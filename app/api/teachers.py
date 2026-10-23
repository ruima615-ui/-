from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import status

from app.api.exam_dependencies import get_current_user
from app.api.exam_dependencies import get_db
from app.schemas.auth import TeacherAccountResponse
from app.schemas.course import CourseResponse
from app.schemas.teacher import TeacherCourseAssignmentResponse
from app.services.teacher_service import assign_teacher_to_course
from app.services.teacher_service import list_teacher_courses
from app.services.teacher_service import approve_teacher_account
from app.services.teacher_service import list_pending_teachers
from app.services.teacher_service import list_active_teachers_and_courses
from app.services.teacher_service import list_teacher_course_assignments, revoke_teacher_course_assignment


router = APIRouter(
    prefix="/teachers",
    tags=["教师"],
)


def call_service(function, **kwargs):
    try:
        return function(**kwargs)
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/assignment-options")
def assignment_options(db=Depends(get_db), current_user=Depends(get_current_user)):
    return call_service(list_active_teachers_and_courses, db=db, admin_id=current_user.id)


@router.get("/assignments")
def assignments(db=Depends(get_db), current_user=Depends(get_current_user)):
    return call_service(list_teacher_course_assignments, db=db, admin_id=current_user.id)


@router.delete("/{teacher_id}/courses/{course_id}", status_code=204)
def revoke_assignment(teacher_id: str, course_id: str, db=Depends(get_db),
                      current_user=Depends(get_current_user)):
    call_service(revoke_teacher_course_assignment, db=db, admin_id=current_user.id,
                 teacher_id=teacher_id, course_id=course_id)


@router.get(
    "/pending",
    response_model=list[TeacherAccountResponse],
)
def pending_teachers(
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    teachers = call_service(
        list_pending_teachers,
        db=db,
        admin_id=current_user.id,
    )
    return [
        TeacherAccountResponse(
            user_id=teacher.id,
            name=teacher.name,
            role=teacher.role,
            status=teacher.status,
        )
        for teacher in teachers
    ]


@router.post(
    "/{teacher_id}/approve",
    response_model=TeacherAccountResponse,
)
def approve_teacher(
    teacher_id: str,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    teacher = call_service(
        approve_teacher_account,
        db=db,
        admin_id=current_user.id,
        teacher_id=teacher_id,
    )
    return TeacherAccountResponse(
        user_id=teacher.id,
        name=teacher.name,
        role=teacher.role,
        status=teacher.status,
    )


@router.post(
    "/{teacher_id}/courses/{course_id}",
    response_model=TeacherCourseAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
)
def assign_course(
    teacher_id: str,
    course_id: str,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    return call_service(
        assign_teacher_to_course,
        db=db,
        admin_id=current_user.id,
        teacher_id=teacher_id,
        course_id=course_id,
    )


@router.get(
    "/me/courses",
    response_model=list[CourseResponse],
)
def my_courses(
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    courses = call_service(
        list_teacher_courses,
        db=db,
        teacher_id=current_user.id,
    )
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
