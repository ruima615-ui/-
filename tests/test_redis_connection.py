from app.core.redis_client import (
    check_redis_connection,
    redis_client
)
def test_redis():
    # 1. 测试连接
    result = check_redis_connection()
    print("连接结果：", result)

    if result["status"] != "success":
        return

    # 2. 写入一条60秒后过期的数据
    redis_client.set(
        name="coursepilot:test:connection",
        value="Redis读写成功",
        ex=60
    )

    # 3. 读取数据
    value = redis_client.get(
        "coursepilot:test:connection"
    )

    # 4. 查询剩余有效时间
    ttl = redis_client.ttl(
        "coursepilot:test:connection"
    )

    print("读取结果：", value)
    print("剩余时间：", ttl, "秒")


if __name__ == "__main__":
    test_redis()