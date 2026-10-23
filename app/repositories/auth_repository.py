#负责将密码哈希写入和读出数据库
from sqlalchemy.orm import Session

from app.models.entities import User
from app.models.entities import UserCredential
#查询user表格，确定用户是否存在以及角色是什么
def get_user_by_id(
    db: Session,
    user_id: str
):
    return db.get(
        User,
        user_id
    )
#查询用户凭证表格，获得数据库中的密码哈希
def get_user_credential(
    db: Session,
    user_id: str
):
    """根据用户编号查询登录凭据"""

    return db.get(
        UserCredential,
        user_id
    )
#第一次设置密码时创建凭据，以后修改密码时更新原来的凭据
def save_user_credential(
    db: Session,
    user_id: str,
    password_hash: str
):
    """创建或者更新用户的密码哈希"""

    credential = get_user_credential(
        db=db,
        user_id=user_id
    )

    # 该用户还没有登录凭据
    if credential is None:
        credential = UserCredential(
            user_id=user_id,
            password_hash=password_hash
        )

        db.add(credential)

    # 该用户已经存在登录凭据，更新密码
    else:
        credential.password_hash = password_hash

    db.commit()
    db.refresh(credential)

    return credential
# 创建任意系统角色的账号；允许哪些角色由业务层决定。
def create_user_account(
    db: Session,
    user_id: str,
    name: str,
    password_hash: str,
    role: str,
    status: str = "active",
):
    """在同一个事务中创建用户资料和登录凭据。"""

    user = User(
        id=user_id,
        name=name,
        role=role,
        status=status,
    )

    credential = UserCredential(
        user_id=user_id,
        password_hash=password_hash
    )

    try:
        # 先添加用户
        db.add(user)

        # 将用户写入当前事务，但暂时不提交
        db.flush()

        # 再添加与用户关联的凭据
        db.add(credential)

        # 两条数据一起提交，不能出现用户创建但是没有密码
        db.commit()

        db.refresh(user)

        return user

    except Exception:
        # 任何一步出错，都撤销本次操作
        db.rollback()
        raise


def create_student_account(
    db: Session,
    user_id: str,
    name: str,
    password_hash: str,
):
    """创建公开注册使用的学生账号。"""

    return create_user_account(
        db=db,
        user_id=user_id,
        name=name,
        password_hash=password_hash,
        role="student",
        status="active",
    )
