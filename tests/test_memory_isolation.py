from app.core.config import MAX_CONTEXT_MESSAGES
from app.memory.short_term_memory import (
    add_message,
    clear_session_messages,
    get_recent_messages
)


def test_memory_isolation():
    """测试不同用户和不同会话的消息是否相互隔离"""

    test_sessions = [
        (1, "session-A"),
        (1, "session-B"),
        (2, "session-A")
    ]

    # 测试前清空数据
    for user_id, session_id in test_sessions:
        clear_session_messages(
            user_id=user_id,
            session_id=session_id
        )

    # 用户1的A会话
    add_message(
        user_id=1,
        session_id="session-A",
        role="user",
        content="这是用户1的A会话"
    )

    # 用户1的B会话
    add_message(
        user_id=1,
        session_id="session-B",
        role="user",
        content="这是用户1的B会话"
    )

    # 用户2的A会话
    add_message(
        user_id=2,
        session_id="session-A",
        role="user",
        content="这是用户2的A会话"
    )

    user1_session_a = get_recent_messages(1, "session-A")
    user1_session_b = get_recent_messages(1, "session-B")
    user2_session_a = get_recent_messages(2, "session-A")

    print("用户1会话A：", user1_session_a)
    print("用户1会话B：", user1_session_b)
    print("用户2会话A：", user2_session_a)

    assert user1_session_a[0]["content"] == "这是用户1的A会话"
    assert user1_session_b[0]["content"] == "这是用户1的B会话"
    assert user2_session_a[0]["content"] == "这是用户2的A会话"

    print("会话隔离测试通过")


def test_message_limit():
    """测试Redis是否只保留最近的消息"""

    user_id = 3
    session_id = "limit-test"

    clear_session_messages(
        user_id=user_id,
        session_id=session_id
    )

    # 比最大限制多写入5条
    for index in range(MAX_CONTEXT_MESSAGES + 5):
        add_message(
            user_id=user_id,
            session_id=session_id,
            role="user",
            content=f"第{index + 1}条消息"
        )

    messages = get_recent_messages(
        user_id=user_id,
        session_id=session_id
    )

    print("实际保留数量：", len(messages))
    print("第一条保留消息：", messages[0])
    print("最后一条保留消息：", messages[-1])

    assert len(messages) == MAX_CONTEXT_MESSAGES
    assert messages[-1]["content"] == (
        f"第{MAX_CONTEXT_MESSAGES + 5}条消息"
    )

    print("消息数量限制测试通过")


if __name__ == "__main__":
    test_memory_isolation()
    test_message_limit()