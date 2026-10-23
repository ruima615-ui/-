from datetime import datetime

from pydantic import BaseModel
from pydantic import Field

from app.schemas.review_plan import ReviewPlanResponse
class MessageResponse(BaseModel):
    """一条历史消息的响应格式"""

    message_id: int
    session_id: str
    role: str
    content: str
    called_tools: list[str] = Field(
        default_factory=list,
    )
    steps: int | None = None
    review_plan: ReviewPlanResponse | None = None
    created_at: datetime#创建时间
class SessionMessagesResponse(BaseModel):
    """一段会话的历史消息响应格式"""

    session_id: str
    count: int#这次接口一共返回多少条历史消息
    messages: list[MessageResponse]#返回的具体消息列表
