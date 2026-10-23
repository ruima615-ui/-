"""教师题库接口。"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.exam_dependencies import get_current_user, get_db
from app.schemas.question import CreateQuestionRequest
from app.services.question_service import import_teacher_questions, list_teacher_questions

router = APIRouter(prefix="/api/teacher/courses", tags=["teacher-questions"])


class BatchQuestionRequest(BaseModel):
    items: list[CreateQuestionRequest] = Field(min_length=1, max_length=200)


def _require_teacher(user):
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="仅限教师使用")


@router.get("/{course_id}/questions")
def course_questions(course_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    _require_teacher(user)
    try:
        return list_teacher_questions(db, user.id, course_id)
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/{course_id}/questions/batch")
def batch_questions(
    course_id: str, body: BatchQuestionRequest,
    db=Depends(get_db), user=Depends(get_current_user),
):
    _require_teacher(user)
    try:
        return import_teacher_questions(db, user.id, course_id, body.items)
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
