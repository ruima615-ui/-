import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_ollama import OllamaEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.core.config import COURSE_MATERIAL_DIR
from app.core.config import COURSE_VECTOR_DIR
from app.core.database import SessionLocal
from app.models.entities import CourseMaterial
from app.models.entities import CourseMaterialIndex
from app.models.entities import CourseMaterialEmbeddingIndex
from app.models.entities import CourseMaterialChunkTopic, Question
from app.services.embedding_service import CourseEmbeddings, DIMENSION, PRIMARY_MODEL, BACKUP_MODEL
from app.repositories.course_material_repository import (
    get_course_material,
)
from app.repositories.material_index_repository import (
    delete_material_index,
    get_material_index,
    list_ready_materials,
    save_material_index,
    get_embedding_index,
    list_embedding_indexes,
)


COURSE_VECTOR_COLLECTION = "course_material_chunks"
# 旧 collection 保留给现有单模型索引；双后端索引使用独立 collection。
COURSE_VECTOR_COLLECTION_PRIMARY = "course_material_chunks_primary"
COURSE_VECTOR_COLLECTION_BACKUP = "course_material_chunks_backup"
COURSE_VECTOR_COLLECTIONS = {
    "primary": COURSE_VECTOR_COLLECTION_PRIMARY,
    "backup": COURSE_VECTOR_COLLECTION_BACKUP,
}
COURSE_EMBEDDING_MODELS = {"primary": PRIMARY_MODEL, "backup": BACKUP_MODEL}
COURSE_EMBEDDING_MODEL = "bge-m3:latest"
COURSE_EMBEDDING_BASE_URL = "http://127.0.0.1:11434"
MATERIAL_CHUNK_SIZE = 800
MATERIAL_CHUNK_OVERLAP = 120


def build_course_vector_store(
    *,
    embedding_function: Embeddings | None = None,
    persist_directory: Path | None = None,
    chroma_client=None,
    backend: str | None = None,
) -> Chroma:
    """连接旧 collection，或显式连接某一 embedding 后端的独立 collection。"""

    if backend is None:
        collection_name = COURSE_VECTOR_COLLECTION
    else:
        try:
            collection_name = COURSE_VECTOR_COLLECTIONS[backend]
        except KeyError as exc:
            raise ValueError(f"未知的向量后端：{backend}") from exc
        if embedding_function is None:
            raise ValueError("双后端 collection 必须显式提供对应的 embedding_function")

    embeddings = embedding_function or OllamaEmbeddings(
        model=COURSE_EMBEDDING_MODEL,
        base_url=COURSE_EMBEDDING_BASE_URL,
    )
    common_arguments = {
        "collection_name": collection_name,
        "embedding_function": embeddings,
        "collection_metadata": {"hnsw:space": "cosine"},
    }

    if chroma_client is not None:
        return Chroma(
            client=chroma_client,
            **common_arguments,
        )

    directory = persist_directory or COURSE_VECTOR_DIR
    directory.mkdir(parents=True, exist_ok=True)
    return Chroma(
        persist_directory=str(directory),
        **common_arguments,
    )


def clean_material_text(text: str) -> str:
    """清除控制字符和过量空白，同时保留段落边界。"""

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _get_section_title(
    chunk_text: str,
    fallback_topic: str,
) -> str:
    for line in chunk_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title and not re.fullmatch(r"第\s*\d+\s*页", title):
                return title[:200]

    return fallback_topic[:200]


def split_topic_candidates(value: str) -> list[str]:
    """教师可提供多个候选知识点；保留旧资料的单标签格式。"""
    return list(dict.fromkeys(
        item.strip() for item in re.split(r"[,，;；\n]", value)
        if item.strip() and item.strip() != "通用"
    ))


def _document_headings(text: str) -> list[tuple[int, str]]:
    """从 Markdown、幻灯片及常见编号标题中提取可供人工复核的章节名。"""
    pattern = re.compile(r"(?m)^[ \t]*(?:#{1,6}[ \t]+|(?:第[一二三四五六七八九十\d]+[章节]|\d+[.、])[ \t]*)([^\n]+)")
    headings = []
    for match in pattern.finditer(text):
        title = match.group(1).strip(" #：:.-")
        if title and len(title) <= 60 and not re.fullmatch(r"第\s*\d+\s*页", title):
            headings.append((match.start(), title))
    return headings


