"""会话管理接口，真正接受HTTP并请求创建会话"""
import json
from uuid import uuid4

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.exam_dependencies import get_current_user
from app.api.exam_dependencies import get_db
from app.models.entities import Course
from app.models.entities import Enrollment
from app.models.entities import ChatMessage, ReviewTaskProgress
from app.repositories.conversation_repository import (
    close_chat_session,
    get_chat_session,
    get_recent_chat_messages,
    get_user_chat_sessions,
)
from app.schemas.message import (
    MessageResponse,
    SessionMessagesResponse,
)
from app.schemas.session import (
    CreateSessionRequest,
    SessionResponse,
)
from app.services.memory_service import create_memory_session
from app.services.wrong_question_service import get_course_wrong_question_details
router=APIRouter(
    tags=["会话"]
)


def _load_message_metadata(metadata_json: str | None) -> dict:
    if not metadata_json:
        return {}
    try:
        metadata = json.loads(metadata_json)
    except (json.JSONDecodeError, TypeError):
        return {}
    return metadata if isinstance(metadata, dict) else {}


class CompleteReviewTaskRequest(BaseModel):
    answers: list[str] = Field(min_length=1, max_length=10)


def _owned_plan(db, session_id: str, user_id: str, message_id: int):
    session = get_chat_session(db=db, session_id=session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权访问这段会话")
    message = db.get(ChatMessage, message_id)
    if message is None or message.session_id != session_id or message.role != "assistant":
        raise HTTPException(status_code=404, detail="复习计划不存在")
    plan = _load_message_metadata(message.metadata_json).get("review_plan")
    if not isinstance(plan, dict) or plan.get("scope", {}).get("course_id") != session.course_id:
        raise HTTPException(status_code=404, detail="复习计划不存在")
    return session, plan


@router.get("/sessions/{session_id}/review-task-progress")
def list_review_task_progress(session_id: str, db=Depends(get_db),
                              current_user=Depends(get_current_user)):
    session = get_chat_session(db=db, session_id=session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权查看任务进度")
    rows = db.scalars(select(ReviewTaskProgress).where(
        ReviewTaskProgress.session_id == session_id,
        ReviewTaskProgress.student_id == current_user.id,
        ReviewTaskProgress.course_id == session.course_id,
    )).all()
    return [{"message_id": row.message_id, "task_id": row.task_id,
             "answers": row.self_check_answers, "completed_at": row.completed_at}
            for row in rows]


@router.post("/sessions/{session_id}/review-tasks/{message_id}/{task_id}/complete")
def complete_review_task(session_id: str, message_id: int, task_id: str,
                         request: CompleteReviewTaskRequest, db=Depends(get_db),
                         current_user=Depends(get_current_user)):
    session, plan = _owned_plan(db, session_id, current_user.id, message_id)
    if session.status != "active":
        raise HTTPException(status_code=409, detail="会话已结束")
    task = next((item for item in plan.get("review_tasks", [])
                 if isinstance(item, dict) and item.get("task_id") == task_id), None)
    if task is None:
        raise HTTPException(status_code=404, detail="复习任务不存在")
    questions = task.get("self_check_questions") or []
    answers = [answer.strip() for answer in request.answers]
    if len(answers) != len(questions) or not all(answers):
        raise HTTPException(status_code=422, detail="请逐题填写自测回答")
    row = db.get(ReviewTaskProgress, (session_id, message_id, task_id))
    if row is None:
        row = ReviewTaskProgress(session_id=session_id, message_id=message_id,
                                 task_id=task_id, student_id=current_user.id,
                                 course_id=session.course_id,
                                 self_check_answers=answers)
        db.add(row)
    else:
        row.self_check_answers = answers
    db.commit()
    db.refresh(row)
    return {"message_id": message_id, "task_id": task_id,
            "answers": row.self_check_answers, "completed_at": row.completed_at}


@router.get("/sessions/{session_id}/plans/{message_id}/wrong-questions/{question_id}")
def plan_wrong_question(session_id: str, message_id: int, question_id: str,
                        db=Depends(get_db), current_user=Depends(get_current_user)):
    session, plan = _owned_plan(db, session_id, current_user.id, message_id)
    if question_id not in {item.get("question_id") for item in plan.get("wrong_question_evidence", [])}:
        raise HTTPException(status_code=404, detail="该题不属于这份复习计划")
    details = get_course_wrong_question_details(db=db, student_id=current_user.id,
                                                course_id=session.course_id)
    question = next((item for item in details.get("wrong_questions", [])
                     if item.get("question_id") == question_id), None)
    if question is None:
        raise HTTPException(status_code=404, detail="当前错题证据不可用")
    return question


@router.get("/sessions/{session_id}/plans/{message_id}/materials/{chunk_id}")
def plan_material_chunk(session_id: str, message_id: int, chunk_id: str,
                        db=Depends(get_db), current_user=Depends(get_current_user)):
    session, plan = _owned_plan(db, session_id, current_user.id, message_id)
    item = next((item for item in plan.get("material_evidence", [])
                 if item.get("chunk_id") == chunk_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="该片段不属于这份复习计划")
    from rag_tools import get_course_material_chunk
    result = get_course_material_chunk(course_id=session.course_id, chunk_id=chunk_id,
                                       topic=item.get("topic"))
    if result.get("status") != "success":
        raise HTTPException(status_code=404, detail="当前课程资料片段不可用")
    return result

@router.post(
    "/sessions",
    response_model=SessionResponse,
    status_code=201
)
def create_session(
    request: CreateSessionRequest,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """为当前登录学生创建课程 Agent 会话。"""

    # get_current_user 已经检查用户存在且状态为 active。
    if current_user.role != "student":
        raise HTTPException(
            status_code=403,
            detail="只有学生可以创建学习会话",
        )

    # 学生 Agent 会话必须关联一门有效课程。
    course = db.get(
        Course,
        request.course_id,
    )

    if course is None:
        raise HTTPException(
            status_code=404,
            detail=f"课程不存在：{request.course_id}",
        )

    if course.status != "active":
        raise HTTPException(
            status_code=403,
            detail="当前课程不可用",
        )

    # 当前学生必须已经选修该课程。
    enrollment = db.get(
        Enrollment,
        (
            current_user.id,
            request.course_id,
        ),
    )

    if enrollment is None:
        raise HTTPException(
            status_code=403,
            detail="当前学生未选修这门课程",
        )

    # 会话编号必须由后端生成。
    session_id = f"SESSION_{uuid4().hex}"

    session = create_memory_session(
        db=db,
        session_id=session_id,
        user_id=current_user.id,
        course_id=request.course_id,
        title=request.title,
    )

    return SessionResponse(
        session_id=session.id,
        user_id=session.user_id,
        course_id=session.course_id,
        title=session.title,
        status=session.status,
        created_at=session.created_at,
    )
@router.get(
    "/sessions",
    response_model=list[SessionResponse],
)
def list_user_sessions(
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """查询当前登录用户自己的会话。"""

    sessions = get_user_chat_sessions(
        db=db,
        user_id=current_user.id,
    )

    return [
        SessionResponse(
            session_id=session.id,
            user_id=session.user_id,
            course_id=session.course_id,
            title=session.title,
            status=session.status,
            created_at=session.created_at,
        )
        for session in sessions
    ]
@router.get(
    "/sessions/{session_id}/messages",
    response_model=SessionMessagesResponse,
)
def list_session_messages(
    session_id: str,
    limit: int = Query(
        default=20,
        ge=1,
        le=100,
    ),
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """查询当前登录用户某段会话的历史消息。"""

    session = get_chat_session(
        db=db,
        session_id=session_id,
    )

    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"会话不存在：{session_id}",
        )

    if session.user_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="当前用户无权查看这段会话",
        )

    database_messages = get_recent_chat_messages(
        db=db,
        session_id=session_id,
        limit=limit,
    )

    response_messages = []
    for message in database_messages:
        metadata = _load_message_metadata(
            message.metadata_json
        )
        response_messages.append(MessageResponse(
            message_id=message.id,
            session_id=message.session_id,
            role=message.role,
            content=message.content,
            called_tools=metadata.get(
                "called_tools",
                [],
            ),
            steps=metadata.get("steps"),
            review_plan=metadata.get("review_plan"),
            created_at=message.created_at,
        ))

    return SessionMessagesResponse(
        session_id=session_id,
        count=len(response_messages),
        messages=response_messages,
    )
#添加关闭会话接口
@router.patch(
    "/sessions/{session_id}/close",
    response_model=SessionResponse
)
def close_session(
    session_id: str,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """关闭当前登录用户自己的会话"""

    session = get_chat_session(
        db=db,
        session_id=session_id,
    )
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"会话不存在：{session_id}",
        )

    if session.user_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="当前用户无权关闭这段会话",
        )

    if session.status != "closed":
        session = close_chat_session(
            db=db,
            session_id=session_id,
        )

    return SessionResponse(
        session_id=session.id,
        user_id=session.user_id,
        course_id=session.course_id,
        title=session.title,
        status=session.status,
        created_at=session.created_at,
    )
