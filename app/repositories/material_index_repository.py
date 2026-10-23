from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import CourseMaterial
from app.models.entities import CourseMaterialIndex
from app.models.entities import CourseMaterialEmbeddingIndex


def get_material_index(
    db: Session,
    material_id: str,
) -> CourseMaterialIndex | None:
    return db.get(CourseMaterialIndex, material_id)


def save_material_index(
    db: Session,
    material_index: CourseMaterialIndex,
) -> CourseMaterialIndex:
    db.add(material_index)
    db.flush()
    return material_index


def delete_material_index(
    db: Session,
    material_index: CourseMaterialIndex,
) -> None:
    db.delete(material_index)
    db.flush()


def list_ready_materials(
    db: Session,
    course_id: str | None = None,
) -> list[CourseMaterial]:
    statement = select(CourseMaterial).where(
        CourseMaterial.status == "ready_for_indexing"
    )

    if course_id is not None:
        statement = statement.where(
            CourseMaterial.course_id == course_id
        )

    statement = statement.order_by(
        CourseMaterial.created_at,
        CourseMaterial.id,
    )
    return list(db.scalars(statement).all())


def has_indexed_course_materials(
    db: Session,
    course_id: str,
) -> bool:
    statement = (
        select(CourseMaterialIndex.material_id)
        .where(
            CourseMaterialIndex.course_id == course_id,
            CourseMaterialIndex.status == "indexed",
        )
        .limit(1)
    )
    return db.scalar(statement) is not None


def get_embedding_index(db: Session, material_id: str, backend: str) -> CourseMaterialEmbeddingIndex | None:
    return db.get(CourseMaterialEmbeddingIndex, (material_id, backend))


def list_embedding_indexes(db: Session, material_id: str) -> list[CourseMaterialEmbeddingIndex]:
    return list(db.scalars(select(CourseMaterialEmbeddingIndex).where(
        CourseMaterialEmbeddingIndex.material_id == material_id,
    )).all())


def has_indexed_embedding_materials(db: Session, course_id: str, backend: str) -> bool:
    return db.scalar(
        select(CourseMaterialEmbeddingIndex.material_id).where(
            CourseMaterialEmbeddingIndex.course_id == course_id,
            CourseMaterialEmbeddingIndex.backend == backend,
            CourseMaterialEmbeddingIndex.status == "indexed",
        ).limit(1)
    ) is not None


def has_any_embedding_indexes(db: Session, course_id: str) -> bool:
    return db.scalar(select(CourseMaterialEmbeddingIndex.material_id).where(
        CourseMaterialEmbeddingIndex.course_id == course_id,
    ).limit(1)) is not None


def ready_embedding_material_ids(db: Session, course_id: str, backend: str) -> set[str]:
    return set(db.scalars(select(CourseMaterialEmbeddingIndex.material_id).where(
        CourseMaterialEmbeddingIndex.course_id == course_id,
        CourseMaterialEmbeddingIndex.backend == backend,
        CourseMaterialEmbeddingIndex.status == "indexed",
    )).all())
