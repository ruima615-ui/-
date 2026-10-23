#课程接口
from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy import select
from pydantic import BaseModel, Field

from app.api.exam_dependencies import get_current_user
from app.api.exam_dependencies import get_db
from app.models.entities import Course
from app.schemas.course import CourseResponse
from app.models.entities import Enrollment
from app.schemas.course import EnrollmentResponse
from app.services.course_service import create_course, list_admin_courses, publish_course

router = APIRouter(
    prefix="/courses",
    tags=["课程"],
)


class CreateCourseRequest(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None


@router.post("", response_model=CourseResponse, status_code=201)
def create_admin_course(body: CreateCourseRequest, db=Depends(get_db),
                        current_user=Depends(get_current_user)):
    try:
        course = create_course(db, current_user.id, body.code, body.name, body.description)
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return CourseResponse(course_id=course.id, code=course.code, name=course.name,
                          description=course.description, status=course.status)


@router.get("/admin", response_model=list[CourseResponse])
def admin_courses(db=Depends(get_db), current_user=Depends(get_current_user)):
    try:
        return [CourseResponse(course_id=course.id, code=course.code, name=course.name,
                               description=course.description, status=course.status)
                for course in list_admin_courses(db, current_user.id)]
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


@router.post("/admin/{course_id}/publish", response_model=CourseResponse)
def publish_admin_course(course_id: str, db=Depends(get_db),
                         current_user=Depends(get_current_user)):
    try:
        course = publish_course(db, current_user.id, course_id)
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return CourseResponse(course_id=course.id, code=course.code, name=course.name,
                          description=course.description, status=course.status)

@router.get(
    "",
    response_model=list[CourseResponse],
)
def list_available_courses(
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """查询当前可以选择的课程。"""

    if current_user.role != "student":
        raise HTTPException(
            status_code=403,
            detail="只有学生可以查看可选课程",
        )

    statement = (
        select(Course)
        .where(Course.status == "active")
        .order_by(Course.code)
    )

    courses = db.scalars(statement).all()

    return [
        CourseResponse(
            course_id=course.id,
            code=course.code,
            name=course.name,
            description=course.description,
            status=course.status,
        )
        for course in courses
    ]
@router.get(
    "/mine",
    response_model=list[CourseResponse],
)
def list_my_courses(
    db=Depends(get_db),#数据库依赖，fastapi先验证JWT，然后将当前用户和数据库连接交给函数
    current_user=Depends(get_current_user),#身份依赖
):
    """查询当前登录学生已经选择的有效课程。"""

    if current_user.role != "student":
        raise HTTPException(
            status_code=403,
            detail="只有学生可以查看自己的课程",
        )

    statement = (
        select(Course)
        .join(
            Enrollment,
            Enrollment.course_id == Course.id,
        )
        .where(
            Enrollment.student_id == current_user.id,
            Course.status == "active",
        )
        .order_by(Course.code)
    )

    courses = db.scalars(statement).all()

    return [
        CourseResponse(
            course_id=course.id,
            code=course.code,
            name=course.name,
            description=course.description,
            status=course.status,
        )
        for course in courses
    ]
@router.post(
    "/{course_id}/enroll",
    response_model=EnrollmentResponse,
    status_code=201,
)
def enroll_course(
    course_id: str,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """当前登录学生选择一门课程。"""

    if current_user.role != "student":
        raise HTTPException(
            status_code=403,
            detail="只有学生可以选择课程",
        )

    course = db.get(Course, course_id)

    if course is None:
        raise HTTPException(
            status_code=404,
            detail=f"课程不存在：{course_id}",
        )

    if course.status != "active":
        raise HTTPException(
            status_code=403,
            detail="当前课程不可选择",
        )

    existing_enrollment = db.get(
        Enrollment,
        (current_user.id, course_id),
    )

    if existing_enrollment is not None:
        raise HTTPException(
            status_code=409,
            detail="你已经选择了这门课程",
        )

    enrollment = Enrollment(
        student_id=current_user.id,
        course_id=course_id,
    )

    try:
        db.add(enrollment)
        db.commit()
        db.refresh(enrollment)
    except Exception:
        db.rollback()
        raise

    return EnrollmentResponse(
        student_id=enrollment.student_id,
        course_id=enrollment.course_id,
        enrolled_at=enrollment.enrolled_at,
    )
