from app.memory.short_term_memory import (
    add_message,
    clear_session_messages,
    get_recent_messages,
    get_session_ttl
)


def test_short_term_memory():
    """测试Redis短期对话记忆"""

    user_id = 1
    session_id = "test-session-001"

    # 清除以前可能留下的同名测试数据
    clear_session_messages(
        user_id=user_id,
        session_id=session_id
    )

    # 保存第一条用户消息
    add_message(
        user_id=user_id,
        session_id=session_id,
        role="user",
        content="我的薄弱知识点是什么？"
    )

    # 保存第二条助手消息
    add_message(
        user_id=user_id,
        session_id=session_id,
        role="assistant",
        content="你需要优先复习Python列表。"
    )

    # 读取当前会话中的全部短期消息
    messages = get_recent_messages(
        user_id=user_id,
        session_id=session_id
    )

    # 查看剩余过期时间
    ttl = get_session_ttl(
        user_id=user_id,
        session_id=session_id
    )

    print("读取到的消息：")

    for message in messages:
        print(message)

    print("消息数量：", len(messages))
    print("剩余有效时间：", ttl, "秒")

    # 自动判断测试是否符合预期
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"
    assert ttl > 0

    print("短期记忆测试通过")


if __name__ == "__main__":
    test_short_term_memory()