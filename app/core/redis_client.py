#创建redis客户端检查redis连接
import redis

from app.core.config import REDIS_URL

#创建redis客户端
redis_client = redis.Redis.from_url(
    REDIS_URL,
    decode_responses=True,
    socket_connect_timeout=3,
    socket_timeout=3
)
def check_redis_connection():
    """检查python程序是否能够连接redis"""
    try:
        redis_client.ping()

        return {
            "status": "success",
            "message": "Redis连接成功"
        }
    except redis.REdisError as error:
        return 
    {
            "status": "error",
            "message": f"Redis连接失败：{error}"
    }