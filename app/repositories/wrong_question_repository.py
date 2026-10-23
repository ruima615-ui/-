#从wrong_question表中获取错题
from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app.models.entities import (
    Exam,
    ExamAnswer,
    ExamAttempt,
    Question,
    WrongQuestion,
)
def get_student_wrong_questions(
    db: Session,
    student_id: str,
    course_id: str,
) -> list[WrongQuestion]:
    """读取学生在当前课程中的具体错题记录。"""

    statement = (
        select(WrongQuestion)
        .where(
            and_(
                WrongQuestion.student_id == student_id,
                WrongQuestion.course_id == course_id,
            )
        )
        .order_by(
            WrongQuestion.id
        )
    )

    return list(
        db.scalars(statement).all()
    )
def get_course_question(
    db: Session,
    course_id: str,
    question_id: str,
) -> Question | None:
    """读取当前课程中的指定题目。"""

    statement = (
        select(Question)
        .where(
            Question.id == question_id,
            Question.course_id == course_id,
        )
    )

    return db.scalar(statement)


def get_latest_wrong_exam_answer(
    db: Session,
    student_id: str,
    course_id: str,
    question_id: str,
) -> ExamAnswer | None:
    """读取学生在当前课程中对指定题目的最近一次错误作答。"""

    statement = (
        select(ExamAnswer)
        .join(
            ExamAttempt,
            ExamAttempt.id
            == ExamAnswer.exam_attempt_id,
        )
        .join(
            Exam,
            Exam.id == ExamAttempt.exam_id,
        )
        .where(
            ExamAttempt.student_id == student_id,
            ExamAttempt.status == "graded",
            Exam.course_id == course_id,
            ExamAnswer.question_id == question_id,
            ExamAnswer.grading_status == "graded",
            ExamAnswer.is_correct.is_(False),
        )
        .order_by(
            ExamAttempt.submitted_at.desc(),
            ExamAnswer.id.desc(),
        )
    )

    return db.scalars(statement).first()
def get_student_topic_wrong_stats(
    db: Session,
    student_id: str,
    course_id: str,
) -> list[dict]:
    """按知识点统计全部考试作答和错误作答。"""

    wrong_condition = (
        ExamAnswer.is_correct.is_(False)
    )

    unique_wrong_questions = func.count(
        func.distinct(
            case(
                (
                    wrong_condition,
                    ExamAnswer.question_id,
                ),
                else_=None,
            )
        )
    ).label("unique_wrong_questions")

    wrong_attempts = func.sum(
        case(
            (wrong_condition, 1),
            else_=0,
        )
    ).label("wrong_attempts")

    total_attempts = func.count(
        ExamAnswer.id
    ).label("total_attempts")

    last_wrong_at = func.max(
        case(
            (
                wrong_condition,
                ExamAttempt.submitted_at,
            ),
            else_=None,
        )
    ).label("last_wrong_at")
    easy_wrong_attempts = func.sum(
    case(
        (
            and_(
                wrong_condition,
                Question.difficulty == "easy",
            ),
            1,
        ),
        else_=0,
    )
).label("easy_wrong_attempts")

    medium_wrong_attempts = func.sum(
    case(
        (
            and_(
                wrong_condition,
                Question.difficulty == "medium",
            ),
            1,
        ),
        else_=0,
    )
).label("medium_wrong_attempts")

    hard_wrong_attempts = func.sum(
    case(
        (
            and_(
                wrong_condition,
                Question.difficulty == "hard",
            ),
            1,
        ),
        else_=0,
    )
).label("hard_wrong_attempts")


    statement = (
        select(
            Question.topic.label("topic"),
            unique_wrong_questions,
            wrong_attempts,
            total_attempts,
            last_wrong_at,
            easy_wrong_attempts,
            medium_wrong_attempts,
            hard_wrong_attempts,
        )
        .join(
            ExamAttempt,
            ExamAttempt.id
            == ExamAnswer.exam_attempt_id,
        )
        .join(
            Exam,
            Exam.id == ExamAttempt.exam_id,
        )
        .join(
            Question,
            Question.id
            == ExamAnswer.question_id,
        )
        .where(
            ExamAttempt.student_id == student_id,
            ExamAttempt.status == "graded",
            Exam.course_id == course_id,
            Question.course_id == course_id,
            ExamAnswer.grading_status == "graded",
            ExamAnswer.is_correct.is_not(None),
        )
        .group_by(
            Question.topic,
        )
        .having(
            wrong_attempts > 0,
        )
        .order_by(
            wrong_attempts.desc(),
            unique_wrong_questions.desc(),
            Question.topic,
        )
    )

    rows = db.execute(statement).all()

    return [
    {
        "topic": row.topic,
        "unique_wrong_questions": int(
            row.unique_wrong_questions or 0
        ),
        "wrong_attempts": int(
            row.wrong_attempts or 0
        ),
        "total_attempts": int(
            row.total_attempts or 0
        ),
        "last_wrong_at": row.last_wrong_at,
        "easy_wrong_attempts": int(
            row.easy_wrong_attempts or 0
        ),
        "medium_wrong_attempts": int(
            row.medium_wrong_attempts or 0
        ),
        "hard_wrong_attempts": int(
            row.hard_wrong_attempts or 0
        ),
    }
    for row in rows
]
