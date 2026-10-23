from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import CourseMaterial


def add_course_material(
    db: Session,
    material: CourseMaterial,
) -> CourseMaterial:
    db.add(material)
    db.flush()
    return material


def get_course_material(
    db: Session,
    material_id: str,
) -> CourseMaterial | None:
    return db.get(CourseMaterial, material_id)


def list_course_materials(
    db: Session,
    course_id: str,
) -> list[CourseMaterial]:
    statement = (
        select(CourseMaterial)
        .where(CourseMaterial.course_id == course_id)
        .order_by(
            CourseMaterial.created_at.desc(),
            CourseMaterial.id,
        )
    )
    return list(db.scalars(statement).all())


def delete_course_material(
    db: Session,
    material: CourseMaterial,
) -> None:
    db.delete(material)
    db.flush()
