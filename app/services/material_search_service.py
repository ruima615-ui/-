from langchain_chroma import Chroma
from sqlalchemy.orm import Session

from app.services.material_index_service import (
    build_course_vector_store,
    COURSE_VECTOR_COLLECTIONS,
)
from app.services.embedding_service import CourseEmbeddings, EmbeddingUnavailable
from app.core.database import SessionLocal
from app.repositories.material_index_repository import (
    has_any_embedding_indexes, has_indexed_course_materials,
    ready_embedding_material_ids,
)


MAX_RETRIEVAL_TOP_K = 10


def get_indexed_course_material_chunk(
    *,
    course_id: str,
    chunk_id: str,
    vector_store: Chroma | None = None,
) -> dict:
    """按稳定 Chunk ID 找回原文，并在返回前核对课程归属。"""
    if not chunk_id:
        return {"status": "invalid_chunk_id", "course_id": course_id}

    store = vector_store or build_course_vector_store()
    stored = store.get(ids=[chunk_id], include=["documents", "metadatas"])
    if not stored.get("ids"):
        return {"status": "chunk_not_found", "course_id": course_id}

    metadata = stored["metadatas"][0]
    if metadata.get("course_id") != course_id:
        # 不向调用方暴露其他课程的资料是否存在。
        return {"status": "chunk_not_found", "course_id": course_id}
    if metadata.get("topic_review_required") and not metadata.get("topic_reviewed"):
        return {"status": "chunk_needs_review", "course_id": course_id}

    return {
        "status": "success",
        "course_id": course_id,
        "topic": metadata.get("topic"),
        "chunk_id": chunk_id,
        "material_id": metadata.get("material_id"),
        "original_filename": metadata.get("original_filename"),
        "source_type": metadata.get("source_type"),
        "content": stored["documents"][0],
    }


def _normalize_topic(topic: str) -> str:
    return "".join(topic.casefold().split())


def _get_indexed_topics(
    *,
    vector_store: Chroma,
    course_id: str,
) -> list[str]:
    """读取一门课程在 Chroma 中真实存在的知识点名称。"""

    stored = vector_store.get(
        where={"course_id": course_id},
        include=["metadatas"],
    )
    topics = {
        metadata.get("topic")
        for metadata in stored.get("metadatas", [])
        if (
            isinstance(metadata, dict)
            and isinstance(metadata.get("topic"), str)
            and metadata["topic"].strip()
        )
    }
    return sorted(topics)


def resolve_indexed_topic(
    *,
    requested_topic: str,
    available_topics: list[str],
) -> str | None:
    """用确定性名称规则把请求知识点映射到已索引知识点。"""

    requested_normalized = _normalize_topic(
        requested_topic
    )
    if not requested_normalized:
        return None

    for topic in available_topics:
        if _normalize_topic(topic) == requested_normalized:
            return topic

    candidates = [
        topic
        for topic in available_topics
        if (
            _normalize_topic(topic) in requested_normalized
            or requested_normalized in _normalize_topic(topic)
        )
    ]

    if not candidates:
        return None

    return max(
        candidates,
        key=lambda value: len(_normalize_topic(value)),
    )


def _build_course_topic_filter(
    *,
    course_id: str,
    topic: str,
) -> dict:
    """构造服务端控制的课程与知识点联合过滤条件。"""

    return {
        "$and": [
            {"course_id": {"$eq": course_id}},
            {"topic": {"$eq": topic}},
        ]
    }


