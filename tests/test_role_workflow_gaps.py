"""管理员分配入口和学生考试记录入口的权限与数据范围。"""

import unittest
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.entities import Course, Exam, ExamAttempt, User
from app.services.exam_attempt_service import list_student_attempts
from app.services.course_service import create_course, publish_course
from app.services.teacher_service import (list_active_teachers_and_courses,
    assign_teacher_to_course, list_teacher_course_assignments,
    revoke_teacher_course_assignment)


class RoleWorkflowGapsTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.db.add_all([
            User(id="A1", name="管理员", role="admin", status="active"),
            User(id="T1", name="教师", role="teacher", status="active"),
            User(id="T2", name="待审教师", role="teacher", status="pending"),
            User(id="S1", name="学生甲", role="student", status="active"),
            User(id="S2", name="学生乙", role="student", status="active"),
            Course(id="C1", code="C1", name="有效课程", status="active"),
            Course(id="C2", code="C2", name="停用课程", status="inactive"),
        ])
        self.db.flush()
        self.db.add_all([
            Exam(id="E1", course_id="C1", title="考试甲", status="published", duration_minutes=30),
            Exam(id="E2", course_id="C1", title="考试乙", status="published", duration_minutes=45),
        ])
        self.db.flush()
        self.db.add_all([
            ExamAttempt(exam_id="E1", student_id="S1", status="graded", total_score=8,
                        started_at=datetime(2026, 10, 20, 8)),
            ExamAttempt(exam_id="E2", student_id="S2", status="pending_review",
                        started_at=datetime(2026, 10, 20, 9)),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_admin_assignment_options_are_active_and_role_scoped(self):
        result = list_active_teachers_and_courses(self.db, "A1")
        self.assertEqual([item["user_id"] for item in result["teachers"]], ["T1"])
        self.assertEqual([item["course_id"] for item in result["courses"]], ["C1"])
        with self.assertRaises(PermissionError):
            list_active_teachers_and_courses(self.db, "S1")

    def test_student_attempts_are_private_and_include_deadline(self):
        result = list_student_attempts(self.db, "S1")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["exam_id"], "E1")
        self.assertEqual(result[0]["deadline"], "2026-10-20T08:30:00")
        self.assertEqual([item["exam_id"] for item in list_student_attempts(self.db, "S2")], ["E2"])

    def test_only_admin_can_create_unique_course(self):
        course = create_course(self.db, "A1", "python101", "Python 基础")
        self.assertEqual(course.code, "PYTHON101")
        self.assertEqual(course.status, "draft")
        self.assertNotIn(course.id, [item["course_id"] for item in
                          list_active_teachers_and_courses(self.db, "A1")["courses"]])
        publish_course(self.db, "A1", course.id)
        self.assertIn(course.id, [item["course_id"] for item in
                       list_active_teachers_and_courses(self.db, "A1")["courses"]])
        with self.assertRaisesRegex(ValueError, "已存在"):
            create_course(self.db, "A1", "PYTHON101", "重复")
        with self.assertRaises(PermissionError):
            create_course(self.db, "T1", "COURSE3", "越权课程")

    def test_admin_can_list_and_revoke_teacher_course_assignment(self):
        assign_teacher_to_course(self.db, "A1", "T1", "C1")
        listed = list_teacher_course_assignments(self.db, "A1")
        self.assertEqual([(row["teacher_id"], row["course_id"]) for row in listed],
                         [("T1", "C1")])
        with self.assertRaises(PermissionError):
            revoke_teacher_course_assignment(self.db, "S1", "T1", "C1")
        revoke_teacher_course_assignment(self.db, "A1", "T1", "C1")
        self.assertEqual(list_teacher_course_assignments(self.db, "A1"), [])


if __name__ == "__main__":
    unittest.main()
