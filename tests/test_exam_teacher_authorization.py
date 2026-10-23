import unittest
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.api.exams import CreateExamRequest
from app.api.exams import ExamItem
from app.api.exams import create_draft
from app.models.entities import Course
from app.models.entities import Exam
from app.models.entities import Question
from app.models.entities import TeacherCourseAssignment
from app.models.entities import User
from app.services.exam_service import create_exam_draft
from app.services.exam_service import publish_exam


class ExamTeacherAuthorizationTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()

        self.db.add_all([
            User(
                id="ADMIN_001",
                name="管理员",
                role="admin",
                status="active",
            ),
            User(
                id="TEACHER_001",
                name="课程教师",
                role="teacher",
                status="active",
            ),
            User(
                id="TEACHER_002",
                name="其他教师",
                role="teacher",
                status="active",
            ),
            Course(
                id="COURSE_001",
                code="COURSE001",
                name="测试课程",
                status="active",
            ),
            Question(
                id="QUESTION_001",
                course_id="COURSE_001",
                question_type="single_choice",
                topic="测试知识点",
                stem="正确答案是哪一个？",
                options={"A": "正确", "B": "错误"},
                answer_key="A",
                max_score=5.0,
            ),
            TeacherCourseAssignment(
                teacher_id="TEACHER_001",
                course_id="COURSE_001",
                assigned_by="ADMIN_001",
            ),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def create_draft(self, user_id: str):
        return create_exam_draft(
            db=self.db,
            teacher_id=user_id,
            course_id="COURSE_001",
            title="权限测试试卷",
            duration_minutes=30,
            items=[
                {
                    "question_id": "QUESTION_001",
                    "points": 5,
                }
            ],
        )

    def test_assigned_teacher_can_create_and_publish_exam(self):
        result = self.create_draft("TEACHER_001")
        exam = self.db.get(Exam, result["exam_id"])

        self.assertEqual(exam.created_by, "TEACHER_001")
        self.assertEqual(exam.status, "draft")

        published = publish_exam(
            db=self.db,
            teacher_id="TEACHER_001",
            exam_id=exam.id,
        )
        self.assertEqual(published["status"], "published")

    def test_admin_cannot_create_or_publish_exam(self):
        with self.assertRaises(PermissionError):
            self.create_draft("ADMIN_001")

        result = self.create_draft("TEACHER_001")
        with self.assertRaises(PermissionError):
            publish_exam(
                db=self.db,
                teacher_id="ADMIN_001",
                exam_id=result["exam_id"],
            )

    def test_unassigned_teacher_cannot_create_exam(self):
        with self.assertRaises(PermissionError):
            self.create_draft("TEACHER_002")

    def test_exam_api_rejects_admin_role(self):
        request = CreateExamRequest(
            course_id="COURSE_001",
            title="管理员不能创建的试卷",
            duration_minutes=30,
            items=[
                ExamItem(
                    question_id="QUESTION_001",
                    points=5,
                )
            ],
        )

        with self.assertRaises(HTTPException) as context:
            create_draft(
                body=request,
                db=self.db,
                user=SimpleNamespace(
                    id="ADMIN_001",
                    role="admin",
                ),
            )

        self.assertEqual(context.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