def search_indexed_course_materials(
    *,
    course_id: str,
    topic: str,
    query: str,
    top_k: int = 3,
    vector_store: Chroma | None = None,
    allowed_material_ids: set[str] | None = None,
) -> dict:
    """只在指定课程和知识点的 Chroma Chunk 中进行语义检索。"""

    if not isinstance(course_id, str) or not course_id.strip():
        return {
            "status": "invalid_course_id",
            "course_id": course_id,
            "message": "课程编号不能为空",
        }
    if not isinstance(topic, str) or not topic.strip():
        return {
            "status": "invalid_topic",
            "course_id": course_id,
            "message": "知识点不能为空",
        }
    if not isinstance(query, str) or not query.strip():
        return {
            "status": "invalid_query",
            "course_id": course_id,
            "topic": topic,
            "message": "检索问题不能为空",
        }
    if (
        type(top_k) is not int
        or top_k < 1
        or top_k > MAX_RETRIEVAL_TOP_K
    ):
        return {
            "status": "invalid_top_k",
            "course_id": course_id,
            "topic": topic,
            "message": (
                f"top_k 必须是 1 到 {MAX_RETRIEVAL_TOP_K} 的整数"
            ),
        }

    store = vector_store or build_course_vector_store()
    available_topics = _get_indexed_topics(
        vector_store=store,
        course_id=course_id,
    )

    if not available_topics:
        return {
            "status": "course_materials_not_indexed",
            "course_id": course_id,
            "requested_topic": topic,
            "query": query,
            "message": "当前课程尚无可检索的向量资料",
        }

    resolved_topic = resolve_indexed_topic(
        requested_topic=topic,
        available_topics=available_topics,
    )

    if resolved_topic is None:
        # 未复核片段不能冒充该知识点的可信证据；仅返回课程范围内的候选，
        # 供教师检查标签后重新索引。
        if "通用" in available_topics:
            generic_filter = _build_course_topic_filter(course_id=course_id, topic="通用")
            if allowed_material_ids is not None:
                if not allowed_material_ids:
                    return {"status": "course_materials_not_indexed", "course_id": course_id,
                            "requested_topic": topic, "query": query}
                generic_filter["$and"].append({"material_id": {
                    "$in": sorted(allowed_material_ids)}})
            candidates = store.similarity_search_with_relevance_scores(
                query=f"{topic} {query}", k=top_k, filter=generic_filter)
            if candidates:
                return {
                    "status": "topic_candidates_need_review", "course_id": course_id,
                    "requested_topic": topic, "query": query,
                    "message": "发现未标注知识点的资料片段，请教师核对标签后再用于复习计划",
                    "candidates": [{"chunk_id": doc.metadata.get("chunk_id"),
                                    "material_id": doc.metadata.get("material_id"),
                                    "section": doc.metadata.get("section")}
                                   for doc, _ in candidates],
                }
        return {
            "status": "topic_materials_not_indexed",
            "course_id": course_id,
            "requested_topic": topic,
            "query": query,
            "available_topics": available_topics,
            "message": "当前课程没有该知识点的已索引资料",
        }

    metadata_filter = _build_course_topic_filter(
        course_id=course_id,
        topic=resolved_topic,
    )
    if allowed_material_ids is not None:
        if not allowed_material_ids:
            return {"status": "course_materials_not_indexed", "course_id": course_id,
                    "requested_topic": topic, "query": query}
        material_filter = ({"$eq": next(iter(allowed_material_ids))}
                           if len(allowed_material_ids) == 1
                           else {"$in": sorted(allowed_material_ids)})
        metadata_filter["$and"].append({"material_id": material_filter})
    results = store.similarity_search_with_relevance_scores(
        query=query.strip(),
        k=top_k * 8,
        filter=metadata_filter,
    )

    retrieved_chunks = []
    unreviewed_chunks = []
    source_ids = set()

    for document, relevance_score in results:
        metadata = document.metadata

        # 双重检查，避免底层过滤配置错误造成越权结果。
        if metadata.get("course_id") != course_id:
            raise RuntimeError("向量检索返回了其他课程的资料")
        if metadata.get("topic") != resolved_topic:
            raise RuntimeError("向量检索返回了其他知识点的资料")

        material_id = metadata.get("material_id")
        if not isinstance(material_id, str) or not material_id:
            raise RuntimeError("向量检索结果缺少 material_id 来源信息")
        if allowed_material_ids is not None and material_id not in allowed_material_ids:
            raise RuntimeError("向量检索返回了尚未就绪的资料")
        if metadata.get("topic_review_required") and not metadata.get("topic_reviewed"):
            unreviewed_chunks.append({"chunk_id": metadata.get("chunk_id"),
                                      "material_id": material_id,
                                      "section": metadata.get("section")})
            continue
        source_ids.add(material_id)
        retrieved_chunks.append({
            "chunk_id": metadata.get("chunk_id"),
            "content": document.page_content,
            "relevance_score": round(
                float(relevance_score),
                6,
            ),
            "course_id": metadata.get("course_id"),
            "topic": metadata.get("topic"),
            "material_id": material_id,
            "material_title": metadata.get(
                "material_title"
            ),
            "section": metadata.get("section"),
            "source_type": metadata.get("source_type"),
            "original_filename": metadata.get(
                "original_filename"
            ),
            "chunk_index": metadata.get("chunk_index"),
        })
        if len(retrieved_chunks) >= top_k:
            break

    if not retrieved_chunks:
        if unreviewed_chunks:
            return {"status": "topic_candidates_need_review", "course_id": course_id,
                    "requested_topic": topic, "topic": resolved_topic, "query": query,
                    "message": "找到该知识点的片段建议，请教师核对标签后再用于复习计划",
                    "candidates": unreviewed_chunks[:top_k]}
        return {
            "status": "no_relevant_content",
            "course_id": course_id,
            "requested_topic": topic,
            "topic": resolved_topic,
            "query": query,
            "message": "知识点资料存在，但没有检索到相关内容",
        }

    return {
        "status": "success",
        "retrieval_method": (
            "chroma_cosine_similarity_with_metadata_filter"
        ),
        "course_id": course_id,
        "requested_topic": topic,
        "topic": resolved_topic,
        "query": query,
        "top_k": top_k,
        "available_topics": available_topics,
        "source_count": len(source_ids),
        "retrieved_chunks": retrieved_chunks,
    }


