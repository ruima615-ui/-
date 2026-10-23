from sqlalchemy import select

from app.models.entities import Exam, ExamQuestion, Question


def get_questions_by_ids(db, question_ids: list[str]):
    """批量读取组卷选中的题目"""

    statement = select(Question).where(Question.id.in_(question_ids))
    return db.scalars(statement).all()


def add_exam_draft(db, exam: Exam, question_rows: list[ExamQuestion]):
    """把试卷和试卷题目加入同一次数据库事务"""

    db.add(exam)
    db.flush()  # 先把试卷写入当前事务，供试卷题目引用

    db.add_all(question_rows)
def get_exam_question_rows(db, exam_id: str):
    """查询一张试卷选了哪些题目，并按试卷上的顺序排列"""

    statement = (
        select(ExamQuestion)
        .where(ExamQuestion.exam_id == exam_id)
        .order_by(ExamQuestion.position)
    )

    return db.scalars(statement).all()