from datetime import datetime

from pydantic import BaseModel


class TeacherCourseAssignmentResponse(BaseModel):
    teacher_id: str
    course_id: str
    assigned_by: str
    assigned_at: datetime