def search_course_materials_with_fallback(
    *, course_id: str, topic: str, query: str, top_k: int = 3,
    db: Session | None = None, vector_stores: dict[str, Chroma] | None = None,
) -> dict:
    """主索引优先；主向量服务不可用时，仅查询已就绪的备份索引。"""
    if not isinstance(course_id, str) or not course_id.strip():
        return {"status": "invalid_course_id", "course_id": course_id,
                "message": "课程编号不能为空"}
    if not isinstance(topic, str) or not topic.strip():
        return {"status": "invalid_topic", "course_id": course_id,
                "message": "知识点不能为空"}
    if not isinstance(query, str) or not query.strip():
        return {"status": "invalid_query", "course_id": course_id, "topic": topic,
                "message": "检索问题不能为空"}
    if type(top_k) is not int or not 1 <= top_k <= MAX_RETRIEVAL_TOP_K:
        return {"status": "invalid_top_k", "course_id": course_id, "topic": topic,
                "message": f"top_k 必须是 1 到 {MAX_RETRIEVAL_TOP_K} 的整数"}
    owns_db = db is None
    db = db or SessionLocal()
    try:
        has_dual = has_any_embedding_indexes(db, course_id)
        if not has_dual:
            if has_indexed_course_materials(db, course_id):
                return search_indexed_course_materials(
                    course_id=course_id, topic=topic, query=query, top_k=top_k,
                    vector_store=(vector_stores or {}).get("legacy"))
            return {"status": "course_materials_not_indexed", "course_id": course_id,
                    "requested_topic": topic, "query": query}
        errors = {}
        last_result = None
        for backend in ("primary", "backup"):
            ready_ids = ready_embedding_material_ids(db, course_id, backend)
            if not ready_ids:
                continue
            store = (vector_stores or {}).get(backend) or build_course_vector_store(
                backend=backend, embedding_function=CourseEmbeddings(backend))
            try:
                result = search_indexed_course_materials(
                    course_id=course_id, topic=topic, query=query, top_k=top_k,
                    vector_store=store, allowed_material_ids=ready_ids)
            except EmbeddingUnavailable as exc:
                errors[backend] = str(exc)
                continue
            if result.get("status") in {"course_materials_not_indexed", "topic_materials_not_indexed"}:
                last_result = result
                continue
            result["embedding_backend"] = backend
            result["collection_name"] = COURSE_VECTOR_COLLECTIONS[backend]
            return result
        if last_result is not None and not errors:
            return last_result
        return {"status": "embedding_unavailable" if errors else "course_materials_not_indexed",
                "course_id": course_id, "requested_topic": topic, "query": query,
                "backend_errors": errors}
    finally:
        if owns_db:
            db.close()


def get_course_material_chunk_with_fallback(
    *, course_id: str, chunk_id: str, db: Session | None = None,
    vector_stores: dict[str, Chroma] | None = None,
) -> dict:
    """从已就绪的主/备索引按 ID 回读，兼容旧 collection。"""
    if not chunk_id:
        return {"status": "invalid_chunk_id", "course_id": course_id}
    owns_db = db is None
    db = db or SessionLocal()
    try:
        if has_any_embedding_indexes(db, course_id):
            for backend in ("primary", "backup"):
                ready_ids = ready_embedding_material_ids(db, course_id, backend)
                if not ready_ids:
                    continue
                store = (vector_stores or {}).get(backend) or build_course_vector_store(
                    backend=backend, embedding_function=CourseEmbeddings(backend))
                result = get_indexed_course_material_chunk(
                    course_id=course_id, chunk_id=chunk_id, vector_store=store)
                if result.get("status") == "success" and result.get("material_id") in ready_ids:
                    result["embedding_backend"] = backend
                    return result
            return {"status": "chunk_not_found", "course_id": course_id}
        return get_indexed_course_material_chunk(
            course_id=course_id, chunk_id=chunk_id,
            vector_store=(vector_stores or {}).get("legacy"))
    finally:
        if owns_db:
            db.close()
