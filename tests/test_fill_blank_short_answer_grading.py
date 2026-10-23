"""填空自动判分与简答人工批改的真实业务状态回归。"""

import unittest
from types import SimpleNamespace

from fastapi.testclient import TestClient

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.api.exam_dependencies import get_current_user, get_db
from app.main import app
from app.models.entities import (
    Course, Enrollment, ExamAnswer, Question, TeacherCourseAssignment, User, WrongQuestion,
)
from app.schemas.question import CreateQuestionRequest
from app.services.exam_attempt_service import (
    get_exam_result, get_review_detail, grade_short_answers, list_pending_reviews,
    start_exam, submit_exam,
)
from app.services.exam_service import create_exam_draft, publish_exam
from app.services.question_service import import_teacher_questions


class MixedGradingTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.db.add_all([
            User(id="A1", name="管理员", role="admin", status="active"),
            User(id="T1", name="教师", role="teacher", status="active"),
            User(id="T2", name="其他教师", role="teacher", status="active"),
            User(id="S1", name="学生", role="student", status="active"),
            Course(id="C1", code="C1", name="课程", status="active"),
            TeacherCourseAssignment(teacher_id="T1", course_id="C1", assigned_by="A1"),
            Enrollment(student_id="S1", course_id="C1"),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def setup_exam(self):
        items = [
            CreateQuestionRequest(course_id="C1", question_type="fill_blank", topic="列表",
                                  stem="首个下标？", answer_key=["0", "零"]),
            CreateQuestionRequest(course_id="C1", question_type="short_answer", topic="列表",
                                  stem="解释索引", answer_key="首个元素下标为 0"),
        ]
        ids = import_teacher_questions(self.db, "T1", "C1", items)["question_ids"]
        draft = create_exam_draft(self.db, "T1", "C1", "混合试卷", 30, [
            {"question_id": ids[0], "points": 2},
            {"question_id": ids[1], "points": 4},
        ])
        publish_exam(self.db, "T1", draft["exam_id"])
        attempt_id = start_exam(self.db, "S1", draft["exam_id"])["attempt_id"]
        return ids, attempt_id

    def test_pending_review_then_final_score_and_wrong_question(self):
        ids, attempt_id = self.setup_exam()
        submitted = submit_exam(self.db, "S1", attempt_id, [
            {"question_id": ids[0], "answer": "０ "},
            {"question_id": ids[1], "answer": "不完整解释"},
        ])
        self.assertEqual(submitted["status"], "pending_review")
        self.assertNotIn("total_score", submitted)
        self.assertEqual(get_exam_result(self.db, "S1", attempt_id)["status"], "pending_review")
        self.assertEqual(len(list_pending_reviews(self.db, "T1", "C1")), 1)
        self.assertEqual(get_review_detail(self.db, "T1", attempt_id)["questions"][0]["answer"], "不完整解释")
        self.assertEqual(self.db.scalar(select(func.count()).select_from(WrongQuestion)), 0)
        self.assertEqual(submit_exam(self.db, "S1", attempt_id, [])["status"], "pending_review")
        with self.assertRaises(PermissionError):
            grade_short_answers(self.db, "T2", attempt_id, [{"question_id": ids[1], "score": 1}])
        with self.assertRaises(ValueError):
            grade_short_answers(self.db, "T1", attempt_id, [{"question_id": ids[1], "score": 5}])
        self.assertEqual(self.db.scalar(select(func.count()).select_from(WrongQuestion)), 0)
        final = grade_short_answers(self.db, "T1", attempt_id, [{"question_id": ids[1], "score": 1}])
        self.assertEqual(final["total_score"], 3)
        result = get_exam_result(self.db, "S1", attempt_id)
        self.assertEqual(result["status"], "graded")
        self.assertEqual([answer["score"] for answer in result["answers"]], [2, 1])
        wrong = self.db.scalars(select(WrongQuestion)).all()
        self.assertEqual([item.question_id for item in wrong], [ids[1]])
        with self.assertRaises(ValueError):
            grade_short_answers(self.db, "T1", attempt_id, [{"question_id": ids[1], "score": 1}])

    def test_fill_blank_wrong_answer_is_graded_immediately(self):
        item = CreateQuestionRequest(course_id="C1", question_type="fill_blank", topic="列表",
                                     stem="首个下标？", answer_key="0")
        question_id = import_teacher_questions(self.db, "T1", "C1", [item])["question_ids"][0]
        draft = create_exam_draft(self.db, "T1", "C1", "填空卷", 30,
                                  [{"question_id": question_id, "points": 2}])
        publish_exam(self.db, "T1", draft["exam_id"])
        attempt_id = start_exam(self.db, "S1", draft["exam_id"])["attempt_id"]
        result = submit_exam(self.db, "S1", attempt_id, [{"question_id": question_id, "answer": "1"}])
        self.assertEqual(result["status"], "graded")
        self.assertEqual(result["total_score"], 0)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(WrongQuestion)), 1)

    def test_review_api_rejects_student_and_grades_for_teacher(self):
        ids, attempt_id = self.setup_exam()
        submit_exam(self.db, "S1", attempt_id, [
            {"question_id": ids[0], "answer": "0"},
            {"question_id": ids[1], "answer": "简答内容"},
        ])
        def session_override():
            yield self.db
        app.dependency_overrides[get_db] = session_override
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="S1", role="student")
        try:
            with TestClient(app) as client:
                url = f"/api/exams/review/{attempt_id}"
                self.assertEqual(client.get(url).status_code, 403)
                app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="T1", role="teacher")
                self.assertEqual(client.get("/api/exams/review/pending", params={"course_id": "C1"}).status_code, 200)
                self.assertEqual(client.get(url).json()["questions"][0]["reference_answer"], "首个元素下标为 0")
                grade = client.post(f"{url}/grades", json={"grades": [{"question_id": ids[1], "score": 4}]})
                self.assertEqual(grade.status_code, 200, grade.text)
                self.assertEqual(grade.json()["total_score"], 6)
        finally:
            app.dependency_overrides.clear()


if __name__ == "__main__":
    unittest.main()
