import os
import json
import hashlib

from pathlib import Path

import numpy as np
from langchain_ollama import OllamaEmbeddings

from app.core.database import SessionLocal
from app.repositories.material_index_repository import (
    has_indexed_course_materials,
    has_any_embedding_indexes,
)
from app.services.material_search_service import (
    get_course_material_chunk_with_fallback,
    search_course_materials_with_fallback,
)


# 本机Ollama连接不经过代理
os.environ["NO_PROXY"] = "127.0.0.1,localhost"


# 路径配置
BASE_DIR = Path(__file__).resolve().parent
KNOWLEDGE_DIR = BASE_DIR / "knowledge"
CACHE_DIR = BASE_DIR / "vector_cache"

# 确保缓存文件夹存在
CACHE_DIR.mkdir(parents=True, exist_ok=True)



# 关键词检索使用的关键词
SEARCH_KEYWORDS = [
    "列表",
    "索引",
    "下标",
    "越界",
    "IndexError",
    "长度",
    "len",
    "遍历",
    "range",
    "函数",
    "print",
    "return",
    "返回值",
    "None",
    "结果",
    "变量"
]


# Embedding模型名称
EMBEDDING_MODEL = "bge-m3:latest"


# 创建Embedding对象
embedding_model = OllamaEmbeddings(
    model=EMBEDDING_MODEL,
    base_url="http://127.0.0.1:11434"
)


