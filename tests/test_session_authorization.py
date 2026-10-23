import os
import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException
from pydantic import ValidationError


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

# 导入 chat.py 会间接导入 agent_runner.py。
# 提供测试 API Key，测试中不会发送网络请求。
os.environ.setdefault(
    "DEEPSEEK_API_KEY",
    "test-api-key",
)


from app.api import chat as chat_api
from app.api import sessions as sessions_api
from app.schemas.chat import ChatRequest


def make_student_a():
    return SimpleNamespace(
        id="STUDENT_A",
        role="student",
        status="active",
    )


def make_student_b_session():
    return SimpleNamespace(
        id="SESSION_B",
        user_id="STUDENT_B",
        course_id="COURSE_001",
        title="学生B的学习会话",
        status="active",
    )


def test_list_sessions_uses_current_user():
    """查询会话列表时只能查询 JWT 对应用户。"""

    fake_db = object()
    student_a = make_student_a()
    repository_requests = []

    def fake_get_user_chat_sessions(db, user_id):
        repository_requests.append({
            "db": db,
            "user_id": user_id,
        })

        return []

    original_function = (
        sessions_api.get_user_chat_sessions
    )

    try:
        sessions_api.get_user_chat_sessions = (
            fake_get_user_chat_sessions
        )

        response = sessions_api.list_user_sessions(
            db=fake_db,
            current_user=student_a,
        )

        assert response == []
        assert len(repository_requests) == 1

        request = repository_requests[0]

        assert request["db"] is fake_db
        assert request["user_id"] == "STUDENT_A"

        print("会话列表身份绑定测试通过")
        print("查询用户：", request["user_id"])

    finally:
        sessions_api.get_user_chat_sessions = (
            original_function
        )


def test_student_cannot_read_other_session():
    """学生 A 不能读取学生 B 的会话消息。"""

    fake_db = object()
    student_a = make_student_a()
    student_b_session = make_student_b_session()

    message_query_called = False

    def fake_get_chat_session(db, session_id):
        assert db is fake_db
        assert session_id == "SESSION_B"

        return student_b_session

    def fake_get_recent_chat_messages(
        db,
        session_id,
        limit,
    ):
        nonlocal message_query_called
        message_query_called = True

        return []

    original_get_session = (
        sessions_api.get_chat_session
    )
    original_get_messages = (
        sessions_api.get_recent_chat_messages
    )

    try:
        sessions_api.get_chat_session = (
            fake_get_chat_session
        )
        sessions_api.get_recent_chat_messages = (
            fake_get_recent_chat_messages
        )

        try:
            sessions_api.list_session_messages(
                session_id="SESSION_B",
                limit=20,
                db=fake_db,
                current_user=student_a,
            )

        except HTTPException as error:
            assert error.status_code == 403
            assert (
                error.detail
                == "当前用户无权查看这段会话"
            )

        else:
            raise AssertionError(
                "学生A读取学生B会话时应返回403"
            )

        # 权限检查失败后，不能继续读取聊天消息。
        assert message_query_called is False

        print("跨用户读取会话拒绝测试通过")

    finally:
        sessions_api.get_chat_session = (
            original_get_session
        )
        sessions_api.get_recent_chat_messages = (
            original_get_messages
        )


def test_student_cannot_close_other_session():
    """学生 A 不能关闭学生 B 的会话。"""

    fake_db = object()
    student_a = make_student_a()
    student_b_session = make_student_b_session()

    close_called = False

    def fake_get_chat_session(db, session_id):
        assert db is fake_db
        assert session_id == "SESSION_B"

        return student_b_session

    def fake_close_chat_session(db, session_id):
        nonlocal close_called
        close_called = True

        return student_b_session

    original_get_session = (
        sessions_api.get_chat_session
    )
    original_close_session = (
        sessions_api.close_chat_session
    )

    try:
        sessions_api.get_chat_session = (
            fake_get_chat_session
        )
        sessions_api.close_chat_session = (
            fake_close_chat_session
        )

        try:
            sessions_api.close_session(
                session_id="SESSION_B",
                db=fake_db,
                current_user=student_a,
            )

        except HTTPException as error:
            assert error.status_code == 403
            assert (
                error.detail
                == "当前用户无权关闭这段会话"
            )

        else:
            raise AssertionError(
                "学生A关闭学生B会话时应返回403"
            )

        # 权限检查失败后，关闭函数不能执行。
        assert close_called is False

        print("跨用户关闭会话拒绝测试通过")

    finally:
        sessions_api.get_chat_session = (
            original_get_session
        )
        sessions_api.close_chat_session = (
            original_close_session
        )


def test_chat_uses_current_user_identity():
    """
    聊天接口必须将 JWT 用户传给 Agent。

    即使请求中使用学生 B 的会话编号，
    传给 Agent 的用户仍然只能是学生 A。
    """

    student_a = make_student_a()
    agent_requests = []

    def fake_run_agent_with_memory(
        user_id,
        session_id,
        user_input,
    ):
        agent_requests.append({
            "user_id": user_id,
            "session_id": session_id,
            "user_input": user_input,
        })

        # 模拟 run_agent_with_memory 检查出会话属于学生 B。
        raise PermissionError("无权访问该会话")

    original_runner = (
        chat_api.run_agent_with_memory
    )

    try:
        chat_api.run_agent_with_memory = (
            fake_run_agent_with_memory
        )

        request = ChatRequest(
            session_id="SESSION_B",
            message="分析我的薄弱知识点",
        )

        try:
            chat_api.chat(
                request=request,
                current_user=student_a,
            )

        except HTTPException as error:
            assert error.status_code == 403
            assert error.detail == "无权访问该会话"

        else:
            raise AssertionError(
                "学生A使用学生B会话时应返回403"
            )

        assert len(agent_requests) == 1

        agent_request = agent_requests[0]

        # 关键断言：user_id 来自 current_user。
        assert agent_request["user_id"] == "STUDENT_A"
        assert agent_request["session_id"] == "SESSION_B"
        assert (
            agent_request["user_input"]
            == "分析我的薄弱知识点"
        )

        print("聊天接口身份绑定测试通过")
        print(
            "传给Agent的用户：",
            agent_request["user_id"],
        )
        print(
            "尝试访问的会话：",
            agent_request["session_id"],
        )

    finally:
        chat_api.run_agent_with_memory = (
            original_runner
        )


def test_chat_request_rejects_user_id():
    """聊天请求体不能伪造 user_id。"""

    try:
        ChatRequest(
            user_id="STUDENT_B",
            session_id="SESSION_B",
            message="尝试伪造身份",
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
            "ChatRequest 应拒绝 user_id 字段"
        )

    print("聊天请求伪造用户身份拒绝测试通过")


if __name__ == "__main__":
    test_list_sessions_uses_current_user()

    print("-" * 60)

    test_student_cannot_read_other_session()

    print("-" * 60)

    test_student_cannot_close_other_session()

    print("-" * 60)

    test_chat_uses_current_user_identity()

    print("-" * 60)

    test_chat_request_rejects_user_id()