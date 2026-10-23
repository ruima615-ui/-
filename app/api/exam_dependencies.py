import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import JWT_SECRET_KEY
from app.core.config import JWT_ALGORITHM
from app.core.database import get_db
from app.models.entities import User


bearer = HTTPBearer(auto_error=False)

#确认这次请求是谁发的
def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db=Depends(get_db),
):
    if credentials is None:
        raise HTTPException(status_code=401, detail="请先登录")

    try:
        payload = jwt.decode(
            credentials.credentials,
            JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
        )
        user_id = payload.get("sub")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="登录凭证无效或已过期")

    if not user_id:
        raise HTTPException(status_code=401, detail="登录凭证缺少用户ID")

    user = db.get(User, user_id)
    if user is None or user.status != "active":
        raise HTTPException(status_code=401, detail="用户不存在或账号不可用")

    return user