# 程序运行期间使用的内存缓存
CHUNK_VECTOR_CACHE = {}
def load_course_material_index(course_id):
    """
    读取指定课程的资料目录和知识点索引。

    返回值：
    course_dir：课程资料目录
    topic_map：知识点到文件名的映射
    error：失败时的错误结果
    """

    if (
        not isinstance(course_id, str)
        or not course_id.strip()
        or course_id in {".", ".."}
        or "/" in course_id
        or "\\" in course_id
    ):
        return None, None, {
            "status": "invalid_course_id",
            "course_id": course_id,
            "message": "课程编号不合法",
        }

    knowledge_root = KNOWLEDGE_DIR.resolve()
    course_dir = (
        knowledge_root / course_id
    ).resolve()

    # 防止课程编号绕过 knowledge 根目录。
    try:
        course_dir.relative_to(knowledge_root)
    except ValueError:
        return None, None, {
            "status": "invalid_course_id",
            "course_id": course_id,
            "message": "课程资料目录不合法",
        }

    index_path = course_dir / "materials.json"

    if not index_path.is_file():
        return course_dir, None, {
            "status": "course_materials_not_configured",
            "course_id": course_id,
            "message": "当前课程尚未配置学习资料",
        }

    try:
        index_data = json.loads(
            index_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as error:
        return course_dir, None, {
            "status": "material_index_invalid",
            "course_id": course_id,
            "message": (
                f"课程资料索引读取失败：{error}"
            ),
        }

    topic_map = index_data.get("topics")

    if not isinstance(topic_map, dict):
        return course_dir, None, {
            "status": "material_index_invalid",
            "course_id": course_id,
            "message": (
                "materials.json 中缺少 topics 对象"
            ),
        }

    return course_dir, topic_map, None


def split_markdown_by_heading(content):
    """按照Markdown二级标题切分文本"""

    parts = content.split("## ")

    # 文档中没有二级标题
    if len(parts) == 1:
        content = content.strip()

        if content:
            return [content]

        return []

    # 二级标题之前的内容通常是总标题
    document_title = parts[0].strip()
    chunks = []

    for index, part in enumerate(parts[1:], start=1):
        part = part.strip()

        if not part:
            continue

        # 加回被split删除的二级标题符号
        chunk = "## " + part

        # 总标题合并到第一个正文块
        if index == 1 and document_title:
            chunk = document_title + "\n\n" + chunk

        chunks.append(chunk)

    return chunks


def cosine_similarity(vector1, vector2):
    """计算两个向量的余弦相似度"""

    vector1 = np.array(vector1)
    vector2 = np.array(vector2)

    dot_product = np.dot(vector1, vector2)

    vector1_length = np.linalg.norm(vector1)
    vector2_length = np.linalg.norm(vector2)

    similarity = dot_product / (
        vector1_length * vector2_length
    )

    return float(similarity)


def get_chunk_score(item):
    """取得一个文本块的相关性分数"""

    return item["score"]


def get_cached_chunk_vectors(chunks):
    """依次检查内存和磁盘，没有缓存时才计算向量"""

    cache_info = {
        "version": 1,
        "model": EMBEDDING_MODEL,
        "chunks": chunks
    }

    # 转换成顺序稳定的JSON字符串
    cache_text = json.dumps(
        cache_info,
        ensure_ascii=False,
        sort_keys=True
    )

    # 生成缓存编号
    cache_key = hashlib.sha256(
        cache_text.encode("utf-8")
    ).hexdigest()

    # 第一层：内存缓存
    if cache_key in CHUNK_VECTOR_CACHE:
        print("内存缓存命中：复用资料向量")
        return CHUNK_VECTOR_CACHE[cache_key]

    # 缓存文件地址
    cache_file = CACHE_DIR / f"{cache_key}.json"

    # 第二层：磁盘缓存
    if cache_file.exists():
        with cache_file.open("r", encoding="utf-8") as file:
            cached_data = json.load(file)

        chunk_vectors = cached_data["vectors"]

        # 加载到内存，方便后续查询
        CHUNK_VECTOR_CACHE[cache_key] = chunk_vectors

        print("磁盘缓存命中：已加载资料向量")
        return chunk_vectors

    # 第三层：重新计算
    print("缓存未命中：正在计算资料向量")

    chunk_vectors = embedding_model.embed_documents(chunks)

    cached_data = {
        "cache_info": cache_info,
        "vectors": chunk_vectors
    }

    # 写入磁盘
    with cache_file.open("w", encoding="utf-8") as file:
        json.dump(
            cached_data,
            file,
            ensure_ascii=False
        )

    # 写入内存
    CHUNK_VECTOR_CACHE[cache_key] = chunk_vectors

    print("资料向量已保存到磁盘和内存")

    return chunk_vectors


def retrieve_relevant_chunks(chunks, query, top_k=2):
    """根据关键词寻找相关文本块"""

    query_lower = query.lower()
    scored_chunks = []

    for chunk_id, chunk in enumerate(chunks, start=1):
        chunk_lower = chunk.lower()
        matched_keywords = []

        for keyword in SEARCH_KEYWORDS:
            keyword_lower = keyword.lower()

            if (
                keyword_lower in query_lower
                and keyword_lower in chunk_lower
            ):
                matched_keywords.append(keyword)

        score = len(matched_keywords)

        if score > 0:
            scored_chunks.append({
                "chunk_id": chunk_id,
                "score": score,
                "matched_keywords": matched_keywords,
                "content": chunk
            })

    scored_chunks.sort(
        key=get_chunk_score,
        reverse=True
    )

    return scored_chunks[:top_k]


def retrieve_chunks_by_embedding(chunks, query, top_k=2):
    """使用Embedding和余弦相似度检索文本块"""

    if not chunks:
        return []

    # 获取资料向量
    chunk_vectors = get_cached_chunk_vectors(chunks)

    # 生成当前问题的向量
    query_vector = embedding_model.embed_query(query)

    scored_chunks = []

    for index in range(len(chunks)):
        chunk_id = index + 1
        chunk = chunks[index]
        chunk_vector = chunk_vectors[index]

        score = cosine_similarity(
            query_vector,
            chunk_vector
        )

        scored_chunks.append({
            "chunk_id": chunk_id,
            "score": score,
            "content": chunk
        })

    scored_chunks.sort(
        key=get_chunk_score,
        reverse=True
    )

    return scored_chunks[:top_k]

#增加主题名称解析
def resolve_material_topic(
    topic_map,
    requested_topic,
):
    """
    把模型生成的主题名称映射到课程配置中的主题。

    例如：
    Python列表索引 -> Python列表
    Python 列表 -> Python列表
    """

    if not isinstance(requested_topic, str):
        return None

    requested_normalized = "".join(
        requested_topic.casefold().split()
    )

    if not requested_normalized:
        return None

    # 第一优先级：标准化后完全一致。
    for configured_topic in topic_map:
        configured_normalized = "".join(
            configured_topic.casefold().split()
        )

        if (
            requested_normalized
            == configured_normalized
        ):
            return configured_topic

    # 第二优先级：一个主题包含另一个主题。
    candidates = []

    for configured_topic in topic_map:
        configured_normalized = "".join(
            configured_topic.casefold().split()
        )

        if (
            configured_normalized
            in requested_normalized
            or requested_normalized
            in configured_normalized
        ):
            candidates.append(configured_topic)

    if not candidates:
        return None

    # 多个主题都匹配时，优先选择名称更具体的主题。
    return max(
        candidates,
        key=lambda value: len(
            "".join(value.casefold().split())
        ),
    )
TOPIC_MATCH_MIN_SCORE = 0.45


def get_topic_file(topic_config):
    """兼容旧字符串格式和新的结构化格式。"""

    if isinstance(topic_config, str):
        return topic_config

    if isinstance(topic_config, dict):
        return topic_config.get("file")

    return None


def get_topic_routing_text(
    topic,
    topic_config,
):
    """构造用于向量匹配的 topic 说明文本。"""

    if isinstance(topic_config, dict):
        description = topic_config.get(
            "description",
            "",
        )
    else:
        description = ""

    return f"{topic}\n{description}".strip()


def resolve_material_topic_by_embedding(
    topic_map,
    query,
):
    """
    比较用户问题与所有课程 topic 的向量相似度。
    """

    if not isinstance(query, str) or not query.strip():
        return None, []

    topics = list(topic_map.keys())

    routing_texts = [
        get_topic_routing_text(
            topic=topic,
            topic_config=topic_map[topic],
        )
        for topic in topics
    ]

    # 复用已有的内存和磁盘向量缓存。
    topic_vectors = get_cached_chunk_vectors(
        routing_texts
    )
    query_vector = embedding_model.embed_query(
        query
    )

    candidates = []

    for topic, topic_vector in zip(
        topics,
        topic_vectors,
    ):
        score = cosine_similarity(
            query_vector,
            topic_vector,
        )

        candidates.append({
            "topic": topic,
            "score": score,
        })

    candidates.sort(
        key=lambda item: item["score"],
        reverse=True,
    )

    if not candidates:
        return None, []

    best_match = candidates[0]

    if (
        best_match["score"]
        < TOPIC_MATCH_MIN_SCORE
    ):
        return None, candidates

    return best_match, candidates
#在指定课程的资料范围内检索相关内容
def search_legacy_learning_material(
    course_id,
    topic,
    query,
):
    """
    在指定课程范围内，先进行语义 topic 路由，再检索相关资料块。
    """

    course_dir, topic_map, error = (
        load_course_material_index(course_id)
    )

    if error is not None:
        return error

    requested_topic = topic

    best_match, topic_candidates = (
        resolve_material_topic_by_embedding(
            topic_map=topic_map,
            query=query,
        )
    )

    if best_match is None:
        return {
            "status": "no_relevant_topic",
            "course_id": course_id,
            "requested_topic": requested_topic,
            "query": query,
            "available_topics": sorted(
                topic_map.keys()
            ),
            "topic_candidates": (
                topic_candidates[:3]
            ),
            "message": (
                "用户问题与当前课程知识点的"
                "相关度不足"
            ),
        }

    resolved_topic = best_match["topic"]
    topic_config = topic_map[resolved_topic]
    file_name = get_topic_file(topic_config)

    if (
        not isinstance(file_name, str)
        or not file_name.strip()
    ):
        return {
            "status": "material_index_invalid",
            "course_id": course_id,
            "topic": resolved_topic,
            "message": "资料文件配置格式错误",
        }

    file_path = (
        course_dir / file_name
    ).resolve()

    # materials.json 中的文件名不能越过课程目录。
    try:
        file_path.relative_to(course_dir)
    except ValueError:
        return {
            "status": "invalid_material_path",
            "course_id": course_id,
            "topic": resolved_topic,
            "source": file_name,
            "message": "课程资料文件路径不合法",
        }

    if not file_path.is_file():
        return {
            "status": "file_not_found",
            "course_id": course_id,
            "topic": resolved_topic,
            "source": file_name,
            "message": (
                f"没有找到课程资料文件：{file_name}"
            ),
        }

    try:
        content = file_path.read_text(
            encoding="utf-8"
        )
    except OSError as error:
        return {
            "status": "material_read_failed",
            "course_id": course_id,
            "topic": resolved_topic,
            "source": file_name,
            "message": f"读取课程资料失败：{error}",
        }

    chunks = split_markdown_by_heading(content)

    relevant_chunks = retrieve_chunks_by_embedding(
        chunks=chunks,
        query=query,
        top_k=3,
    )

    if not relevant_chunks:
        return {
            "status": "no_relevant_content",
            "course_id": course_id,
            "topic": resolved_topic,
            "source": file_name,
            "message": (
                "资料文件存在，但没有找到相关内容"
            ),
        }

    return {
        "status": "success",
        "retrieval_method": (
            "semantic_topic_routing"
            "+embedding_cosine_similarity"
        ),
        "course_id": course_id,
        "requested_topic": requested_topic,
        "topic": resolved_topic,
        "topic_match_score": best_match["score"],
        "topic_candidates": topic_candidates[:3],
        "query": query,
        "source": file_name,
        "total_chunks": len(chunks),
        "retrieved_chunks": relevant_chunks,
    }


def searchlearningmaterial(
    course_id,
    topic,
    query,
):
    """
    优先检索教师/官方资料的 Chroma 索引；
    课程尚未迁移到新索引时兼容旧 knowledge 目录。
    """

    db = SessionLocal()
    try:
        use_chroma = has_indexed_course_materials(
            db=db,
            course_id=course_id,
        ) or has_any_embedding_indexes(db, course_id)
    finally:
        db.close()

    if use_chroma:
        return search_course_materials_with_fallback(
            course_id=course_id,
            topic=topic,
            query=query,
            top_k=3,
        )

    legacy_result = search_legacy_learning_material(
        course_id=course_id,
        topic=topic,
        query=query,
    )
    legacy_result["index_backend"] = "legacy_knowledge_directory"
    return legacy_result


def get_course_material_chunk(course_id, chunk_id, topic=None):
    """按 ID 读取当前课程资料块；兼容 Chroma 和旧版 Markdown 索引。"""
    # Chroma ID 含资料 ID 和内容哈希；旧版 ID 是从 1 开始的块序号。
    if isinstance(chunk_id, str) and not chunk_id.isdecimal():
        return get_course_material_chunk_with_fallback(
            course_id=course_id,
            chunk_id=chunk_id,
        )

    course_dir, topic_map, error = load_course_material_index(course_id)
    if error is not None:
        return error
    if not isinstance(topic, str) or topic not in topic_map:
        return {"status": "topic_not_found", "course_id": course_id}
    if not isinstance(chunk_id, str) or not chunk_id.isdecimal():
        return {"status": "invalid_chunk_id", "course_id": course_id}

    file_name = get_topic_file(topic_map[topic])
    if not isinstance(file_name, str):
        return {"status": "material_index_invalid", "course_id": course_id}
    file_path = (course_dir / file_name).resolve()
    try:
        file_path.relative_to(course_dir)
    except ValueError:
        return {"status": "invalid_material_path", "course_id": course_id}
    if not file_path.is_file():
        return {"status": "chunk_not_found", "course_id": course_id}

    chunks = split_markdown_by_heading(file_path.read_text(encoding="utf-8"))
    index = int(chunk_id) - 1
    if index < 0 or index >= len(chunks):
        return {"status": "chunk_not_found", "course_id": course_id}
    return {
        "status": "success",
        "course_id": course_id,
        "topic": topic,
        "chunk_id": chunk_id,
        "source": file_name,
        "content": chunks[index],
        "index_backend": "legacy_knowledge_directory",
    }
