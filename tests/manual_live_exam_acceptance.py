"""对正在运行的 FastAPI/Streamlit 做临时账号的三题型验收。

运行前确认本机 8000/8501 是当前项目。测试仅创建带 LIVE_ACCEPT_ 前缀的数据，
finally 中按精确 ID 删除本次数据；不会触碰已有账户、考试和聊天。
"""

import json
import sqlite3
from pathlib import Path
from uuid import uuid4

import requests
from sqlalchemy import delete, select
from streamlit.testing.v1 import AppTest

from app.core.config import AGENT_CHECKPOINT_FILE
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.entities import (
    ChatMessage, ChatSession, Course, Enrollment, Exam, ExamAnswer,
    ExamAttempt, ExamQuestion, Question, TeacherCourseAssignment, User,
    UserCredential, WrongQuestion,
)


ROOT = Path(__file__).resolve().parents[1]
API = "http://127.0.0.1:8000"
UI = "http://127.0.0.1:8501/_stcore/health"


def request(method, path, *, token=None, **kwargs):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = requests.request(method, API + path, headers=headers, timeout=90, **kwargs)
    if response.status_code >= 400:
        raise AssertionError(f"{method} {path}: HTTP {response.status_code} {response.text[:300]}")
    return response.json()


def login(user_id, password):
    return request("POST", "/api/auth/login",
                   data={"username": user_id, "password": password})["access_token"]


def find(elements, label):
    return next(item for item in elements if item.label == label)


def require_ui(app, phase):
    if app.exception:
        raise AssertionError(f"{phase} Streamlit exception: {app.exception[0].message}")


def ui_login(user_id, password):
    app = AppTest.from_file(str(ROOT / "frontend" / "streamlit_app.py"))
    app.run(timeout=20)
    require_ui(app, "login page")
    app.text_input[0].set_value(user_id)
    app.text_input[1].set_value(password)
    app.button[0].click().run(timeout=20)
    require_ui(app, "login")
    assert app.session_state["user_id"] == user_id
    return app


def cleanup(*, admin_id, teacher_id, student_id, course_id, question_ids,
            exam_id, session_id):
    ids = (admin_id, teacher_id, student_id)
    if not all(value.startswith("LIVE_ACCEPT_") for value in (*ids, course_id, *question_ids)):
        raise AssertionError("拒绝清理非本次验收 ID")
    with SessionLocal() as db:
        if session_id:
            db.execute(delete(ChatMessage).where(ChatMessage.session_id == session_id))
            db.execute(delete(ChatSession).where(ChatSession.id == session_id))
        if exam_id:
            attempt_ids = db.scalars(select(ExamAttempt.id).where(ExamAttempt.exam_id == exam_id)).all()
            if attempt_ids:
                db.execute(delete(ExamAnswer).where(ExamAnswer.exam_attempt_id.in_(attempt_ids)))
            db.execute(delete(ExamAttempt).where(ExamAttempt.exam_id == exam_id))
            db.execute(delete(ExamQuestion).where(ExamQuestion.exam_id == exam_id))
            db.execute(delete(Exam).where(Exam.id == exam_id))
        db.execute(delete(WrongQuestion).where(
            WrongQuestion.student_id == student_id, WrongQuestion.course_id == course_id))
        db.execute(delete(Question).where(Question.id.in_(question_ids)))
        db.execute(delete(Enrollment).where(
            Enrollment.student_id == student_id, Enrollment.course_id == course_id))
        db.execute(delete(TeacherCourseAssignment).where(
            TeacherCourseAssignment.teacher_id == teacher_id,
            TeacherCourseAssignment.course_id == course_id))
        db.execute(delete(UserCredential).where(UserCredential.user_id.in_(ids)))
        db.execute(delete(User).where(User.id.in_(ids)))
        db.execute(delete(Course).where(Course.id == course_id))
        db.commit()
    if session_id and AGENT_CHECKPOINT_FILE.exists():
        with sqlite3.connect(AGENT_CHECKPOINT_FILE) as connection:
            for table in ("checkpoints", "checkpoint_writes", "checkpoint_blobs"):
                if table in {row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")
                }:
                    connection.execute(f"DELETE FROM {table} WHERE thread_id = ?", (session_id,))
            connection.commit()


