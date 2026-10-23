from pydantic import BaseModel


class CourseResponse(BaseModel):
    """学生可以查看的课程信息。"""

    course_id: str
    code: str
    name: str
    description: str | None
    status: str
#学生选课
from datetime import datetime


class EnrollmentResponse(BaseModel):
    """学生成功选课后的结果。"""

    student_id: str
    course_id: str
    enrolled_at: datetime