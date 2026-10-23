"""为已有管理员安全地初始化或更新登录密码。"""

import argparse
from getpass import getpass

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.entities import User
from app.repositories.auth_repository import save_user_credential


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "admin_id",
        help="已有管理员的用户 ID",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        admin = db.get(User, args.admin_id)
        if admin is None or admin.role != "admin":
            raise ValueError("指定用户不是管理员")
        if admin.status != "active":
            raise ValueError("管理员账号不可用")

        password = getpass("输入管理员密码：")
        confirmation = getpass("再次输入管理员密码：")

        if password != confirmation:
            raise ValueError("两次输入的密码不一致")
        if not 8 <= len(password) <= 128:
            raise ValueError("密码长度必须为 8 到 128 个字符")

        save_user_credential(
            db=db,
            user_id=admin.id,
            password_hash=hash_password(password),
        )
        print(f"管理员 {admin.id} 的密码已保存")
    finally:
        db.close()


if __name__ == "__main__":
    main()