def main():
    assert requests.get(API + "/openapi.json", timeout=5).status_code == 200
    assert requests.get(UI, timeout=5).status_code == 200
    suffix = uuid4().hex[:8].upper()
    admin_id = f"LIVE_ACCEPT_A_{suffix}"
    teacher_id = f"LIVE_ACCEPT_T_{suffix}"
    student_id = f"LIVE_ACCEPT_S_{suffix}"
    course_id = f"LIVE_ACCEPT_C_{suffix}"
    question_ids = [f"LIVE_ACCEPT_Q{i}_{suffix}" for i in range(1, 4)]
    password = "LiveAccept-" + uuid4().hex[:16]
    exam_id = None
    session_id = None
    report = {}
    try:
        with SessionLocal() as db:
            db.add(User(id=admin_id, name="验收管理员", role="admin", status="active"))
            db.add(UserCredential(user_id=admin_id, password_hash=hash_password(password)))
            db.add(Course(id=course_id, code=f"AC{suffix}", name="验收课程",
                          description="临时合成课程", status="active"))
            for qid, qtype, stem, options, key in (
                (question_ids[0], "single_choice", "列表首项索引？",
                 {"A": "0", "B": "1"}, "A"),
                (question_ids[1], "multiple_choice", "哪些索引对长度为3的列表合法？",
                 {"A": "0", "B": "3", "C": "2"}, ["A", "C"]),
                (question_ids[2], "true_false", "长度为3的列表可以访问索引3。",
                 None, False),
            ):
                db.add(Question(
                    id=qid, course_id=course_id, question_type=qtype,
                    topic="Python列表", difficulty="easy", knowledge_count_level=1,
                    reasoning_level=0, transfer_level=0, distractor_level=0,
                    difficulty_score=1, stem=stem, options=options, answer_key=key,
                    explanation="列表索引从0到长度减1。", max_score=5.0,
                ))
            db.commit()

        registered = request("POST", "/api/auth/register/teacher", json={
            "user_id": teacher_id, "name": "验收教师", "password": password,
        })
        assert registered["status"] == "pending"
        admin_token = login(admin_id, password)
        request("POST", f"/api/teachers/{teacher_id}/approve", token=admin_token)
        request("POST", f"/api/teachers/{teacher_id}/courses/{course_id}", token=admin_token)
        request("POST", "/api/auth/register", json={
            "user_id": student_id, "name": "验收学生", "password": password,
        })
        student_token = login(student_id, password)
        request("POST", f"/api/courses/{course_id}/enroll", token=student_token)

        teacher_app = ui_login(teacher_id, password)
        assert any("教师工作台" in item.value for item in teacher_app.header)
        find(teacher_app.selectbox, "课程").set_value("AC" + suffix + " · 验收课程")
        find(teacher_app.text_input, "试卷名称").set_value("三题型验收卷")
        find(teacher_app.text_area, "题目 ID：每行一个").set_value("\n".join(question_ids))
        find(teacher_app.button, "创建试卷草稿").click().run(timeout=20)
        require_ui(teacher_app, "create draft")
        exam_id = teacher_app.session_state["created_exam"]["exam_id"]
        find(teacher_app.text_input, "要发布的试卷 ID").set_value(exam_id)
        find(teacher_app.button, "发布试卷").click().run(timeout=20)
        require_ui(teacher_app, "publish")

        student_app = ui_login(student_id, password)
        find(student_app.radio, "页面").set_value("学生考试")
        student_app.run(timeout=20)
        find(student_app.button, "开始考试").click().run(timeout=20)
        require_ui(student_app, "start exam")
        attempt_id = student_app.session_state["attempt_id"]
        paper = student_app.session_state["paper"]
        assert [item["question_type"] for item in paper["questions"]] == [
            "single_choice", "multiple_choice", "true_false"]
        assert "answer_key" not in json.dumps(paper)
        next(item for item in student_app.radio
             if item.key == f"exam_answer_{attempt_id}_{question_ids[0]}").set_value("B")
        next(item for item in student_app.multiselect
             if item.key == f"exam_answer_{attempt_id}_{question_ids[1]}").set_value(["A", "C"])
        next(item for item in student_app.radio
             if item.key == f"exam_answer_{attempt_id}_{question_ids[2]}").set_value(True)
        find(student_app.button, "提交试卷").click().run(timeout=20)
        require_ui(student_app, "submit")
        result = student_app.session_state["exam_result"]
        assert result["status"] == "graded" and result["total_score"] == 1.0
        assert [item["is_correct"] for item in result["answers"]] == [False, True, False]

        with SessionLocal() as db:
            wrong_ids = set(db.scalars(select(WrongQuestion.question_id).where(
                WrongQuestion.student_id == student_id,
                WrongQuestion.course_id == course_id,
            )).all())
        assert wrong_ids == {question_ids[0], question_ids[2]}

        session = request("POST", "/api/sessions", token=student_token,
                          json={"course_id": course_id, "title": "验收错题分析"})
        session_id = session["session_id"]
        chat = request("POST", "/api/chat", token=student_token, json={
            "session_id": session_id,
            "message": "请查询我当前课程的错题，分析薄弱知识点，并根据真实错题给复习建议。",
        })
        assert "get_current_course_wrong_questions" in chat["called_tools"]
        assert all(qid in chat["answer"] for qid in wrong_ids)
        report = {
            "backend_health": 200, "frontend_health": 200,
            "teacher_ui_draft_and_publish": True,
            "question_types": ["single_choice", "multiple_choice", "true_false"],
            "graded_score": result["total_score"], "wrong_count": len(wrong_ids),
            "agent_tools": chat["called_tools"], "agent_steps": chat["steps"],
            "agent_mentions_all_wrong_questions": True,
        }
    finally:
        cleanup(admin_id=admin_id, teacher_id=teacher_id, student_id=student_id,
                course_id=course_id, question_ids=question_ids, exam_id=exam_id,
                session_id=session_id)
    print(json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    main()