def _normalized_topic(value: str) -> str:
    return "".join(char for char in value.casefold() if char.isalnum())


def _heading_matches_topic(heading: str, topic: str) -> bool:
    heading_text = _normalized_topic(heading)
    topic_text = _normalized_topic(topic)
    if not heading_text or not topic_text:
        return False
    if topic_text in heading_text or (heading_text in topic_text and len(heading_text) >= 2):
        return True
    # 只用于待教师确认的建议：例如“列表索引”可匹配“Python列表”。
    parts = re.findall(r"[\u4e00-\u9fff]+|[a-z0-9]+", topic.casefold())
    for part in parts:
        if len(part) >= 2 and part in heading_text:
            return True
        if len(part) >= 4 and re.search(r"[\u4e00-\u9fff]", part):
            if any(part[index:index + 2] in heading_text for index in range(len(part) - 1)):
                return True
    return False


def _suggest_chunk_topics(
    chunk_text: str, candidates: list[str], *, section: str,
    trust_single_declared_topic: bool,
) -> list[str]:
    if trust_single_declared_topic:
        return candidates.copy()
    normalized = _normalized_topic(chunk_text)
    return [topic for topic in candidates
            if _normalized_topic(topic) in normalized or _heading_matches_topic(section, topic)]


def build_material_chunk_documents(
    *,
    material: CourseMaterial,
    text: str,
    chunk_size: int = MATERIAL_CHUNK_SIZE,
    chunk_overlap: int = MATERIAL_CHUNK_OVERLAP,
    candidate_topics: list[str] | None = None,
    topic_overrides: dict[int, dict] | None = None,
) -> tuple[list[Document], list[str]]:
    """将一份资料切分成带来源信息的 LangChain Documents。"""

    if chunk_size <= 0:
        raise ValueError("chunk_size 必须大于 0")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError(
            "chunk_overlap 必须大于等于 0 且小于 chunk_size"
        )

    cleaned_text = clean_material_text(text)
    if not cleaned_text:
        raise ValueError("资料解析文本为空，无法建立索引")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=[
            "\n## ",
            "\n### ",
            "\n\n",
            "\n",
            "。",
            "；",
            " ",
            "",
        ],
    )
    chunk_texts = splitter.split_text(cleaned_text)
    chunk_count = len(chunk_texts)
    headings = _document_headings(cleaned_text)
    documents = []
    chunk_ids = []

    candidates = candidate_topics if candidate_topics is not None else split_topic_candidates(material.topic)
    trust_single_declared_topic = material.topic != "通用" and len(candidates) == 1
    scan_from = 0
    for chunk_index, chunk_text in enumerate(chunk_texts):
        anchor = chunk_text[:min(24, len(chunk_text))]
        position = cleaned_text.find(anchor, scan_from)
        if position < 0:
            position = cleaned_text.find(anchor)
        if position < 0:
            position = scan_from
        scan_from = min(len(cleaned_text), max(position + len(chunk_text) - chunk_overlap, position + 1))
        preceding = [title for start, title in headings if start <= position]
        section = _get_section_title(chunk_text, preceding[-1] if preceding else material.title)
        content_hash = hashlib.sha256(
            chunk_text.encode("utf-8")
        ).hexdigest()[:16]
        base_chunk_id = (
            f"{material.id}:chunk:{chunk_index}:{content_hash}"
        )
        suggested = _suggest_chunk_topics(
            chunk_text, candidates, section=section,
            trust_single_declared_topic=trust_single_declared_topic)
        override = (topic_overrides or {}).get(chunk_index)
        reviewed = bool(override and override["content_hash"] == content_hash)
        topics = override["topics"] if reviewed else suggested
        # 未识别到知识点的片段仅归入通用；不得假定它匹配所有候选知识点。
        topics = topics or ["通用"]
        common_metadata = {
            "course_id": material.course_id,
            "material_id": material.id,
            "material_title": material.title,
            "source_type": material.source_type,
            "original_filename": material.original_filename,
            "uploaded_by": material.uploaded_by,
            "chunk_index": chunk_index,
            "chunk_count": chunk_count,
            "section": section,
        }
        for topic in topics:
            chunk_id = (base_chunk_id if len(topics) == 1 else
                        f"{base_chunk_id}:{hashlib.sha256(topic.encode('utf-8')).hexdigest()[:8]}")
            documents.append(Document(page_content=chunk_text, metadata={
                **common_metadata, "topic": topic, "chunk_id": chunk_id,
                "topic_reviewed": reviewed,
                "topic_review_required": not trust_single_declared_topic,
            }))
            chunk_ids.append(chunk_id)

    return documents, chunk_ids


