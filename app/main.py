#fastapi服务启动入口
from contextlib import asynccontextmanager
from pathlib import Path
from app.api.auth import router as auth_router
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from app.api.sessions import router as session_router
from app.api.chat import router as chat_router
from app.core.database import create_tables
from app.api.courses import router as course_router
from app.api.teachers import router as teacher_router
from app.api.course_materials import admin_router as official_material_router
from app.api.course_materials import router as course_material_router
from app.api.questions import router as question_router
@asynccontextmanager
#定义启动过程
async def lifespan(app: FastAPI):
    """管理FastAPI启动和关闭过程"""

    # 服务启动时，确保数据库表存在
    create_tables()

    yield

    # yield后面可以放置服务关闭时的清理代码

#创建fastapi应用
app = FastAPI(
    title="CoursePilot API",
    description="智能教学与学情分析Agent后端服务",
    version="0.1.0",
    lifespan=lifespan
)
#注册聊天路由
app.include_router(
    chat_router,
    prefix="/api"
)
#注册路由
app.include_router(
    auth_router,
    prefix="/api"
)
#注册会话路由
app.include_router(
    session_router,
    prefix="/api"
)
#课程接口路由
app.include_router(
    course_router,
    prefix="/api",
)
app.include_router(
    teacher_router,
    prefix="/api",
)
app.include_router(
    course_material_router,
    prefix="/api",
)
app.include_router(question_router)
app.include_router(
    official_material_router,
    prefix="/api",
)
@app.get(
    "/health",
    tags=["系统"]
)
def health():
    """服务健康检查"""

    return {
        "status": "ok",
        "service": "CoursePilot"
    }
#
from app.api.exams import router as exams_router

app.include_router(exams_router)


@app.get("/", include_in_schema=False)
def web_home():
    """独立 Web 前端入口；旧 Streamlit 可在迁移期间继续单独运行。"""
    return RedirectResponse(url="/web/")


WEB_DIR = Path(__file__).resolve().parents[1] / "web"
app.mount("/web", StaticFiles(directory=WEB_DIR, html=True), name="web")
