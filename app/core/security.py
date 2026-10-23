#集中处理密码和JWT令牌的安全计算
#明文密码-密码哈希，明文密码与哈希是否匹配
#用户身份-生成JWT令牌，JWT-验证并解析用户身份
from datetime import datetime
from datetime import timedelta
from datetime import timezone

import jwt
from pwdlib import PasswordHash

from app.core.config import ACCESS_TOKEN_EXPIRE_MINUTES
from app.core.config import JWT_ALGORITHM
from app.core.config import JWT_SECRET_KEY


# 创建密码哈希工具，使用推荐算法Argon2
password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    """把明文密码转换成不可逆的密码哈希"""

    return password_hash.hash(password)


def verify_password(
    plain_password: str,
    stored_password_hash: str
) -> bool:
    """检查用户输入的密码是否与数据库中的哈希匹配"""

    return password_hash.verify(
        plain_password,
        stored_password_hash
    )


def create_access_token(
    user_id: str,
    role: str
) -> str:
    """为登录成功的用户生成JWT"""

    expire_time = (
        datetime.now(timezone.utc)
        + timedelta(
            minutes=ACCESS_TOKEN_EXPIRE_MINUTES
        )
    )

    payload = {
        "sub": user_id,
        "role": role,
        "exp": expire_time
    }

    token = jwt.encode(
        payload,
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM
    )

    return token


def decode_access_token(token: str) -> dict:
    """验证并解析JWT"""

    payload = jwt.decode(
        token,
        JWT_SECRET_KEY,
        algorithms=[JWT_ALGORITHM]
    )

    return payload