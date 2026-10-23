#从数据库中取出该课程的项目
from sqlalchemy import select

from app.models.entities import Question


def get_course_questions(db, course_id: str):
    """从数据库读取一门课程的题目"""

    statement = (
        select(Question)
        .where(Question.course_id == course_id)
        .order_by(Question.id)
    )

    return db.scalars(statement).all()
def add_question(
    db,
    question: Question,
) -> Question:
    """把新题目加入当前数据库事务。"""

    db.add(question)
    db.flush()

    return question