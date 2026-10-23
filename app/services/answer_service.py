from sqlalchemy.orm import Session

from app.models.entities import Course, User
from app.repositories.answer_repository import (
    get_question,
    is_enrolled,
    save_answer_result,
)
from app.services.grading_service import grade_answer


def submit_answer(
    db: Session,
    student_id: str,
    question_id: str,
    answer: dict,
) -> dict:
    """检查作答资格、判题、保存结果"""

    student = db.get(User, student_id)
    if student is None or student.role != "student":
        raise ValueError("学生不存在")

    if student.status != "active":
        raise PermissionError("学生账号已停用")

    question = get_question(db, question_id)
    if question is None:
        raise ValueError("题目不存在")

    course = db.get(Course, question.course_id)
    if course is None or course.status != "active":
        raise ValueError("题目所属课程不可用")

    if not is_enrolled(db, student_id, question.course_id):
        raise PermissionError("学生尚未加入题目所属课程")

    grade = grade_answer(
        question_type=question.question_type,
        answer_key=question.answer_key,
        answer=answer,
        max_score=question.max_score,
    )

    attempt = save_answer_result(
        db=db,
        student_id=student_id,
        question=question,
        answer=answer,
        grade=grade,
    )

    return {
        "attempt_id": attempt.id,
        "question_id": question.id,
        "grading_status": attempt.grading_status,
        "is_correct": attempt.is_correct,
        "score": attempt.score,
    }