def get_material_topic_assignments(
    db: Session, material: CourseMaterial, text: str,
) -> tuple[list[str], dict[int, dict]]:
    declared = split_topic_candidates(material.topic)
    course_topics = sorted(set(db.scalars(
        select(Question.topic).where(Question.course_id == material.course_id)
    ).all()))
    # 优先使用课程题库的受控词表；无题库时从资料章节标题提取待复核标签。
    headings = list(dict.fromkeys(title for _, title in _document_headings(clean_material_text(text))))
    candidates = declared or course_topics or headings[:30]
    overrides = {row.chunk_index: {"topics": row.topics, "content_hash": row.content_hash}
                 for row in db.scalars(
        select(CourseMaterialChunkTopic).where(CourseMaterialChunkTopic.material_id == material.id)
    ).all()}
    return candidates, overrides


def _read_extracted_material_text(
    material: CourseMaterial,
    storage_root: Path,
) -> str:
    if not material.extracted_text_path:
        raise ValueError("课程资料没有可索引的解析文本")

    root = storage_root.resolve()
    text_path = (
        root / material.extracted_text_path
    ).resolve()

    try:
        text_path.relative_to(root)
    except ValueError as error:
        raise ValueError("课程资料解析文本路径无效") from error

    if not text_path.is_file():
        raise ValueError("课程资料解析文本不存在")

    return text_path.read_text(encoding="utf-8")


def _set_index_failed(
    *,
    db: Session,
    index_record: CourseMaterialIndex,
    error: Exception,
) -> None:
    index_record.status = "failed"
    index_record.index_error = str(error)[:2000]
    index_record.indexed_at = None
    db.add(index_record)
    db.commit()


