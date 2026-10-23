from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from app.api.exam_dependencies import get_current_user, get_db
from app.services.exam_attempt_service import (
    get_exam_paper,
    get_exam_result,
    start_exam,
    submit_exam,
    list_available_exams,
    list_pending_reviews,
    get_review_detail,
    grade_short_answers,
    list_student_attempts,
)
from app.services.exam_service import (
    create_exam_draft, publish_exam, list_teacher_exams, get_teacher_exam_detail,
)


router = APIRouter(prefix="/api/exams", tags=["exams"])


class ExamItem(BaseModel):
    question_id: str
    points: float = Field(gt=0)


class CreateExamRequest(BaseModel):
    course_id: str
    title: str = Field(min_length=1)
    duration_minutes: int = Field(gt=0)
    items: list[ExamItem] = Field(min_length=1)


class SubmittedAnswer(BaseModel):
    question_id: str
    answer: Any


class SubmitExamRequest(BaseModel):
    answers: list[SubmittedAnswer]


class ShortAnswerGrade(BaseModel):
    question_id: str
    score: float = Field(ge=0, allow_inf_nan=False)


class GradeShortAnswersRequest(BaseModel):
    grades: list[ShortAnswerGrade] = Field(min_length=1)

class AvailableExamResponse(BaseModel):
    exam_id: str
    course_id: str
    course_name: str
    title: str
    duration_minutes: int
    status: str

def require_role(user, role):
    if user.role != role:
        raise HTTPException(status_code=403, detail=f"仅限{role}使用")


@router.get("/review/pending")
def pending_reviews(course_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    require_role(user, "teacher")
    return call_service(list_pending_reviews, db=db, teacher_id=user.id, course_id=course_id)


@router.get("/review/{attempt_id}")
def review_detail(attempt_id: int, db=Depends(get_db), user=Depends(get_current_user)):
    require_role(user, "teacher")
    return call_service(get_review_detail, db=db, teacher_id=user.id, attempt_id=attempt_id)


@router.post("/review/{attempt_id}/grades")
def review_grades(attempt_id: int, body: GradeShortAnswersRequest,
                  db=Depends(get_db), user=Depends(get_current_user)):
    require_role(user, "teacher")
    return call_service(grade_short_answers, db=db, teacher_id=user.id,
                        attempt_id=attempt_id,
                        grades=[item.model_dump() for item in body.grades])


def call_service(function, **kwargs):
    """把业务层已明确的错误转换成 HTTP 响应。"""
    try:
        return function(**kwargs)
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.get("/attempts/mine")
def my_attempts(db=Depends(get_db), user=Depends(get_current_user)):
    require_role(user, "student")
    return list_student_attempts(db=db, student_id=user.id)


@router.post("/drafts")
def create_draft(
    body: CreateExamRequest,
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    require_role(user, "teacher")
    return call_service(
        create_exam_draft,
        db=db,
        teacher_id=user.id,
        course_id=body.course_id,
        title=body.title,
        duration_minutes=body.duration_minutes,
        items=[item.model_dump() for item in body.items],
    )


@router.get("/teacher")
def teacher_exams(course_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    require_role(user, "teacher")
    return call_service(list_teacher_exams, db=db, teacher_id=user.id, course_id=course_id)


@router.get("/teacher/{exam_id}")
def teacher_exam_detail(exam_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    require_role(user, "teacher")
    return call_service(get_teacher_exam_detail, db=db, teacher_id=user.id, exam_id=exam_id)


@router.post("/{exam_id}/publish")
def publish(
    exam_id: str,
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    require_role(user, "teacher")
    call_service(
        publish_exam,
        db=db,
        teacher_id=user.id,
        exam_id=exam_id,
    )
    return {"exam_id": exam_id, "status": "published"}

@router.get(
    "/available",
    response_model=list[AvailableExamResponse],
)
def available_exams(
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    """查询当前学生可以参加的考试。"""

    require_role(user, "student")

    return call_service(
        list_available_exams,
        db=db,
        student_id=user.id,
    )

@router.post("/{exam_id}/attempts")
def start(
    exam_id: str,
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    require_role(user, "student")
    return call_service(
        start_exam,
        db=db,
        student_id=user.id,
        exam_id=exam_id,
    )


@router.get("/attempts/{attempt_id}/paper")
def paper(
    attempt_id: int,
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    require_role(user, "student")
    return call_service(
        get_exam_paper,
        db=db,
        student_id=user.id,
        attempt_id=attempt_id,
    )


@router.post("/attempts/{attempt_id}/submit")
def submit(
    attempt_id: int,
    body: SubmitExamRequest,
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    require_role(user, "student")
    return call_service(
        submit_exam,
        db=db,
        student_id=user.id,
        attempt_id=attempt_id,
        answers=[item.model_dump() for item in body.answers],
    )


@router.get("/attempts/{attempt_id}/result")
def result(
    attempt_id: int,
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    require_role(user, "student")
    return call_service(
        get_exam_result,
        db=db,
        student_id=user.id,
        attempt_id=attempt_id,
    )
