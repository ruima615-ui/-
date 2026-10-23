import hashlib

from fastapi import APIRouter
from fastapi import BackgroundTasks
from fastapi import Depends
from fastapi import File
from fastapi import Form
from fastapi import HTTPException
from fastapi import UploadFile
from fastapi import status
from fastapi import Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.exam_dependencies import get_current_user
from app.api.exam_dependencies import get_db
from app.schemas.course_material import CourseMaterialResponse
from app.schemas.course_material import CourseMaterialTitleUpdate
from app.services.course_material_service import (
    MAX_MATERIAL_SIZE_BYTES,
    create_official_course_material,
    create_teacher_course_material,
    delete_owned_course_material,
    get_admin_course_materials,
    get_teacher_course_materials,
    update_owned_course_material_title,
)
from app.services.material_index_service import (
    index_course_material_in_background,
)
from app.repositories.material_index_repository import get_material_index, list_embedding_indexes
from app.models.entities import CourseMaterialChunkTopic, Question
from app.repositories.course_material_repository import get_course_material
from app.services.material_index_service import (
    _read_extracted_material_text, build_material_chunk_documents,
    get_material_topic_assignments,
)
from app.core.config import COURSE_MATERIAL_DIR
from app.services.teacher_service import require_teacher_course_access


router = APIRouter(
    prefix="/teacher/course-materials",
    tags=["教师课程资料"],
)


class ChunkTopicsUpdate(BaseModel):
    topics: list[str] = Field(min_length=1, max_length=4)


def _editable_teacher_material(db, user, material_id):
    material = get_course_material(db, material_id)
    if material is None:
        raise HTTPException(status_code=404, detail="课程资料不存在")
    if user.role != "teacher" or material.source_type != "teacher" or material.uploaded_by != user.id:
        raise HTTPException(status_code=403, detail="只能复核自己上传的课程资料")
    try:
        require_teacher_course_access(db=db, teacher_id=user.id, course_id=material.course_id)
    except (PermissionError, ValueError) as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    return material


@router.get("/{material_id}/chunk-topics")
def list_teacher_material_chunk_topics(
    material_id: str, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
    db=Depends(get_db), current_user=Depends(get_current_user),
):
    """教师查看按片段生成的建议标签与已复核标签。"""
    material = _editable_teacher_material(db, current_user, material_id)
    if material.status != "ready_for_indexing":
        raise HTTPException(status_code=409, detail="资料解析尚未完成")
    text = _read_extracted_material_text(material, COURSE_MATERIAL_DIR)
    candidates, overrides = get_material_topic_assignments(db, material, text)
    documents, _ = build_material_chunk_documents(
        material=material, text=text, candidate_topics=candidates, topic_overrides=overrides)
    by_index = {}
    for document in documents:
        index = document.metadata["chunk_index"]
        entry = by_index.setdefault(index, {
            "chunk_index": index, "section": document.metadata["section"],
            "content": document.page_content, "topics": [],
            "reviewed": document.metadata["topic_reviewed"],
        })
        entry["topics"].append(document.metadata["topic"])
    chunks = list(by_index.values())
    reviewed_topics = {topic for override in overrides.values() for topic in override["topics"]}
    available = sorted(set(candidates) | reviewed_topics | set(db.scalars(
        select(Question.topic).where(Question.course_id == material.course_id)
    ).all()) | {"通用"})
    return {"material_id": material_id, "candidate_topics": candidates,
            "available_topics": available,
            "total": len(chunks), "chunks": chunks[offset:offset + limit]}


