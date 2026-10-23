import sqlite3

from app.core.config import DATABASE_FILE


def get_question_columns(
    connection: sqlite3.Connection,
) -> set[str]:
    """读取 questions 表当前包含的字段。"""

    rows = connection.execute(
        "PRAGMA table_info(questions)"
    ).fetchall()

    return {
        row[1]
        for row in rows
    }


def main():
    if not DATABASE_FILE.exists():
        raise FileNotFoundError(
            f"数据库不存在：{DATABASE_FILE}"
        )

    connection = sqlite3.connect(
        str(DATABASE_FILE)
    )#存在进行数据库连接

    try:
        columns = get_question_columns(
            connection
        )

        if not columns:
            raise RuntimeError(
                "questions 表不存在，不能执行迁移"
            )

        if "difficulty" not in columns:
            connection.execute(
                """
                ALTER TABLE questions
                ADD COLUMN difficulty VARCHAR(20)
                NOT NULL DEFAULT 'medium'
                """
            )
            print(
                "已增加 questions.difficulty"
            )
        else:
            print(
                "questions.difficulty 已存在"
            )

        columns = get_question_columns(
            connection
        )

        connection.commit()

        final_columns = get_question_columns(
            connection
        )

        required_columns = {
            "difficulty",
        }

        if not required_columns.issubset(
            final_columns
        ):
            raise RuntimeError(
                "迁移后字段检查失败"
            )

        print("V2-A1 数据库迁移完成")

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


if __name__ == "__main__":
    main()