import sqlite3

from langgraph.checkpoint.sqlite import (
    SqliteSaver,
)

from app.core.config import (
    AGENT_CHECKPOINT_FILE,
)
# 创建进程运行期间持续存在的 SQLite 连接。
checkpoint_connection = sqlite3.connect(
    str(AGENT_CHECKPOINT_FILE),
    check_same_thread=False,
)


# SqliteSaver 负责读写 LangGraph checkpoint。
student_agent_checkpointer = SqliteSaver(
    checkpoint_connection,)

# 创建 LangGraph 所需的数据表。
student_agent_checkpointer.setup()