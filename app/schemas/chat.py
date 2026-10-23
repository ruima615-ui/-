from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from app.schemas.review_plan import ReviewPlanResponse


class ChatRequest(BaseModel):
    """学生发送给 Agent 的消息。"""

    model_config = ConfigDict(
        extra="forbid",
    )

    session_id: str = Field(
        min_length=1,
        description="当前 Agent 会话编号",
    )

    message: str = Field(
        min_length=1,
        description="用户本轮输入",
    )


class ChatResponse(BaseModel):
    """Agent 返回的回答。"""

    answer: str
    called_tools: list[str]
    steps: int
    review_plan: ReviewPlanResponse | None = None
