"""把项目内 PYTHON101 示例资料导入正式资料流水线并建立向量索引。"""

from pathlib import Path

from sqlalchemy import select

from app.core.config import BASE_DIR
from app.core.database import SessionLocal
from app.models.entities import CourseMaterial
from app.services.course_material_service import (
    create_official_course_material,
)
from app.services.material_index_service import (
    index_course_material,
)


COURSE_ID = "PYTHON101"
ADMIN_ID = "DEMO_ADMIN_001"
DEMO_MATERIALS = (
    (
        "python_list.md",
        "Python 列表课程资料",
        "Python列表",
    ),
    (
        "function_return.md",
        "Python 函数返回值课程资料",
        "函数返回值",
    ),
)


def get_existing_material(
    db,
    *,
    filename: str,
    topic: str,
) -> CourseMaterial | None:
    return db.scalar(select(CourseMaterial).where(
        CourseMaterial.course_id == COURSE_ID,
        CourseMaterial.original_filename == filename,
        CourseMaterial.topic == topic,
        CourseMaterial.source_type == "official",
    ))


def main() -> None:
    knowledge_dir = BASE_DIR / "knowledge" / COURSE_ID
    db = SessionLocal()
    try:
        for filename, title, topic in DEMO_MATERIALS:
            source_path = knowledge_dir / filename
            if not source_path.is_file():
                raise FileNotFoundError(source_path)

            material = get_existing_material(
                db,
                filename=filename,
                topic=topic,
            )
            if material is None:
                material = create_official_course_material(
                    db=db,
                    admin_id=ADMIN_ID,
                    course_id=COURSE_ID,
                    filename=filename,
                    mime_type="text/markdown",
                    data=source_path.read_bytes(),
                    title=title,
                    topic=topic,
                )

            result = index_course_material(
                db=db,
                material_id=material.id,
            )
            print(
                f"{topic}: {result['status']} "
                f"({result['chunk_count']} chunks)"
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