def index_course_material(
    *,
    db: Session,
    material_id: str,
    vector_store: Chroma | None = None,
    embedding_function: Embeddings | None = None,
    storage_root: Path | None = None,
    persist_directory: Path | None = None,
    chunk_size: int = MATERIAL_CHUNK_SIZE,
    chunk_overlap: int = MATERIAL_CHUNK_OVERLAP,
    embedding_model_name: str = COURSE_EMBEDDING_MODEL,
) -> dict:
    """把一份已解析课程资料幂等写入 Chroma。"""

    material = get_course_material(db, material_id)
    if material is None:
        raise ValueError("课程资料不存在")
    if material.status != "ready_for_indexing":
        raise ValueError("课程资料当前不能建立向量索引")

    root = storage_root or COURSE_MATERIAL_DIR
    text = _read_extracted_material_text(material, root)
    cleaned_text = clean_material_text(text)
    content_checksum = hashlib.sha256(
        cleaned_text.encode("utf-8")
    ).hexdigest()

    existing_index = get_material_index(db, material.id)
    if (
        existing_index is not None
        and existing_index.status == "indexed"
        and existing_index.content_checksum == content_checksum
        and existing_index.embedding_model == embedding_model_name
        and existing_index.chunk_size == chunk_size
        and existing_index.chunk_overlap == chunk_overlap
    ):
        return {
            "status": "already_indexed",
            "course_id": material.course_id,
            "material_id": material.id,
            "chunk_count": existing_index.chunk_count,
            "collection_name": existing_index.collection_name,
        }

    documents, chunk_ids = build_material_chunk_documents(
        material=material,
        text=cleaned_text,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    store = vector_store or build_course_vector_store(
        embedding_function=embedding_function,
        persist_directory=persist_directory,
    )

    if existing_index is None:
        existing_index = CourseMaterialIndex(
            material_id=material.id,
            course_id=material.course_id,
            collection_name=COURSE_VECTOR_COLLECTION,
            embedding_model=embedding_model_name,
            content_checksum=content_checksum,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            chunk_count=0,
            status="indexing",
        )
    else:
        existing_index.status = "indexing"
        existing_index.index_error = None
        existing_index.indexed_at = None
        existing_index.content_checksum = content_checksum
        existing_index.embedding_model = embedding_model_name
        existing_index.chunk_size = chunk_size
        existing_index.chunk_overlap = chunk_overlap

    save_material_index(db, existing_index)
    db.commit()

    try:
        previous = store.get(
            where={"material_id": material.id},
            include=[],
        )
        previous_ids = previous.get("ids", [])
        if previous_ids:
            store.delete(ids=previous_ids)

        store.add_documents(
            documents=documents,
            ids=chunk_ids,
        )

        existing_index.status = "indexed"
        existing_index.index_error = None
        existing_index.chunk_count = len(documents)
        existing_index.indexed_at = datetime.utcnow()
        db.add(existing_index)
        db.commit()
        db.refresh(existing_index)
    except Exception as error:
        db.rollback()
        _set_index_failed(
            db=db,
            index_record=existing_index,
            error=error,
        )
        raise

    return {
        "status": "indexed",
        "course_id": material.course_id,
        "material_id": material.id,
        "chunk_count": len(documents),
        "chunk_ids": chunk_ids,
        "collection_name": COURSE_VECTOR_COLLECTION,
    }


def index_ready_course_materials(
    *,
    db: Session,
    course_id: str | None = None,
    vector_store: Chroma | None = None,
    embedding_function: Embeddings | None = None,
    storage_root: Path | None = None,
    persist_directory: Path | None = None,
) -> list[dict]:
    """批量索引全部或指定课程中已解析的资料。"""

    materials = list_ready_materials(
        db=db,
        course_id=course_id,
    )
    store = vector_store or build_course_vector_store(
        embedding_function=embedding_function,
        persist_directory=persist_directory,
    )

    return [
        index_course_material(
            db=db,
            material_id=material.id,
            vector_store=store,
            storage_root=storage_root,
        )
        for material in materials
    ]


def index_course_material_dual(
    *,
    db: Session,
    material_id: str,
    vector_stores: dict[str, Chroma] | None = None,
    embedding_functions: dict[str, Embeddings] | None = None,
    storage_root: Path | None = None,
    persist_directory: Path | None = None,
    chunk_size: int = MATERIAL_CHUNK_SIZE,
    chunk_overlap: int = MATERIAL_CHUNK_OVERLAP,
) -> dict:
    """同一批 Chunk 分别写入主、备 collection，状态独立提交。"""
    material = get_course_material(db, material_id)
    if material is None:
        raise ValueError("课程资料不存在")
    if material.status != "ready_for_indexing":
        raise ValueError("课程资料当前不能建立向量索引")

    text = clean_material_text(_read_extracted_material_text(
        material, storage_root or COURSE_MATERIAL_DIR))
    candidates, overrides = get_material_topic_assignments(db, material, text)
    # 标签变化也应触发重建；否则旧向量 metadata 会继续使用过期知识点。
    checksum = hashlib.sha256(json.dumps({
        "text": text, "candidates": candidates, "overrides": overrides,
        "topic_schema": 3,
    }, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    documents, chunk_ids = build_material_chunk_documents(
        material=material, text=text, chunk_size=chunk_size, chunk_overlap=chunk_overlap,
        candidate_topics=candidates, topic_overrides=overrides)
    outcomes = {}
    for backend in ("primary", "backup"):
        collection_name = COURSE_VECTOR_COLLECTIONS[backend]
        model_name = COURSE_EMBEDDING_MODELS[backend]
        record = get_embedding_index(db, material.id, backend)
        if (record is not None and record.status == "indexed"
                and record.collection_name == collection_name
                and record.embedding_model == model_name and record.dimension == DIMENSION
                and record.content_checksum == checksum and record.chunk_size == chunk_size
                and record.chunk_overlap == chunk_overlap):
            outcomes[backend] = "already_indexed"
            continue
        if record is None:
            record = CourseMaterialEmbeddingIndex(
                material_id=material.id, backend=backend, course_id=material.course_id,
                collection_name=collection_name, embedding_model=model_name,
                dimension=DIMENSION, content_checksum=checksum, chunk_size=chunk_size,
                chunk_overlap=chunk_overlap, chunk_count=0)
        record.status = "indexing"
        record.index_error = None
        record.indexed_at = None
        record.collection_name = collection_name
        record.embedding_model = model_name
        record.dimension = DIMENSION
        record.content_checksum = checksum
        record.chunk_size = chunk_size
        record.chunk_overlap = chunk_overlap
        db.add(record)
        db.commit()
        try:
            store = (vector_stores or {}).get(backend) or build_course_vector_store(
                backend=backend,
                embedding_function=(embedding_functions or {}).get(backend) or CourseEmbeddings(backend),
                persist_directory=persist_directory,
            )
            previous_ids = store.get(where={"material_id": material.id}, include=[]).get("ids", [])
            if previous_ids:
                store.delete(ids=previous_ids)
            store.add_documents(documents=documents, ids=chunk_ids)
            record.status = "indexed"
            record.chunk_count = len(chunk_ids)
            record.indexed_at = datetime.utcnow()
            db.add(record)
            db.commit()
            outcomes[backend] = "indexed"
        except Exception as exc:
            db.rollback()
            record = get_embedding_index(db, material.id, backend)
            record.status = "failed"
            record.chunk_count = 0
            record.index_error = f"{type(exc).__name__}: {exc}"[:2000]
            record.indexed_at = None
            db.add(record)
            db.commit()
            outcomes[backend] = "failed"
    return {"material_id": material.id, "course_id": material.course_id,
            "chunk_count": len(chunk_ids), "backends": outcomes}


def index_ready_course_materials_dual(*, db: Session, course_id: str | None = None,
                                      **kwargs) -> list[dict]:
    return [index_course_material_dual(db=db, material_id=item.id, **kwargs)
            for item in list_ready_materials(db=db, course_id=course_id)]


def index_course_material_in_background(
    material_id: str,
) -> None:
    """供 FastAPI 后台任务使用，并独立管理数据库会话。"""

    db = SessionLocal()
    try:
        material = get_course_material(db, material_id)
        if material is None:
            raise ValueError("课程资料不存在")
        # 首次启用双索引时，同课程旧资料也需要回填，避免新旧索引混用漏资料。
        results = index_ready_course_materials_dual(db=db, course_id=material.course_id)
        for result in results:
            if all(status == "failed" for status in result["backends"].values()):
                print(f"课程资料双后端索引均失败：{result['material_id']}")
    except Exception as error:
        # 双后端索引在各自的状态行记录失败原因。
        print(
            f"课程资料索引失败：{material_id}：{error}"
        )
    finally:
        db.close()


def remove_course_material_from_index(
    *,
    db: Session,
    material_id: str,
    vector_store: Chroma | None = None,
    vector_stores: dict[str, Chroma] | None = None,
) -> bool:
    """删除资料对应的全部 Chroma Chunk 和索引状态。"""

    index_record = get_material_index(db, material_id)
    dual_records = list_embedding_indexes(db, material_id)
    if index_record is None and not dual_records:
        return False

    for record in dual_records:
        backend = record.backend
        store = (vector_stores or {}).get(backend) or build_course_vector_store(
            backend=backend, embedding_function=CourseEmbeddings(backend))
        chunk_ids = store.get(where={"material_id": material_id}, include=[]).get("ids", [])
        if chunk_ids:
            store.delete(ids=chunk_ids)
        db.delete(record)
    if index_record is not None:
        store = vector_store or build_course_vector_store()
        chunk_ids = store.get(where={"material_id": material_id}, include=[]).get("ids", [])
        if chunk_ids:
            store.delete(ids=chunk_ids)
        delete_material_index(db, index_record)
    db.flush()
    return True
