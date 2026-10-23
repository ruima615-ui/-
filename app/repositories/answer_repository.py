from sqlalchemy import select

from sqlalchemy.orm import Session

from app.models.entities import (
    AnswerAttempt,#作答
    Enrollment, #选课
    Question,#题目
    WrongQuestion,#错题
)

#从question表中找到这道题目
def get_question(db: Session, question_id: str):
    return db.get(Question, question_id)

#确认学生是否选择了这个课程
def is_enrolled(db: Session, student_id: str, course_id: str) -> bool:
    return db.get(Enrollment, (student_id, course_id)) is not None

#保存一条作答记录
def save_answer_result(
    db: Session,
    student_id: str,
    question: Question,
    answer: dict,
    grade: dict,
) -> AnswerAttempt:
    """在一次事务中保存作答结果；答错时同步保存错题"""

    attempt = AnswerAttempt(
        student_id=student_id,
        question_id=question.id,
        answer=answer,
        grading_status=grade["grading_status"],
        is_correct=grade["is_correct"],
        score=grade["score"],
    )

    try:
        db.add(attempt)

        # 简答题尚未评分，不生成错题；客观题答对也不生成
        if grade["grading_status"] == "graded" and grade["is_correct"] is False:
            existing = db.scalar(
                select(WrongQuestion).where(
                    WrongQuestion.student_id == student_id,
                    WrongQuestion.course_id == question.course_id,
                    WrongQuestion.question_id == question.id,
                )
            )

            mistake = (
                f"学生答案：{answer}；"
                f"正确答案：{question.answer_key}"
            )

            if existing is None:
                db.add(WrongQuestion(
                    student_id=student_id,
                    course_id=question.course_id,
                    question_id=question.id,
                    topic=question.topic,
                    mistake=mistake,
                ))
            else:
                # 重复答错同一题，更新错误描述，避免无限增加相同错题
                existing.mistake = mistake

        db.commit()
        db.refresh(attempt)
        return attempt

    except Exception:
        db.rollback()
        raise