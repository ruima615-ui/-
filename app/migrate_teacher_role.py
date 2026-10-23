"""让现有 SQLite 数据库支持教师角色和教师课程授权。"""

import sqlite3
from datetime import datetime

from app.core.config import DATABASE_FILE


def backup_database(source: sqlite3.Connection):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = DATABASE_FILE.with_name(
        f"{DATABASE_FILE.stem}_before_teacher_{timestamp}.db"
    )
    target = sqlite3.connect(str(backup_file))
    try:
        source.backup(target)
    finally:
        target.close()
    return backup_file


def main() -> None:
    if not DATABASE_FILE.exists():
        raise FileNotFoundError(f"数据库不存在：{DATABASE_FILE}")

    connection = sqlite3.connect(str(DATABASE_FILE))
    backup_file = backup_database(connection)

    try:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("BEGIN IMMEDIATE")

        users_sql_row = connection.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type='table' AND name='users'"
        ).fetchone()
        if users_sql_row is None:
            raise RuntimeError("users 表不存在")

        if "'teacher'" not in users_sql_row[0]:
            old_count = connection.execute(
                "SELECT COUNT(*) FROM users"
            ).fetchone()[0]

            connection.execute(
                """
                CREATE TABLE users_new (
                    id VARCHAR(50) NOT NULL PRIMARY KEY,
                    name VARCHAR(100) NOT NULL,
                    role VARCHAR(20) NOT NULL,
                    status VARCHAR(20) NOT NULL,
                    created_at DATETIME NOT NULL
                        DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT ck_users_role
                        CHECK (
                            role IN (
                                'student',
                                'teacher',
                                'admin'
                            )
                        )
                )
                """
            )
            connection.execute(
                """
                INSERT INTO users_new (
                    id, name, role, status, created_at
                )
                SELECT id, name, role, status, created_at
                FROM users
                """
            )
            connection.execute("DROP TABLE users")
            connection.execute("ALTER TABLE users_new RENAME TO users")
            connection.execute(
                "CREATE INDEX ix_users_role ON users (role)"
            )

            new_count = connection.execute(
                "SELECT COUNT(*) FROM users"
            ).fetchone()[0]
            if new_count != old_count:
                raise RuntimeError("用户数量在迁移后发生变化")

            print("users 角色约束已加入 teacher")
        else:
            print("users 已支持 teacher")

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS teacher_course_assignments (
                teacher_id VARCHAR(50) NOT NULL,
                course_id VARCHAR(50) NOT NULL,
                assigned_by VARCHAR(50) NOT NULL,
                assigned_at DATETIME NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (teacher_id, course_id),
                FOREIGN KEY(teacher_id) REFERENCES users (id),
                FOREIGN KEY(course_id) REFERENCES courses (id),
                FOREIGN KEY(assigned_by) REFERENCES users (id)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
                ix_teacher_course_assignments_course_id
            ON teacher_course_assignments (course_id)
            """
        )

        foreign_key_errors = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()
        if foreign_key_errors:
            raise RuntimeError(
                f"外键检查失败：{foreign_key_errors}"
            )

        connection.commit()
        connection.execute("PRAGMA foreign_keys=ON")
        print("teacher_course_assignments 已准备完成")
        print(f"迁移前备份：{backup_file}")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
