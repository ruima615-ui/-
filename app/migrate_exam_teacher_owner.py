"""给历史 exams 表增加创建教师字段。"""

import sqlite3

from app.core.config import DATABASE_FILE


def main() -> None:
    if not DATABASE_FILE.exists():
        raise FileNotFoundError(f"数据库不存在：{DATABASE_FILE}")

    connection = sqlite3.connect(str(DATABASE_FILE))
    try:
        connection.execute("BEGIN IMMEDIATE")
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(exams)")
        }
        if not columns:
            raise RuntimeError("exams 表不存在")

        if "created_by" not in columns:
            connection.execute(
                """
                ALTER TABLE exams
                ADD COLUMN created_by VARCHAR(50)
                    REFERENCES users(id)
                """
            )
            print("已增加 exams.created_by")
        else:
            print("exams.created_by 已存在")

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_exams_created_by
            ON exams (created_by)
            """
        )

        foreign_key_errors = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()
        if foreign_key_errors:
            raise RuntimeError(f"外键检查失败：{foreign_key_errors}")

        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
