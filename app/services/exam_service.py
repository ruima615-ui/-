from math import isfinite
from uuid import uuid4
from sqlalchemy import select

from app.models.entities import Exam, ExamQuestion, Question
from app.repositories.exam_repository import (
    add_exam_draft,
    get_exam_question_rows,
    get_questions_by_ids,
)
from app.services.teacher_service import require_teacher_course_access


def list_teacher_exams(db, teacher_id: str, course_id: str) -> list[dict]:
    """列出当前教师在授权课程中创建的试卷。"""
    require_teacher_course_access(db, teacher_id, course_id)
    exams = db.scalars(select(Exam).where(
        Exam.course_id == course_id, Exam.created_by == teacher_id,
    ).order_by(Exam.created_at.desc(), Exam.id.desc())).all()
    return [{"exam_id": exam.id, "course_id": exam.course_id,
             "title": exam.title, "status": exam.status,
             "duration_minutes": exam.duration_minutes,
             "created_at": exam.created_at.isoformat() if exam.created_at else None}
            for exam in exams]


def get_teacher_exam_detail(db, teacher_id: str, exam_id: str) -> dict:
    """从数据库重建草稿或已发布试卷的完整教师预览。"""
    exam = db.get(Exam, exam_id)
    if exam is None:
        raise ValueError("试卷不存在")
    require_teacher_course_access(db, teacher_id, exam.course_id)
    if exam.created_by != teacher_id:
        raise PermissionError("只能查看自己创建的试卷")
    questions = []
    for row in get_exam_question_rows(db, exam_id):
        question = db.get(Question, row.question_id)
        questions.append({
            "question_id": row.question_id, "position": row.position,
            "points": row.points, "topic": question.topic,
            "question_type": question.question_type, "stem": question.stem,
            "options": question.options, "answer_key": question.answer_key,
            "explanation": question.explanation,
        })
    return {"exam_id": exam.id, "course_id": exam.course_id,
            "title": exam.title, "status": exam.status,
            "duration_minutes": exam.duration_minutes,
            "questions": questions,
            "total_points": round(sum(item["points"] for item in questions), 2)}

def create_exam_draft(
    db,
    teacher_id: str,
    course_id: str,
    title: str,
    duration_minutes: int,
    items: list[dict],
) -> dict:
    """从课程题库选题，创建草稿试卷"""

    require_teacher_course_access(
        db=db,
        teacher_id=teacher_id,
        course_id=course_id,
    )

    if not isinstance(title, str) or not title.strip():
        raise ValueError("试卷标题不能为空")

    if type(duration_minutes) is not int or duration_minutes <= 0:
        raise ValueError("考试时长必须是正整数")

    if not isinstance(items, list) or not items:
        raise ValueError("试卷至少需要一道题目")

    question_ids = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("每道试卷题目必须是一个字典")

        question_id = item.get("question_id")
        points = item.get("points")

        if not isinstance(question_id, str) or not question_id:
            raise ValueError("题目编号不能为空")

        if (
            type(points) not in (int, float)
            or not isfinite(points)
            or points <= 0
        ):
            raise ValueError(f"题目{question_id}的分值必须大于0")

        question_ids.append(question_id)

    if len(question_ids) != len(set(question_ids)):
        raise ValueError("同一张试卷中不能重复选择同一道题")

    questions = get_questions_by_ids(db, question_ids)
    question_map = {question.id: question for question in questions}

    for question_id in question_ids:
        question = question_map.get(question_id)

        if question is None:
            raise ValueError(f"题目不存在：{question_id}")

        if question.course_id != course_id:
            raise ValueError(
                f"题目{question_id}不属于课程{course_id}"
            )

    exam_id = f"EXAM_{uuid4().hex}"

    exam = Exam(
        id=exam_id,
        course_id=course_id,
        created_by=teacher_id,
        title=title.strip(),
        duration_minutes=duration_minutes,
        status="draft",
    )

    question_rows = [
        ExamQuestion(
            exam_id=exam_id,
            question_id=item["question_id"],
            position=index,
            points=float(item["points"]),
        )
        for index, item in enumerate(items, start=1)
    ]

    try:
        add_exam_draft(db, exam, question_rows)
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "exam_id": exam_id,
        "course_id": course_id,
        "created_by": teacher_id,
        "title": exam.title,
        "status": "draft",
        "question_count": len(question_rows),
        "total_points": round(
            sum(row.points for row in question_rows), 2
        ),
    }

#检查草稿试卷并发布
def publish_exam(db, teacher_id: str, exam_id: str) -> dict:
    """检查草稿试卷并发布"""

    exam = db.get(Exam, exam_id)
    if exam is None:
        raise ValueError(f"试卷不存在：{exam_id}")

    if exam.status != "draft":
        raise ValueError("只有草稿试卷可以发布")

    require_teacher_course_access(
        db=db,
        teacher_id=teacher_id,
        course_id=exam.course_id,
    )
    if exam.created_by is not None and exam.created_by != teacher_id:
        raise PermissionError("只能发布自己创建的试卷")

    rows = get_exam_question_rows(db, exam_id)
    if not rows:
        raise ValueError("试卷没有题目，不能发布")

    for row in rows:
        question = db.get(Question, row.question_id)

        if question is None:
            raise ValueError(f"题目不存在：{row.question_id}")

        if question.course_id != exam.course_id:
            raise ValueError(
                f"题目{row.question_id}不属于试卷所在课程"
            )

        if row.points <= 0:
            raise ValueError(f"题目{row.question_id}的分值无效")

        if question.answer_key is None:
            raise ValueError(f"题目{row.question_id}缺少标准答案或参考答案")

    try:
        for row in get_exam_question_rows(db, exam.id):
            question = db.get(Question, row.question_id)

            if question.question_type == "single_choice":
                valid_key = isinstance(question.answer_key, str)

            elif question.question_type == "multiple_choice":
                valid_key = (
                    isinstance(question.answer_key, list)
                    and len(question.answer_key) > 0
                    and all(isinstance(item, str) for item in question.answer_key)
                    and len(question.answer_key) == len(set(question.answer_key))
                )

            elif question.question_type == "true_false":
                valid_key = type(question.answer_key) is bool

            elif question.question_type == "fill_blank":
                key = question.answer_key
                valid_key = (
                    isinstance(key, str) and bool(key.strip())
                    or isinstance(key, list) and bool(key)
                    and all(isinstance(value, str) and value.strip() for value in key)
                    and len(key) == len(set(key))
                )

            elif question.question_type == "short_answer":
                valid_key = isinstance(question.answer_key, str) and bool(question.answer_key.strip())

            else:
                raise ValueError(f"暂不支持的题型：{question.question_type}")

            if not valid_key:
                raise ValueError(f"题目 {question.id} 的标准答案格式不正确")
        exam.status = "published"#试卷发布前进行校验
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {
        "exam_id": exam.id,
        "status": exam.status,
        "question_count": len(rows),
        "total_points": round(
            sum(row.points for row in rows), 2
        ),
    }
