"""统一管理Redis短期记忆和SQLite长期记忆"""
#sqlite永久保存完整对话
#redis保存上下文，快速提供最近对话
#禁止关闭后的会话继续聊天
import json

from redis.exceptions import RedisError
from sqlalchemy.orm import Session

from app.memory.short_term_memory import add_message as add_short_term_message
from app.memory.short_term_memory import get_recent_messages as get_short_term_messages
from app.repositories.conversation_repository import add_chat_message
from app.repositories.conversation_repository import create_chat_session
from app.repositories.conversation_repository import get_chat_session
from app.repositories.conversation_repository import get_recent_chat_messages
#检查会话归属和状态
def check_session_owner(db, user_id, session_id):
    session = get_chat_session(
    db=db,
    session_id=session_id
)
    #检查1：会话是否存在
    if session is None:
        raise ValueError(f"会话不存在：{session_id}")
    #检查2:会话是否属于当前用户
    if session.user_id != user_id:#用户A不能访问用户B的会话
        raise PermissionError(
            f"用户{user_id}无权访问会话{session_id}"
        )
    #检查3：会话是否关闭
    if session.status != "active":
        raise PermissionError(
            f"会话{session_id}已经关闭，不能继续发送消息"
        )
    return session
def create_memory_session(
    db: Session,
    session_id: str,
    user_id: str,
    course_id: str | None = None,
    title: str | None = None
):
    """在SQLite中创建一段新会话"""

    return create_chat_session(
        db=db,
        session_id=session_id,
        user_id=user_id,
        course_id=course_id,
        title=title
    )
def save_message(
    db: Session,
    user_id: str,
    session_id: str,
    role: str,
    content: str,
    metadata: dict | None = None,
):
    """将一条消息保存到SQLite和Redis"""

    # 确保当前用户只能操作自己的会话
    check_session_owner(
        db=db,
        user_id=user_id,
        session_id=session_id
    )

    # 第一步：先保存到SQLite
    # SQLite是长期记忆，也是可信数据源
    saved_message = add_chat_message(
        db=db,
        session_id=session_id,
        role=role,
        content=content,
        metadata_json=(
            json.dumps(
                metadata,
                ensure_ascii=False,
                default=str,
            )
            if metadata
            else None
        ),
    )

    # 第二步：再保存到Redis
    try:
        add_short_term_message(
            user_id=user_id,
            session_id=session_id,
            role=role,
            content=content
        )

        print("消息已保存到SQLite和Redis")

    except RedisError as error:
        # Redis失败不会撤销已经写入SQLite的数据
        print(
            "Redis写入失败，消息已保存在SQLite：",
            error
        )

    return saved_message
#读取最近对话
def load_context(
    db: Session,
    user_id: str,
    session_id: str,
    limit: int = 20
):
    """读取Agent需要的最近对话上下文"""

    # 先检查用户是否有权访问这段会话
    check_session_owner(
        db=db,
        user_id=user_id,
        session_id=session_id
    )

    # 第一步：优先从Redis读取
    try:
        cached_messages = get_short_term_messages(
            user_id=user_id,
            session_id=session_id
        )

        if cached_messages:
            print("Redis记忆命中")

            return cached_messages[-limit:]

    except RedisError as error:
        print(
            "Redis读取失败，准备从SQLite读取：",
            error
        )

    # 第二步：Redis没有内容，从SQLite读取
    print("Redis记忆未命中，回源SQLite")

    database_messages = get_recent_chat_messages(
        db=db,
        session_id=session_id,
        limit=limit
    )

    # 把SQLAlchemy对象转换成模型需要的消息字典
    context_messages = []

    for message in database_messages:
        message_dict = {
            "role": message.role,
            "content": message.content
        }

        context_messages.append(message_dict)

    # 第三步：把SQLite查出的内容重新写入Redis
    try:
        for message in context_messages:
            add_short_term_message(
                user_id=user_id,
                session_id=session_id,
                role=message["role"],
                content=message["content"]
            )

        if context_messages:
            print("SQLite历史消息已回填Redis")

    except RedisError as error:
        print(
            "Redis回填失败，本次继续使用SQLite结果：",
            error
        )

    return context_messages
