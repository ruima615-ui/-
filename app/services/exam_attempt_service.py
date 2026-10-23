from datetime import datetime, timedelta, timezone
from math import isfinite
import unicodedata

from sqlalchemy import select

from app.models.entities import (
    Course,
    Enrollment,
    Exam,
    ExamAnswer,
    ExamAttempt,
    Question,
    User,
    WrongQuestion,
)
from app.repositories.exam_repository import get_exam_question_rows
from app.services.teacher_service import require_teacher_course_access

#获取当前时间，判断考试是否超时
def _now():
    """与当前 SQLite 的时间字段保持一致，使用不带时区的 UTC 时间。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)

#读取试卷中的题目
def _question_rows(db, exam_id):
    rows = get_exam_question_rows(db, exam_id)
    if not rows:
        raise ValueError("试卷没有题目")
    return rows


def _grade(question, submitted_answer, points):
    """客观题与单空填空题自动判分；简答题返回待人工批改。"""
    key = question.answer_key

    if question.question_type == "single_choice":
        if not isinstance(submitted_answer, str):
            raise ValueError(f"题目 {question.id} 的答案必须是字符串")
        is_correct = submitted_answer == key

    elif question.question_type == "multiple_choice":
        if (
            not isinstance(submitted_answer, list)
            or not all(isinstance(item, str) for item in submitted_answer)
            or len(submitted_answer) != len(set(submitted_answer))
        ):
            raise ValueError(f"题目 {question.id} 的答案必须是不重复的选项列表")
        is_correct = set(submitted_answer) == set(key)

    elif question.question_type == "true_false":
        if not isinstance(submitted_answer, bool):
            raise ValueError(f"题目 {question.id} 的答案必须是布尔值")
        is_correct = submitted_answer == key

    elif question.question_type == "fill_blank":
        if not isinstance(submitted_answer, str) or not submitted_answer.strip():
            raise ValueError(f"题目 {question.id} 的填空答案必须是非空文本")
        # 只统一全角/半角并去首尾空白；不忽略大小写或内部空格。
        normalized = unicodedata.normalize("NFKC", submitted_answer).strip()
        accepted = key if isinstance(key, list) else [key]
        is_correct = normalized in {
            unicodedata.normalize("NFKC", answer).strip() for answer in accepted
        }

    elif question.question_type == "short_answer":
        if not isinstance(submitted_answer, str) or not submitted_answer.strip():
            raise ValueError(f"题目 {question.id} 的简答答案必须是非空文本")
        return None, None

    else:
        raise ValueError(f"题目 {question.id} 暂不支持自动判分")

    return is_correct, float(points) if is_correct else 0.0


def start_exam(db, student_id, exam_id):
    """检查学生资格，创建一次考试记录。"""
    student = db.get(User, student_id)
    exam = db.get(Exam, exam_id)

    if student is None or student.role != "student" or student.status != "active":
        raise ValueError("学生不存在或账号不可用")
    if exam is None or exam.status != "published":
        raise ValueError("考试不存在或尚未发布")

    course = db.get(Course, exam.course_id)
    if course is None or course.status != "active":
        raise ValueError("课程不可用")

    enrollment = db.get(Enrollment, (student_id, exam.course_id))
    if enrollment is None:
        raise PermissionError("学生未选修这门课程")

    _question_rows(db, exam_id)

    existing = db.scalar(
        select(ExamAttempt).where(
            ExamAttempt.exam_id == exam_id,
            ExamAttempt.student_id == student_id,
        )
    )
    if existing is not None:
        if existing.status == "in_progress":
            return {"attempt_id": existing.id, "status": existing.status}
        raise ValueError("这场考试已经提交，不能再次开考")

    try:
        attempt = ExamAttempt(
            exam_id=exam_id,
            student_id=student_id,
            status="in_progress",
        )
        db.add(attempt)
        db.commit()
        db.refresh(attempt)
        return {"attempt_id": attempt.id, "status": attempt.status}
    except Exception:
        db.rollback()
        raise


def get_exam_paper(db, student_id, attempt_id):
    """返回本次试卷；绝不返回标准答案和解析。"""
    attempt = db.get(ExamAttempt, attempt_id)
    if attempt is None or attempt.student_id != student_id:
        raise PermissionError("无权查看这次考试")
    if attempt.status != "in_progress":
        raise ValueError("这次考试已经结束")

    exam = db.get(Exam, attempt.exam_id)
    deadline = attempt.started_at + timedelta(minutes=exam.duration_minutes)
    if _now() > deadline:
        raise ValueError("考试已超时，请提交试卷以确认结果")

    paper = []
    for row in _question_rows(db, exam.id):
        question = db.get(Question, row.question_id)
        paper.append({
            "question_id": question.id,
            "position": row.position,
            "question_type": question.question_type,
            "stem": question.stem,
            "options": question.options,
            "points": row.points,
        })

    return {
        "attempt_id": attempt.id,
        "exam_title": exam.title,
        "deadline": deadline.isoformat(),
        "questions": paper,
    }


def get_exam_result(db, student_id, attempt_id):
    """只能查看自己的已判分结果。"""
    attempt = db.get(ExamAttempt, attempt_id)
    if attempt is None or attempt.student_id != student_id:
        raise PermissionError("无权查看这次考试")
    if attempt.status == "pending_review":
        return {"attempt_id": attempt.id, "status": "pending_review",
                "message": "简答题待教师批改，最终成绩尚未生成"}
    if attempt.status != "graded":
        raise ValueError("考试尚未完成判分")

    rows = _question_rows(db, attempt.exam_id)
    answers = db.scalars(
        select(ExamAnswer).where(ExamAnswer.exam_attempt_id == attempt.id)
    ).all()
    question_rows = {row.question_id: row for row in rows}
    questions = {item.question_id: db.get(Question, item.question_id) for item in answers}

    return {
        "attempt_id": attempt.id,
        "status": attempt.status,
        "total_score": attempt.total_score,
        "full_score": sum(float(row.points) for row in rows),
        "answers": [
            {
                "question_id": item.question_id,
                "stem": questions[item.question_id].stem,
                "topic": questions[item.question_id].topic,
                "question_type": questions[item.question_id].question_type,
                "options": questions[item.question_id].options,
                "correct_answer": questions[item.question_id].answer_key,
                "explanation": questions[item.question_id].explanation,
                "points": question_rows[item.question_id].points,
                "answer": item.answer,
                "is_correct": item.is_correct,
                "score": item.score,
            }
            for item in answers
        ],
    }


def list_student_attempts(db, student_id):
    """仅列出当前学生的考试记录，供续考和成绩入口使用。"""
    rows = db.execute(
        select(ExamAttempt, Exam, Course)
        .join(Exam, Exam.id == ExamAttempt.exam_id)
        .join(Course, Course.id == Exam.course_id)
        .where(ExamAttempt.student_id == student_id)
        .order_by(ExamAttempt.started_at.desc(), ExamAttempt.id.desc())
    ).all()
    return [
        {
            "attempt_id": attempt.id,
            "exam_id": exam.id,
            "exam_title": exam.title,
            "course_id": course.id,
            "course_name": course.name,
            "status": attempt.status,
            "total_score": attempt.total_score,
            "started_at": attempt.started_at.isoformat(),
            "deadline": (attempt.started_at + timedelta(minutes=exam.duration_minutes)).isoformat(),
        }
        for attempt, exam, course in rows
    ]


def submit_exam(db, student_id, attempt_id, answers):
    """
    整卷提交。

    answers 示例：
    [
        {"question_id": "Q001", "answer": "A"},
        {"question_id": "Q002", "answer": ["A", "C"]},
        {"question_id": "Q003", "answer": True},
    ]
    """
    attempt = db.get(ExamAttempt, attempt_id)
    if attempt is None or attempt.student_id != student_id:
        raise PermissionError("无权提交这次考试")

    # 网络重试时，不重复插入答题记录。
    if attempt.status in ("graded", "pending_review"):
        return get_exam_result(db, student_id, attempt_id)
    if attempt.status != "in_progress":
        raise ValueError("当前考试状态不允许提交")

    exam = db.get(Exam, attempt.exam_id)
    rows = _question_rows(db, exam.id)
    question_ids = {row.question_id for row in rows}
    now = _now()
    deadline = attempt.started_at + timedelta(minutes=exam.duration_minutes)
    timed_out = now > deadline

    try:
        if timed_out:
            # 超时计零分，仍保存逐题的未作答记录。
            for row in rows:
                db.add(ExamAnswer(
                    exam_attempt_id=attempt.id,
                    question_id=row.question_id,
                    answer={},
                    grading_status="graded",
                    is_correct=False,
                    score=0.0,
                ))
            attempt.total_score = 0.0

        else:
            if not isinstance(answers, list):
                raise ValueError("answers 必须是列表")

            submitted = {}
            for item in answers:
                if not isinstance(item, dict) or "question_id" not in item or "answer" not in item:
                    raise ValueError("每条答案必须包含 question_id 和 answer")
                question_id = item["question_id"]
                if question_id in submitted:
                    raise ValueError(f"重复提交题目：{question_id}")
                submitted[question_id] = item["answer"]

            if set(submitted) != question_ids:
                raise ValueError("提交的题目必须与当前试卷完全一致")

            total_score = 0.0
            has_pending = False
            for row in rows:
                question = db.get(Question, row.question_id)
                student_answer = submitted[row.question_id]
                is_correct, score = _grade(
                    question, student_answer, row.points
                )

                db.add(ExamAnswer(
                    exam_attempt_id=attempt.id,
                    question_id=question.id,
                    answer=student_answer,
                    grading_status="pending" if is_correct is None else "graded",
                    is_correct=is_correct,
                    score=score,
                ))
                if score is None:
                    has_pending = True
                else:
                    total_score += score

            attempt.total_score = None if has_pending else round(total_score, 2)

        attempt.status = "pending_review" if not timed_out and has_pending else "graded"
        attempt.submitted_at = now
        db.flush()
        if attempt.status == "graded" and not timed_out:
            _record_wrong_answers(db, attempt, exam)
        db.commit()

    except Exception:
        db.rollback()
        raise

    result = get_exam_result(db, student_id, attempt_id)
    result["timed_out"] = timed_out
    return result


def _record_wrong_answers(db, attempt, exam):
    """全部判完后才把失分题写入错题库。"""
    answers = db.scalars(select(ExamAnswer).where(
        ExamAnswer.exam_attempt_id == attempt.id,
        ExamAnswer.is_correct.is_(False),
    )).all()
    for answer in answers:
        question = db.get(Question, answer.question_id)
        old_wrong = db.scalar(select(WrongQuestion).where(
            WrongQuestion.student_id == attempt.student_id,
            WrongQuestion.course_id == exam.course_id,
            WrongQuestion.question_id == question.id,
        ))
        if old_wrong is None:
            db.add(WrongQuestion(
                student_id=attempt.student_id,
                course_id=exam.course_id,
                question_id=question.id,
                topic=question.topic,
                mistake=f"考试 {exam.id} 中回答错误，作答：{answer.answer}",
            ))


def list_pending_reviews(db, teacher_id: str, course_id: str) -> list[dict]:
    require_teacher_course_access(db, teacher_id, course_id)
    attempts = db.scalars(select(ExamAttempt).join(
        Exam, Exam.id == ExamAttempt.exam_id,
    ).where(Exam.course_id == course_id,
            ExamAttempt.status == "pending_review").order_by(ExamAttempt.submitted_at)).all()
    return [{"attempt_id": item.id, "exam_id": item.exam_id,
             "student_id": item.student_id, "submitted_at": item.submitted_at.isoformat()}
            for item in attempts]


def get_review_detail(db, teacher_id: str, attempt_id: int) -> dict:
    attempt = db.get(ExamAttempt, attempt_id)
    if attempt is None:
        raise ValueError("考试记录不存在")
    exam = db.get(Exam, attempt.exam_id)
    require_teacher_course_access(db, teacher_id, exam.course_id)
    if attempt.status != "pending_review":
        raise ValueError("该考试当前没有待批改的简答题")
    answers = {answer.question_id: answer for answer in db.scalars(select(ExamAnswer).where(
        ExamAnswer.exam_attempt_id == attempt.id,
    )).all()}
    return {"attempt_id": attempt.id, "exam_title": exam.title,
            "student_id": attempt.student_id, "course_id": exam.course_id,
            "questions": [
                {"question_id": row.question_id, "position": row.position,
                 "stem": question.stem, "answer": answers[row.question_id].answer,
                 "reference_answer": question.answer_key, "explanation": question.explanation,
                 "points": row.points, "grading_status": answers[row.question_id].grading_status,
                 "score": answers[row.question_id].score}
                for row in _question_rows(db, exam.id)
                for question in [db.get(Question, row.question_id)]
                if question.question_type == "short_answer"
            ]}


def grade_short_answers(db, teacher_id: str, attempt_id: int, grades: list[dict]) -> dict:
    detail = get_review_detail(db, teacher_id, attempt_id)
    pending = {item["question_id"]: item for item in detail["questions"]
               if item["grading_status"] == "pending"}
    submitted = {item.get("question_id"): item.get("score") for item in grades}
    if len(submitted) != len(grades) or set(submitted) != set(pending):
        raise ValueError("须一次提交全部待批改简答题且不能重复")
    for question_id, score in submitted.items():
        if (type(score) not in (int, float) or not isfinite(score)
                or score < 0 or score > pending[question_id]["points"]):
            raise ValueError(f"题目 {question_id} 得分须在 0 到满分之间")
    attempt = db.get(ExamAttempt, attempt_id)
    exam = db.get(Exam, attempt.exam_id)
    try:
        answers = db.scalars(select(ExamAnswer).where(
            ExamAnswer.exam_attempt_id == attempt_id,
        )).all()
        for answer in answers:
            if answer.question_id in submitted:
                score = round(float(submitted[answer.question_id]), 2)
                answer.score = score
                answer.is_correct = score == float(pending[answer.question_id]["points"])
                answer.grading_status = "graded"
        attempt.total_score = round(sum(float(answer.score) for answer in answers), 2)
        attempt.status = "graded"
        db.flush()
        _record_wrong_answers(db, attempt, exam)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"attempt_id": attempt.id, "status": attempt.status,
            "total_score": attempt.total_score}
#学生在自己已经选择的课程中查询已经发布的考试
def list_available_exams(
    db,
    student_id,
):
    statement = (
        select(Exam, Course)
        .join(
            Course,
            Course.id == Exam.course_id,
        )
        .join(
            Enrollment,
            Enrollment.course_id == Exam.course_id,
        )
        .where(
            Enrollment.student_id == student_id,
            Course.status == "active",
            Exam.status == "published",
        )
        .order_by(Exam.created_at.desc())
    )
    rows = db.execute(statement).all()
    return [
        {
            "exam_id": exam.id,
            "course_id": course.id,
            "course_name": course.name,
            "title": exam.title,
            "duration_minutes": exam.duration_minutes,
            "status": exam.status,
        }
        for exam, course in rows
    ]
