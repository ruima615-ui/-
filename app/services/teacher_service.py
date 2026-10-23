from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.core.security import hash_password
from app.models.entities import Course
from app.models.entities import TeacherCourseAssignment
from app.models.entities import User
from app.repositories.auth_repository import create_user_account
from app.repositories.auth_repository import get_user_by_id
from app.repositories.teacher_repository import add_teacher_course_assignment
from app.repositories.teacher_repository import get_teacher_course_assignment
from app.repositories.teacher_repository import get_teacher_courses
from app.repositories.teacher_repository import get_teachers_by_status


def _require_active_admin(
    db: Session,
    admin_id: str,
) -> User:
    admin = db.get(User, admin_id)
    if (
        admin is None
        or admin.role != "admin"
        or admin.status != "active"
    ):
        raise PermissionError("只有可用的管理员可以执行此操作")
    return admin


def register_teacher_account(
    db: Session,
    user_id: str,
    name: str,
    plain_password: str,
) -> User:
    """教师自助注册，账号等待管理员审核。"""

    if get_user_by_id(db, user_id) is not None:
        raise ValueError(f"用户编号已经存在：{user_id}")

    try:
        return create_user_account(
            db=db,
            user_id=user_id,
            name=name,
            password_hash=hash_password(plain_password),
            role="teacher",
            status="pending",
        )
    except IntegrityError as error:
        raise ValueError(f"用户编号已经存在：{user_id}") from error


def list_pending_teachers(
    db: Session,
    admin_id: str,
) -> list[User]:
    _require_active_admin(db, admin_id)
    return get_teachers_by_status(db, "pending")


def list_active_teachers_and_courses(db: Session, admin_id: str) -> dict:
    """管理员分配课程时可选的真实教师和课程。"""
    _require_active_admin(db, admin_id)
    teachers = db.scalars(select(User).where(
        User.role == "teacher", User.status == "active"
    ).order_by(User.id)).all()
    courses = db.scalars(select(Course).where(
        Course.status == "active"
    ).order_by(Course.code)).all()
    return {
        "teachers": [{"user_id": teacher.id, "name": teacher.name} for teacher in teachers],
        "courses": [{"course_id": course.id, "code": course.code, "name": course.name} for course in courses],
    }


def list_teacher_course_assignments(db: Session, admin_id: str) -> list[dict]:
    _require_active_admin(db, admin_id)
    rows = db.execute(
        select(TeacherCourseAssignment, User, Course)
        .join(User, User.id == TeacherCourseAssignment.teacher_id)
        .join(Course, Course.id == TeacherCourseAssignment.course_id)
        .order_by(Course.code, User.id)
    ).all()
    return [{"teacher_id": teacher.id, "teacher_name": teacher.name,
             "course_id": course.id, "course_name": course.name,
             "course_code": course.code, "assigned_at": assignment.assigned_at}
            for assignment, teacher, course in rows]


def revoke_teacher_course_assignment(db: Session, admin_id: str,
                                     teacher_id: str, course_id: str) -> None:
    _require_active_admin(db, admin_id)
    assignment = db.get(TeacherCourseAssignment, (teacher_id, course_id))
    if assignment is None:
        raise ValueError("教师课程授权不存在")
    db.delete(assignment)
    db.commit()


def approve_teacher_account(
    db: Session,
    admin_id: str,
    teacher_id: str,
) -> User:
    """管理员批准一个待审核教师账号。"""

    _require_active_admin(db, admin_id)

    teacher = db.get(User, teacher_id)
    if teacher is None or teacher.role != "teacher":
        raise ValueError("教师账号不存在")
    if teacher.status == "active":
        raise ValueError("教师账号已经通过审核")
    if teacher.status != "pending":
        raise ValueError("当前教师账号不能通过审核")

    try:
        teacher.status = "active"
        db.commit()
        db.refresh(teacher)
        return teacher
    except Exception:
        db.rollback()
        raise


def assign_teacher_to_course(
    db: Session,
    admin_id: str,
    teacher_id: str,
    course_id: str,
) -> TeacherCourseAssignment:
    """管理员授权一名教师负责一门课程。"""

    _require_active_admin(db, admin_id)

    teacher = db.get(User, teacher_id)
    if (
        teacher is None
        or teacher.role != "teacher"
        or teacher.status != "active"
    ):
        raise ValueError("教师不存在或账号不可用")

    course = db.get(Course, course_id)
    if course is None or course.status != "active":
        raise ValueError("课程不存在或不可用")

    if get_teacher_course_assignment(db, teacher_id, course_id):
        raise ValueError("该教师已经负责这门课程")

    assignment = TeacherCourseAssignment(
        teacher_id=teacher_id,
        course_id=course_id,
        assigned_by=admin_id,
    )

    try:
        add_teacher_course_assignment(db, assignment)
        db.commit()
        db.refresh(assignment)
        return assignment
    except Exception:
        db.rollback()
        raise


def list_teacher_courses(
    db: Session,
    teacher_id: str,
) -> list[Course]:
    """读取当前教师被授权管理的有效课程。"""

    teacher = db.get(User, teacher_id)
    if (
        teacher is None
        or teacher.role != "teacher"
        or teacher.status != "active"
    ):
        raise PermissionError("当前用户不是可用的教师")

    return get_teacher_courses(db, teacher_id)


def require_teacher_course_access(
    db: Session,
    teacher_id: str,
    course_id: str,
) -> Course:
    """校验教师是否有权管理指定课程，并返回该课程。"""

    teacher = db.get(User, teacher_id)
    if (
        teacher is None
        or teacher.role != "teacher"
        or teacher.status != "active"
    ):
        raise PermissionError("当前用户不是可用的教师")

    course = db.get(Course, course_id)
    if course is None or course.status != "active":
        raise ValueError("课程不存在或不可用")

    assignment = get_teacher_course_assignment(
        db,
        teacher_id,
        course_id,
    )
    if assignment is None:
        raise PermissionError("当前教师无权管理这门课程")

    return course
