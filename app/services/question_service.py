"""教师题库：按课程授权读取，批量校验后一次事务导入。"""

from uuid import uuid4
from math import isfinite

from sqlalchemy.orm import Session

from app.models.entities import Question
from app.repositories.question_repository import get_course_questions
from app.schemas.question import CreateQuestionRequest
from app.services.question_difficulty_service import calculate_question_difficulty
from app.services.teacher_service import require_teacher_course_access


def _validate_answer(item: CreateQuestionRequest) -> None:
    options = item.options
    key = item.answer_key
    if item.question_type in ("single_choice", "multiple_choice"):
        if not options or len(options) < 2 or any(
            not isinstance(label, str) or not label.strip()
            or not isinstance(value, str) or not value.strip()
            for label, value in options.items()
        ):
            raise ValueError("选择题至少需要两个非空选项")
        if item.question_type == "single_choice":
            valid = isinstance(key, str) and key in options
        else:
            valid = (
                isinstance(key, list) and bool(key)
                and all(isinstance(label, str) and label in options for label in key)
                and len(key) == len(set(key))
            )
        if not valid:
            raise ValueError("标准答案必须引用已有选项且不能重复")
    elif item.question_type == "true_false":
        if type(key) is not bool:
            raise ValueError("判断题标准答案必须是 true 或 false")
    elif item.question_type == "fill_blank":
        if not (
            isinstance(key, str) and key.strip()
            or isinstance(key, list) and bool(key)
            and all(isinstance(value, str) and value.strip() for value in key)
            and len(key) == len(set(key))
        ):
            raise ValueError("填空题标准答案须为非空字符串或不重复的可接受答案列表")
    elif item.question_type == "short_answer":
        if not isinstance(key, str) or not key.strip():
            raise ValueError("简答题需要非空的参考答案供教师批改")


def list_teacher_questions(db: Session, teacher_id: str, course_id: str) -> list[dict]:
    require_teacher_course_access(db, teacher_id, course_id)
    return [
        {
            "question_id": question.id,
            "course_id": question.course_id,
            "question_type": question.question_type,
            "topic": question.topic,
            "stem": question.stem,
            "difficulty": question.difficulty,
            "options": question.options,
            "answer_key": question.answer_key,
            "explanation": question.explanation,
            "max_score": question.max_score,
        }
        for question in get_course_questions(db, course_id)
    ]


def import_teacher_questions(
    db: Session, teacher_id: str, course_id: str,
    items: list[CreateQuestionRequest],
) -> dict:
    require_teacher_course_access(db, teacher_id, course_id)
    if not items or len(items) > 200:
        raise ValueError("每次须导入 1 至 200 道题")
    questions = []
    for index, item in enumerate(items, start=1):
        try:
            if item.course_id != course_id:
                raise ValueError("题目所属课程与当前课程不一致")
            if not item.topic.strip() or not item.stem.strip():
                raise ValueError("知识点和题干不能为空")
            if not isfinite(item.max_score):
                raise ValueError("题目分值必须是有限数值")
            _validate_answer(item)
            difficulty = calculate_question_difficulty(
                knowledge_count_level=item.knowledge_count_level,
                reasoning_level=item.reasoning_level,
                transfer_level=item.transfer_level,
                distractor_level=item.distractor_level,
            )
            questions.append(Question(
                id=f"Q_{uuid4().hex}",
                course_id=course_id,
                question_type=item.question_type,
                topic=item.topic.strip(),
                stem=item.stem.strip(),
                options=item.options,
                answer_key=item.answer_key,
                explanation=item.explanation,
                max_score=item.max_score,
                **difficulty,
                knowledge_count_level=item.knowledge_count_level,
                reasoning_level=item.reasoning_level,
                transfer_level=item.transfer_level,
                distractor_level=item.distractor_level,
            ))
        except ValueError as error:
            raise ValueError(f"第 {index} 道题：{error}") from error
    try:
        db.add_all(questions)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"course_id": course_id, "count": len(questions),
            "question_ids": [question.id for question in questions]}
