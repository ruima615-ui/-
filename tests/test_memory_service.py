"""测试Redis和SQLite组成的双层记忆"""

import uuid

from app.core.database import SessionLocal
from app.models.entities import Course
from app.models.entities import Enrollment
from app.models.entities import User
from app.repositories.conversation_repository import add_chat_message
from app.services.memory_service import create_memory_session
from app.services.memory_service import load_context
from app.services.memory_service import save_message


def run_test():
    """运行双层记忆测试"""

    # 每次生成新的编号，避免和以前的测试数据重复
    suffix = uuid.uuid4().hex[:8]

    user_id = f"TEST_USER_{suffix}"
    course_id = f"TEST_COURSE_{suffix}"
    session_id = f"TEST_SESSION_{suffix}"

    db = SessionLocal()

    try:
        # 1. 创建测试学生
        student = User(
            id=user_id,
            name="双层记忆测试学生",
            role="student"
        )

        # 2. 创建测试课程
        course = Course(
            id=course_id,
            code=f"MEMORY_{suffix}",
            name="双层记忆测试课程"
        )

        db.add_all([
            student,
            course
        ])
        db.commit()

        # 3. 创建选课关系
        enrollment = Enrollment(
            student_id=user_id,
            course_id=course_id
        )

        db.add(enrollment)
        db.commit()

        # 4. 创建一段新会话
        create_memory_session(
            db=db,
            session_id=session_id,
            user_id=user_id,
            course_id=course_id,
            title="双层记忆测试"
        )

        # 5. 故意只向SQLite写入消息
        # 用于模拟Redis缓存为空的情况
        add_chat_message(
            db=db,
            session_id=session_id,
            role="user",
            content="什么是Python列表？"
        )

        add_chat_message(
            db=db,
            session_id=session_id,
            role="assistant",
            content="Python列表是一种可以保存多个元素的数据结构。"
        )

        print("\n第一次读取：")

        first_context = load_context(
            db=db,
            user_id=user_id,
            session_id=session_id,
            limit=20
        )

        print("第一次读取结果：", first_context)

        assert len(first_context) == 2
        assert first_context[0]["role"] == "user"
        assert first_context[1]["role"] == "assistant"

        print("\n第二次读取：")

        second_context = load_context(
            db=db,
            user_id=user_id,
            session_id=session_id,
            limit=20
        )

        print("第二次读取结果：", second_context)

        assert second_context == first_context

        # 6. 使用统一服务保存第三条消息
        save_message(
            db=db,
            user_id=user_id,
            session_id=session_id,
            role="user",
            content="列表索引为什么从0开始？"
        )

        third_context = load_context(
            db=db,
            user_id=user_id,
            session_id=session_id,
            limit=20
        )

        assert len(third_context) == 3
        assert third_context[-1]["content"] == "列表索引为什么从0开始？"

        print("\n双层记忆测试通过")

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    run_test()