#创建聊天接口,http接口层
#负责将前端发来的json转交给agent,
#再把agent结果转换成http响应
from fastapi import APIRouter
from fastapi import HTTPException

from agent_runner import run_agent_with_memory
from app.schemas.chat import ChatRequest
from app.schemas.chat import ChatResponse
from fastapi import Depends
from app.api.exam_dependencies import get_current_user
#创建一个接口路由器,APIrouter是一个专门收集接口的对象
router=APIRouter(
    tags=["聊天"]
)
#注册post接口，告诉fastapi请求方法：post（提交聊天信息）
@router.post(
    "/chat",#请求地址
    response_model=ChatResponse#返回格式
)
def chat(request:ChatRequest, current_user=Depends(get_current_user),):
    """接收当前登录学生的问题并运行 Agent。"""

    if current_user.role != "student":
        raise HTTPException(
            status_code=403,
            detail="只有学生可以使用学习助手",
        )

    try:
        result = run_agent_with_memory(
            user_id=current_user.id,
            session_id=request.session_id,
            user_input=request.message,
        )

        return ChatResponse(
            answer=result["answer"],
            called_tools=result["called_tools"],
            steps=result["steps"],
            review_plan=result.get("review_plan"),
        )

    except PermissionError as error:
        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    except ValueError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        ) from error

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail="Agent执行失败",
        ) from error


@router.post("/chat/review-plan-multi", response_model=ChatResponse)
def multi_agent_review_chat(request: ChatRequest, current_user=Depends(get_current_user)):
    """Explicit opt-in for the bounded Coordinator → diagnosis → plan graph."""
    if current_user.role != "student":
        raise HTTPException(status_code=403, detail="只有学生可以使用学习助手")
    try:
        result = run_agent_with_memory(
            user_id=current_user.id, session_id=request.session_id,
            user_input=request.message, workflow="multi_agent_review",
        )
        return ChatResponse(
            answer=result["answer"], called_tools=result["called_tools"],
            steps=result["steps"], review_plan=result["review_plan"],
        )
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=500, detail="Agent执行失败") from error
 
