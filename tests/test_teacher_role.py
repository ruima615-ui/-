import unittest

from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from app.api.exam_dependencies import get_current_user
from app.api.exam_dependencies import get_db
from app.core.database import Base
from app.core.security import create_access_token
from app.models.entities import Course
from app.models.entities import User
from app.services.auth_service import authenticate_user
from app.services.teacher_service import approve_teacher_account
from app.services.teacher_service import assign_teacher_to_course
from app.services.teacher_service import list_pending_teachers
from app.services.teacher_service import list_teacher_courses
from app.services.teacher_service import register_teacher_account
from app.services.teacher_service import require_teacher_course_access
from app.main import app


class TeacherRoleTest(unittest.TestCase):
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
                id="STUDENT_001",
                name="学生",
                role="student",
                status="active",
            ),
            Course(
                id="COURSE_001",
                code="COURSE001",
                name="测试课程",
                status="active",
            ),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_teacher_registration_approval_login_and_course_access(self):
        teacher = register_teacher_account(
            db=self.db,
            user_id="TEACHER_001",
            name="测试教师",
            plain_password="teacher123",
        )

        self.assertEqual(teacher.role, "teacher")
        self.assertEqual(teacher.status, "pending")
        self.assertEqual(
            [item.id for item in list_pending_teachers(
                self.db,
                "ADMIN_001",
            )],
            ["TEACHER_001"],
        )

        with self.assertRaisesRegex(
            PermissionError,
            "等待管理员审核",
        ):
            authenticate_user(
                db=self.db,
                user_id="TEACHER_001",
                plain_password="teacher123",
            )

        approved = approve_teacher_account(
            db=self.db,
            admin_id="ADMIN_001",
            teacher_id="TEACHER_001",
        )
        self.assertEqual(approved.status, "active")

        login_result = authenticate_user(
            db=self.db,
            user_id="TEACHER_001",
            plain_password="teacher123",
        )
        self.assertIsNotNone(login_result)
        self.assertEqual(login_result["user"].role, "teacher")

        assignment = assign_teacher_to_course(
            db=self.db,
            admin_id="ADMIN_001",
            teacher_id="TEACHER_001",
            course_id="COURSE_001",
        )
        self.assertEqual(assignment.assigned_by, "ADMIN_001")
        self.assertEqual(
            [course.id for course in list_teacher_courses(
                self.db,
                "TEACHER_001",
            )],
            ["COURSE_001"],
        )
        self.assertEqual(
            require_teacher_course_access(
                self.db,
                "TEACHER_001",
                "COURSE_001",
            ).id,
            "COURSE_001",
        )

        # 即使 JWT 中伪造 admin，当前身份仍以数据库角色为准。
        forged_token = create_access_token(
            user_id="TEACHER_001",
            role="admin",
        )
        current_user = get_current_user(
            credentials=HTTPAuthorizationCredentials(
                scheme="Bearer",
                credentials=forged_token,
            ),
            db=self.db,
        )
        self.assertEqual(current_user.role, "teacher")

    def test_non_admin_cannot_approve_or_assign_teacher(self):
        register_teacher_account(
            db=self.db,
            user_id="TEACHER_002",
            name="另一位教师",
            plain_password="teacher456",
        )

        with self.assertRaises(PermissionError):
            approve_teacher_account(
                db=self.db,
                admin_id="STUDENT_001",
                teacher_id="TEACHER_002",
            )

    def test_teacher_http_flow(self):
        def override_get_db():
            yield self.db

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)

        try:
            register_response = client.post(
                "/api/auth/register/teacher",
                json={
                    "user_id": "TEACHER_HTTP",
                    "name": "接口教师",
                    "password": "teacher789",
                },
            )
            self.assertEqual(register_response.status_code, 201)
            self.assertEqual(register_response.json()["status"], "pending")

            pending_login = client.post(
                "/api/auth/login",
                data={
                    "username": "TEACHER_HTTP",
                    "password": "teacher789",
                },
            )
            self.assertEqual(pending_login.status_code, 403)

            admin_headers = {
                "Authorization": "Bearer " + create_access_token(
                    user_id="ADMIN_001",
                    role="admin",
                )
            }
            pending_response = client.get(
                "/api/teachers/pending",
                headers=admin_headers,
            )
            self.assertEqual(pending_response.status_code, 200)
            self.assertEqual(
                pending_response.json()[0]["user_id"],
                "TEACHER_HTTP",
            )

            approve_response = client.post(
                "/api/teachers/TEACHER_HTTP/approve",
                headers=admin_headers,
            )
            self.assertEqual(approve_response.status_code, 200)

            assign_response = client.post(
                "/api/teachers/TEACHER_HTTP/courses/COURSE_001",
                headers=admin_headers,
            )
            self.assertEqual(assign_response.status_code, 201)

            active_login = client.post(
                "/api/auth/login",
                data={
                    "username": "TEACHER_HTTP",
                    "password": "teacher789",
                },
            )
            self.assertEqual(active_login.status_code, 200)
            teacher_headers = {
                "Authorization": (
                    "Bearer " + active_login.json()["access_token"]
                )
            }
            courses_response = client.get(
                "/api/teachers/me/courses",
                headers=teacher_headers,
            )
            self.assertEqual(courses_response.status_code, 200)
            self.assertEqual(
                courses_response.json()[0]["course_id"],
                "COURSE_001",
            )
        finally:
            app.dependency_overrides.clear()


if __name__ == "__main__":
    unittest.main()
