# 主程序.py
# 学习助手的终端启动入口,程序启动时准备当前用户和会话，循环接受问题，调用带记忆的Agent
#导入依赖
from agent_runner import run_agent_with_memory

from app.core.database import SessionLocal
from app.models.entities import User
from app.repositories.conversation_repository import get_chat_session
from app.services.memory_service import create_memory_session
# 当前是终端开发版本，暂时使用固定用户和固定会话
DEMO_USER_ID = "S001"
DEMO_SESSION_ID = "SESSION_S001"


def prepare_demo_session():
    """准备终端演示需要的用户和会话，即数据库链接"""

    db = SessionLocal()

    try:
        # 1. 查询演示学生是否存在
        user = db.get(
            User,
            DEMO_USER_ID
        )

        # 2. 如果不存在，就创建演示学生
        if user is None:
            user = User(
                id=DEMO_USER_ID,
                name="张三",
                role="student"
            )

            db.add(user)
            db.commit()

            print("已创建演示学生：张三")

        # 3. 查询固定会话是否存在
        session = get_chat_session(
            db=db,
            session_id=DEMO_SESSION_ID
        )

        # 4. 如果不存在，就创建新会话
        if session is None:
            create_memory_session(
                db=db,
                session_id=DEMO_SESSION_ID,
                user_id=DEMO_USER_ID,
                course_id=None,
                title="终端学习对话"
            )

            print("已创建演示会话：", DEMO_SESSION_ID)

    finally:
        db.close()


def main():
    """启动带双层记忆的终端对话"""

    # 程序启动时，确保用户和会话已经存在
    prepare_demo_session()

    print("学习助手已经启动，输入“退出”结束对话。")

    while True:
        user_input = input("你：")

        if user_input == "退出":
            print("对话结束")
            break

        if not user_input.strip():
            continue

        # 运行带Redis和SQLite记忆的Agent
        result = run_agent_with_memory(
            user_id=DEMO_USER_ID,
            session_id=DEMO_SESSION_ID,
            user_input=user_input
        )

        print("助手：", result["answer"])


if __name__ == "__main__":
    main()