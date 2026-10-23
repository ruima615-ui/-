"""给已有 questions 表增加教师难度标注字段。"""

import sqlite3

from app.core.config import DATABASE_FILE


NEW_COLUMNS = (
    "knowledge_count_level",
    "reasoning_level",
    "transfer_level",
    "distractor_level",
    "difficulty_score",
)


def main() -> None:
    if not DATABASE_FILE.exists():
        raise FileNotFoundError(f"数据库不存在：{DATABASE_FILE}")

    connection = sqlite3.connect(str(DATABASE_FILE))
    try:
        connection.execute("BEGIN IMMEDIATE")
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(questions)")
        }
        if not columns:
            raise RuntimeError("questions 表不存在")

        for column in NEW_COLUMNS:
            if column in columns:
                print(f"已存在：questions.{column}")
                continue

            # 列名只来自上方固定列表，不接收外部输入。
            connection.execute(
                f"ALTER TABLE questions ADD COLUMN {column} INTEGER"
            )
            print(f"已增加：questions.{column}")

        final_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(questions)")
        }
        if not set(NEW_COLUMNS).issubset(final_columns):
            raise RuntimeError("难度标注字段检查失败")

        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
