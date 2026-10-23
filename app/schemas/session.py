"""规定创建会话时请求和响应的数据格式"""
from datetime import datetime

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


class CreateSessionRequest(BaseModel):
    """创建学生课程学习会话时提交的数据。"""

    model_config = ConfigDict(
        extra="forbid",
    )

    course_id: str = Field(
        min_length=1,
        description="本次学习对话所属的课程编号",
    )

    title: str | None = Field(
        default=None,
        max_length=200,
        description="会话标题",
    )


class SessionResponse(BaseModel):
    """创建成功后返回的会话信息。"""

    session_id: str
    user_id: str
    course_id: str | None
    title: str | None
    status: str
    created_at: datetime