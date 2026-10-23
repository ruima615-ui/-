#使用redis 保存和读取近期对话
import json

from app.core.config import (
    MAX_CONTEXT_MESSAGES,#保存最多可保存多少内容
    SESSION_TTL_SECONDS#这些对话可以存活时间
)
from app.core.redis_client import redis_client


def build_session_key(user_id, session_id):
    """生成当前用户、当前会话对应的Redis键"""
    return (
        f"coursepilot:session:"
        f"{user_id}:{session_id}:messages"
    )
def add_message(user_id,session_id,role,content):
    """向redis保存一条对话消息"""
    key=build_session_key(
        user_id=user_id,
        session_id=session_id
    )
    #创建python字典
    message={
        "role":role,
        "content":content
    }
    # Redis不能直接保存Python字典，需要先转换为JSON字符串
    message_json = json.dumps(
        message,
        ensure_ascii=False
    )
      # pipeline将多条Redis命令组合执行
    with redis_client.pipeline() as pipeline:
        # 把新消息添加到列表末尾
        pipeline.rpush(key, message_json)

        # 只保留最近MAX_CONTEXT_MESSAGES条消息
        pipeline.ltrim(
            key,
            -MAX_CONTEXT_MESSAGES,
            -1
        )

        # 设置整个会话的过期时间
        pipeline.expire(
            key,
            SESSION_TTL_SECONDS
        )

        pipeline.execute()
def get_recent_messages(user_id, session_id):
    #读取当前会话最近的消息
    key = build_session_key(
    user_id=user_id,
    session_id=session_id
)
    #读取整个redis列表
    message_json_list = redis_client.lrange(
    key,
    0,
    -1
)
    messages = []
#字符串转为字典，加入发给模型的Messages中
    for message_json in message_json_list:
        message = json.loads(message_json)
        messages.append(message)
    return messages
def clear_session_messages(user_id, session_id):
    #删除当前对话在redis中的短期记忆
    key = build_session_key(
        user_id=user_id,
        session_id=session_id
    )
    redis_client.delete(key)
def get_session_ttl(user_id, session_id):
    """查询当前会话还剩多少秒过期"""

    key = build_session_key(
        user_id=user_id,
        session_id=session_id
    )
    return redis_client.ttl(key)