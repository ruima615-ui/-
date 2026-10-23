"""管理员建立课程的业务入口。"""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.entities import Course, User


def create_course(db, admin_id: str, code: str, name: str, description: str | None = None) -> Course:
    admin = db.get(User, admin_id)
    if admin is None or admin.role != "admin" or admin.status != "active":
        raise PermissionError("只有可用的管理员可以创建课程")
    code, name = code.strip().upper(), name.strip()
    if not code or not name:
        raise ValueError("课程代码和名称不能为空")
    if db.scalar(select(Course.id).where(Course.code == code)) is not None:
        raise ValueError("课程代码已存在")
    course = Course(id=f"COURSE_{uuid4().hex[:16]}", code=code, name=name,
                    description=(description or "").strip() or None, status="draft")
    try:
        db.add(course)
        db.commit()
        db.refresh(course)
    except IntegrityError as error:
        db.rollback()
        raise ValueError("课程代码已存在") from error
    return course


def list_admin_courses(db, admin_id: str) -> list[Course]:
    _require_admin(db, admin_id)
    return db.scalars(select(Course).order_by(Course.created_at.desc())).all()


def publish_course(db, admin_id: str, course_id: str) -> Course:
    _require_admin(db, admin_id)
    course = db.get(Course, course_id)
    if course is None:
        raise ValueError("课程不存在")
    if course.status != "draft":
        raise ValueError("只有草稿课程可以发布")
    course.status = "active"
    db.commit()
    db.refresh(course)
    return course


def _require_admin(db, admin_id: str) -> None:
    admin = db.get(User, admin_id)
    if admin is None or admin.role != "admin" or admin.status != "active":
        raise PermissionError("只有可用的管理员可以管理课程")