@router.put("/{material_id}/chunk-topics/{chunk_index}")
def update_teacher_material_chunk_topics(
    material_id: str, chunk_index: int, request: ChunkTopicsUpdate,
    background_tasks: BackgroundTasks, db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """保存人工标签；后台重建双索引，避免只改 SQLite 而留下旧向量 metadata。"""
    material = _editable_teacher_material(db, current_user, material_id)
    if material.status != "ready_for_indexing":
        raise HTTPException(status_code=409, detail="资料解析尚未完成")
    if chunk_index < 0:
        raise HTTPException(status_code=422, detail="片段序号无效")
    text = _read_extracted_material_text(material, COURSE_MATERIAL_DIR)
    candidates, overrides = get_material_topic_assignments(db, material, text)
    documents, _ = build_material_chunk_documents(
        material=material, text=text, candidate_topics=candidates, topic_overrides=overrides)
    selected = next((doc for doc in documents if doc.metadata["chunk_index"] == chunk_index), None)
    if selected is None:
        raise HTTPException(status_code=404, detail="资料片段不存在")
    content_hash = hashlib.sha256(selected.page_content.encode("utf-8")).hexdigest()[:16]
    topics = list(dict.fromkeys(item.strip() for item in request.topics))
    if (not topics or len(topics) > 4 or
            ("通用" in topics and len(topics) > 1) or
            any(not topic or len(topic) > 100 or
                any(character in ",，;；\n\r\t" or ord(character) < 32 for character in topic)
                for topic in topics)):
        raise HTTPException(status_code=422, detail="每段需选择 1～4 个知识点；新标签不超过 100 字且不能包含分隔符或控制字符")
    assignment = db.get(CourseMaterialChunkTopic, (material_id, chunk_index))
    if assignment is None:
        assignment = CourseMaterialChunkTopic(material_id=material_id, chunk_index=chunk_index,
                                              content_hash=content_hash, topics=topics)
    else:
        assignment.content_hash = content_hash
        assignment.topics = topics
    db.add(assignment)
    for index in list_embedding_indexes(db, material_id):
        index.status = "indexing"
        db.add(index)
    db.commit()
    background_tasks.add_task(index_course_material_in_background, material_id)
    return {"material_id": material_id, "chunk_index": chunk_index,
            "topics": topics, "status": "reindexing"}


def _to_response(material) -> CourseMaterialResponse:
    return CourseMaterialResponse(
        material_id=material.id,
        course_id=material.course_id,
        uploaded_by=material.uploaded_by,
        source_type=material.source_type,
        topic=material.topic,
        title=material.title,
        original_filename=material.original_filename,
        file_extension=material.file_extension,
        mime_type=material.mime_type,
        size_bytes=material.size_bytes,
        checksum_sha256=material.checksum_sha256,
        extracted_text_length=material.extracted_text_length,
        status=material.status,
        parse_error=material.parse_error,
        created_at=material.created_at,
    )


@router.post(
    "/courses/{course_id}",
    response_model=CourseMaterialResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_course_material(
    course_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    topic: str | None = Form(default=None),
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    data = await file.read(
        MAX_MATERIAL_SIZE_BYTES + 1
    )

    try:
        material = create_teacher_course_material(
            db=db,
            teacher_id=current_user.id,
            course_id=course_id,
            filename=file.filename or "",
            mime_type=file.content_type,
            data=data,
            title=title,
            topic=topic,
        )
    except PermissionError as error:
        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail=str(error),
        ) from error

    if material.status == "ready_for_indexing":
        background_tasks.add_task(
            index_course_material_in_background,
            material.id,
        )

    return _to_response(material)


@router.get(
    "/courses/{course_id}",
    response_model=list[CourseMaterialResponse],
)
def teacher_course_materials(
    course_id: str,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        materials = get_teacher_course_materials(
            db=db,
            teacher_id=current_user.id,
            course_id=course_id,
        )
    except PermissionError as error:
        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        ) from error

    return [
        _to_response(material)
        for material in materials
    ]


@router.get("/courses/{course_id}/index-status")
def teacher_material_index_status(
    course_id: str, db=Depends(get_db), current_user=Depends(get_current_user),
):
    """课程授权通过后，显示资料解析及主/备向量索引的独立状态。"""
    try:
        materials = get_teacher_course_materials(
            db=db, teacher_id=current_user.id, course_id=course_id,
        )
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    result = []
    for material in materials:
        indexes = list_embedding_indexes(db, material.id)
        legacy = get_material_index(db, material.id) if not indexes else None
        result.append({
            "material_id": material.id,
            "title": material.title,
            "filename": material.original_filename,
            "source_type": material.source_type,
            "uploaded_by": material.uploaded_by,
            "topic": material.topic,
            "parse_status": material.status,
            "parse_error": material.parse_error,
            "indexes": {
                row.backend: {
                    "status": row.status,
                    "chunk_count": row.chunk_count,
                    "embedding_model": row.embedding_model,
                    "index_error": row.index_error,
                }
                for row in indexes
            } or ({"legacy": {
                "status": legacy.status, "chunk_count": legacy.chunk_count,
                "embedding_model": legacy.embedding_model,
                "index_error": legacy.index_error,
            }} if legacy else {}),
        })
    return result


@router.patch(
    "/{material_id}",
    response_model=CourseMaterialResponse,
)
def update_teacher_material(
    material_id: str,
    request: CourseMaterialTitleUpdate,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        material = update_owned_course_material_title(
            db=db,
            user_id=current_user.id,
            material_id=material_id,
            title=request.title,
            expected_source_type="teacher",
        )
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    return _to_response(material)


@router.delete(
    "/{material_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_teacher_material(
    material_id: str,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        delete_owned_course_material(
            db=db,
            user_id=current_user.id,
            material_id=material_id,
            expected_source_type="teacher",
        )
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


admin_router = APIRouter(
    prefix="/admin/course-materials",
    tags=["官方课程资料"],
)


@admin_router.post(
    "/courses/{course_id}",
    response_model=CourseMaterialResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_official_course_material(
    course_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    topic: str | None = Form(default=None),
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    data = await file.read(MAX_MATERIAL_SIZE_BYTES + 1)
    try:
        material = create_official_course_material(
            db=db,
            admin_id=current_user.id,
            course_id=course_id,
            filename=file.filename or "",
            mime_type=file.content_type,
            data=data,
            title=title,
            topic=topic,
        )
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    if material.status == "ready_for_indexing":
        background_tasks.add_task(
            index_course_material_in_background,
            material.id,
        )

    return _to_response(material)


@admin_router.get(
    "/courses/{course_id}",
    response_model=list[CourseMaterialResponse],
)
def admin_course_materials(
    course_id: str,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        materials = get_admin_course_materials(
            db=db,
            admin_id=current_user.id,
            course_id=course_id,
        )
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    return [_to_response(material) for material in materials]


@admin_router.patch(
    "/{material_id}",
    response_model=CourseMaterialResponse,
)
def update_official_material(
    material_id: str,
    request: CourseMaterialTitleUpdate,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        material = update_owned_course_material_title(
            db=db,
            user_id=current_user.id,
            material_id=material_id,
            title=request.title,
            expected_source_type="official",
        )
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    return _to_response(material)


@admin_router.delete(
    "/{material_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_official_material(
    material_id: str,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        delete_owned_course_material(
            db=db,
            user_id=current_user.id,
            material_id=material_id,
            expected_source_type="official",
        )
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
