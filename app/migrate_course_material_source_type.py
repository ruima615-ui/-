from sqlalchemy import inspect
from sqlalchemy import text

from app.core.database import engine


def migrate_course_material_source_type() -> None:
    """为已有 course_materials 表补充后端控制的资料来源字段。"""

    inspector = inspect(engine)
    if "course_materials" not in inspector.get_table_names():
        raise RuntimeError("course_materials 表不存在，请先创建数据库表")

    column_names = {
        column["name"]
        for column in inspector.get_columns("course_materials")
    }

    with engine.begin() as connection:
        if "source_type" not in column_names:
            connection.execute(text(
                "ALTER TABLE course_materials "
                "ADD COLUMN source_type VARCHAR(20) "
                "NOT NULL DEFAULT 'teacher'"
            ))

        if "topic" not in column_names:
            connection.execute(text(
                "ALTER TABLE course_materials "
                "ADD COLUMN topic VARCHAR(100) "
                "NOT NULL DEFAULT '通用'"
            ))
            connection.execute(text(
                "UPDATE course_materials "
                "SET topic = title"
            ))

        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS "
            "ix_course_materials_source_type "
            "ON course_materials (source_type)"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS "
            "ix_course_materials_topic "
            "ON course_materials (topic)"
        ))


if __name__ == "__main__":
    migrate_course_material_source_type()
    print("course_materials.source_type 迁移完成")
