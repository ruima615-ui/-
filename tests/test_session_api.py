import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException
from pydantic import ValidationError


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))


from app.api import sessions as sessions_api
from app.schemas.session import CreateSessionRequest


class FakeDb:
    """只实现 create_session() 会用到的 db.get()。"""

    def __init__(self, course, enrollment):
        self.course = course
        self.enrollment = enrollment
        self.enrollment_key = None

    def get(self, model, key):
        if model is sessions_api.Course:
            return self.course

        if model is sessions_api.Enrollment:
            self.enrollment_key = key
            return self.enrollment

        raise AssertionError(
            f"测试中出现了未预期的数据库查询：{model}, {key}"
        )


def test_create_session_success():
    """已选课学生可以创建课程会话。"""

    current_user = SimpleNamespace(
        id="STUDENT_001",
        role="student",
        status="active",
    )

    course = SimpleNamespace(
        id="COURSE_001",
        status="active",
    )

    enrollment = SimpleNamespace(
        student_id="STUDENT_001",
        course_id="COURSE_001",
    )

    fake_db = FakeDb(
        course=course,
        enrollment=enrollment,
    )

    create_requests = []

    def fake_create_memory_session(**kwargs):
        create_requests.append(kwargs)

        return SimpleNamespace(
            id=kwargs["session_id"],
            user_id=kwargs["user_id"],
            course_id=kwargs["course_id"],
            title=kwargs["title"],
            status="active",
            created_at=datetime(2026, 1, 1, 10, 0, 0),
        )

    original_create_memory_session = (
        sessions_api.create_memory_session
    )

    try:
        sessions_api.create_memory_session = (
            fake_create_memory_session
        )

        request = CreateSessionRequest(
            course_id="COURSE_001",
            title="Python列表错题复习",
        )

        response = sessions_api.create_session(
            request=request,
            db=fake_db,
            current_user=current_user,
        )

        assert response.session_id.startswith("SESSION_")
        assert response.user_id == "STUDENT_001"
        assert response.course_id == "COURSE_001"
        assert response.title == "Python列表错题复习"
        assert response.status == "active"

        # 验证选课查询使用的是当前登录学生。
        assert fake_db.enrollment_key == (
            "STUDENT_001",
            "COURSE_001",
        )

        assert len(create_requests) == 1

        saved_request = create_requests[0]

        # 会话用户必须来自 current_user。
        assert saved_request["user_id"] == "STUDENT_001"
        assert saved_request["course_id"] == "COURSE_001"
        assert saved_request["db"] is fake_db

        print("创建课程会话成功测试通过")
        print("会话编号：", response.session_id)
        print("会话学生：", response.user_id)
        print("会话课程：", response.course_id)

    finally:
        sessions_api.create_memory_session = (
            original_create_memory_session
        )


def test_create_session_rejects_unenrolled_student():
    """未选课学生不能创建该课程的会话。"""

    current_user = SimpleNamespace(
        id="STUDENT_002",
        role="student",
        status="active",
    )

    course = SimpleNamespace(
        id="COURSE_001",
        status="active",
    )

    fake_db = FakeDb(
        course=course,
        enrollment=None,
    )

    request = CreateSessionRequest(
        course_id="COURSE_001",
        title="不允许创建的会话",
    )

    try:
        sessions_api.create_session(
            request=request,
            db=fake_db,
            current_user=current_user,
        )

    except HTTPException as error:
        assert error.status_code == 403
        assert error.detail == "当前学生未选修这门课程"

    else:
        raise AssertionError(
            "未选课学生创建会话时应当返回403"
        )

    assert fake_db.enrollment_key == (
        "STUDENT_002",
        "COURSE_001",
    )

    print("未选课学生拒绝测试通过")


def test_request_cannot_choose_user_id():
    """请求体不能指定或伪造学生编号。"""

    try:
        CreateSessionRequest(
            course_id="COURSE_001",
            title="尝试伪造身份",
            user_id="OTHER_STUDENT",
        )

    except ValidationError as error:
        validation_errors = error.errors()

        assert len(validation_errors) == 1
        assert validation_errors[0]["loc"] == (
            "user_id",
        )
        assert (
            validation_errors[0]["type"]
            == "extra_forbidden"
        )

    else:
        raise AssertionError(
            "CreateSessionRequest 应拒绝 user_id 字段"
        )

    print("请求体伪造用户身份拒绝测试通过")


if __name__ == "__main__":
    test_create_session_success()

    print("-" * 60)

    test_create_session_rejects_unenrolled_student()

    print("-" * 60)

    test_request_cannot_choose_user_id()