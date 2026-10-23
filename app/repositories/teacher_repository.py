from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Course
from app.models.entities import TeacherCourseAssignment
from app.models.entities import User


def get_teacher_course_assignment(
    db: Session,
    teacher_id: str,
    course_id: str,
):
    return db.get(
        TeacherCourseAssignment,
        (teacher_id, course_id),
    )


def add_teacher_course_assignment(
    db: Session,
    assignment: TeacherCourseAssignment,
):
    db.add(assignment)
    db.flush()
    return assignment


def get_teacher_courses(
    db: Session,
    teacher_id: str,
) -> list[Course]:
    statement = (
        select(Course)
        .join(
            TeacherCourseAssignment,
            TeacherCourseAssignment.course_id == Course.id,
        )
        .where(
            TeacherCourseAssignment.teacher_id == teacher_id,
            Course.status == "active",
        )
        .order_by(Course.code)
    )
    return list(db.scalars(statement).all())


def get_teachers_by_status(
    db: Session,
    status: str,
) -> list[User]:
    statement = (
        select(User)
        .where(
            User.role == "teacher",
            User.status == status,
        )
        .order_by(User.created_at, User.id)
    )
    return list(db.scalars(statement).all())
