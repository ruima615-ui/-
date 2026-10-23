"""负责对话会话和长期消息的数据库操作"""

from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.entities import ChatMessage
from app.models.entities import ChatSession
#创建一段新对话

def create_chat_session(
    db: Session,
    session_id: str,
    user_id: str,
    course_id: str | None = None,
    title: str | None = None
):
    """创建一段新对话"""

    session = ChatSession(
        id=session_id,
        user_id=user_id,
        course_id=course_id,
        title=title
    )

    db.add(session)
    db.commit()
    db.refresh(session)

    return session

#根据会话编号找到对话
def get_chat_session(db: Session, session_id: str):
    """根据会话编号查询会话"""

    return db.get(ChatSession, session_id)

#保存一条用户或者对手消息
def add_chat_message(
    db: Session,
    session_id: str,
    role: str,
    content: str,
    metadata_json: str | None = None,
):
    """向指定会话中保存一条长期消息"""

    # 先确认会话存在
    session = get_chat_session(
        db=db,
        session_id=session_id
    )

    if session is None:
        raise ValueError(f"会话不存在：{session_id}")

    message = ChatMessage(
        session_id=session_id,
        role=role,
        content=content,
        metadata_json=metadata_json,
    )

    db.add(message)
    db.commit()
    db.refresh(message)

    return message
#读取某个会话最近的若干条消息
def get_recent_chat_messages(
    db: Session,
    session_id: str,
    limit: int = 20
):
    """读取某个会话最近的若干条消息"""

    statement = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id.desc())
        .limit(limit)
    )

    messages = list(
        db.scalars(statement).all()
    )

    # 数据库查出来的顺序是从新到旧，
    # 反转后变成正常的对话顺序：从旧到新
    messages.reverse()

    return messages

#增加查询函数
def get_user_chat_sessions(
    db: Session,
    user_id: str
):
    """查询某个用户创建的全部会话"""
#查询chat_session表，只保留user_id匹配的记录，按照创建时间从新到旧排序，转换成列表返回
    statement = (
        select(ChatSession)
        .where(ChatSession.user_id == user_id)
        .order_by(ChatSession.created_at.desc())
    )

    sessions = db.scalars(statement).all()

    return list(sessions)
#关闭会话
def close_chat_session(
    db: Session,
    session_id: str
):
    """把指定会话修改为关闭状态"""

    session = db.get(
        ChatSession,
        session_id
    )
    #根据主键查询会话

    if session is None:
        return None

    session.status = "closed"

    db.commit()
    db.refresh(session)

    return session
