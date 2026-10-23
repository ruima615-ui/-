from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.core.security import hash_password
from app.core.security import verify_password

from app.repositories.auth_repository import create_student_account
from app.repositories.auth_repository import get_user_by_id
from app.repositories.auth_repository import get_user_credential


def register_student(
    db: Session,
    user_id: str,
    name: str,
    plain_password: str
):
    """注册学生账号"""

    # 第一步：检查用户编号是否已经存在
    existing_user = get_user_by_id(
        db=db,
        user_id=user_id
    )

    if existing_user is not None:
        raise ValueError(
            f"用户编号已经存在：{user_id}"
        )

    # 第二步：把明文密码转换成密码哈希
    hashed_password = hash_password(
        plain_password
    )

    # 第三步：让仓库层创建用户资料和登录凭据
    try:
        user = create_student_account(
            db=db,
            user_id=user_id,
            name=name,
            password_hash=hashed_password
        )

    except IntegrityError as error:
        raise ValueError(
            f"用户编号已经存在：{user_id}"
        ) from error

    return user


def authenticate_user(
    db: Session,
    user_id: str,
    plain_password: str
):
    """验证用户密码，成功后生成JWT"""

    # 第一步：查询用户
    user = get_user_by_id(
        db=db,
        user_id=user_id
    )

    if user is None:
        return None

    # 第二步：检查用户是否被停用
    if user.status == "pending":
        raise PermissionError(
            f"教师账号{user_id}正在等待管理员审核"
        )

    if user.status != "active":
        raise PermissionError(
            f"用户{user_id}已经被停用"
        )

    # 第三步：查询登录凭据
    credential = get_user_credential(
        db=db,
        user_id=user_id
    )

    if credential is None:
        return None

    # 第四步：验证用户输入的密码
    password_is_correct = verify_password(
        plain_password=plain_password,
        stored_password_hash=credential.password_hash
    )

    if not password_is_correct:
        return None

    # 第五步：密码正确，生成JWT
    access_token = create_access_token(
        user_id=user.id,
        role=user.role
    )

    return {
        "user": user,
        "access_token": access_token
    }
