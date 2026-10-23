import os
from pathlib import Path

from dotenv import load_dotenv
#读取env,apikey,ollama地址，数据库地址，embedding模型，最大agent轮数
# config.py位于：
# agentproject/app/core/config.py
#
# parents[0]是core
# parents[1]是app
# parents[2]是agentproject
BASE_DIR = Path(__file__).resolve().parents[2]
# 明确读取项目根目录中的.env
ENV_FILE = BASE_DIR / ".env"
load_dotenv(ENV_FILE)
# 数据文件夹
DATA_DIR = BASE_DIR / "data"

# 如果data文件夹不存在，就自动创建
DATA_DIR.mkdir(
    parents=True,
    exist_ok=True
)

# 教师上传的课程原始资料和解析文本保存目录。
COURSE_MATERIAL_DIR = DATA_DIR / "course_materials"
COURSE_MATERIAL_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

# Chroma 课程资料向量数据库目录。
COURSE_VECTOR_DIR = DATA_DIR / "course_vectors"
COURSE_VECTOR_DIR.mkdir(
    parents=True,
    exist_ok=True,
)
# SQLite数据库文件
DATABASE_FILE = DATA_DIR / "education.db"
#langgraph状态数据库：agent消息状态和执行位置
AGENT_CHECKPOINT_FILE=(
    DATA_DIR / "agent_checkpoints.db"
)
# SQLAlchemy使用的SQLite连接地址
DATABASE_URL = (
    f"sqlite:///{DATABASE_FILE.as_posix()}"
)

# Redis连接地址
REDIS_URL = os.getenv(
    "REDIS_URL",
    "redis://127.0.0.1:6379/0"
)
# 短期对话记忆保存时间，默认24小时
SESSION_TTL_SECONDS = int(
    os.getenv(
        "SESSION_TTL_SECONDS",
        "86400"
    )
)
# Agent临时运行状态保存时间，默认1小时
AGENT_STATE_TTL_SECONDS = int(
    os.getenv(
        "AGENT_STATE_TTL_SECONDS",
        "3600"
    )
)
# 每次最多加载多少条历史消息
MAX_CONTEXT_MESSAGES = int(
    os.getenv(
        "MAX_CONTEXT_MESSAGES",
        "20"
    )
)

# DeepSeek API Key
DEEPSEEK_API_KEY = os.getenv(
    "DEEPSEEK_API_KEY"
)
#补充JWT配置
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")

JWT_ALGORITHM = os.getenv(
    "JWT_ALGORITHM",
    "HS256"
)

ACCESS_TOKEN_EXPIRE_MINUTES = int(
    os.getenv(
        "ACCESS_TOKEN_EXPIRE_MINUTES",
        "60"
    )
)

if not JWT_SECRET_KEY:
    raise ValueError(
        "没有读取到JWT_SECRET_KEY，请检查.env文件"
    )
