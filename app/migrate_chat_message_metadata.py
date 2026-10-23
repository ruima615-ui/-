from sqlalchemy import inspect
from sqlalchemy import text

from app.core.database import engine


def migrate_chat_message_metadata() -> None:
    """为历史消息增加可选结构化元数据，不改动已有聊天内容。"""

    inspector = inspect(engine)
    if "chat_messages" not in inspector.get_table_names():
        raise RuntimeError("chat_messages 表不存在")

    column_names = {
        column["name"]
        for column in inspector.get_columns("chat_messages")
    }
    if "metadata_json" in column_names:
        return

    with engine.begin() as connection:
        connection.execute(text(
            "ALTER TABLE chat_messages "
            "ADD COLUMN metadata_json TEXT"
        ))


if __name__ == "__main__":
    migrate_chat_message_metadata()
    print("chat_messages.metadata_json 迁移完成")
