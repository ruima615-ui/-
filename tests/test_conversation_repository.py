"""测试SQLite长期对话记忆"""

from sqlalchemy import delete

from app.core.database import SessionLocal
from app.models.entities import ChatMessage
from app.models.entities import ChatSession
from app.models.entities import Course
from app.models.entities import Enrollment
from app.models.entities import User
from app.repositories.conversation_repository import add_chat_message
from app.repositories.conversation_repository import create_chat_session
from app.repositories.conversation_repository import get_chat_session
from app.repositories.conversation_repository import get_recent_chat_messages


TEST_USER_ID = "TEST_STUDENT_001"
TEST_COURSE_ID = "TEST_COURSE_001"
TEST_SESSION_ID = "TEST_SESSION_001"


def clear_old_test_data(db):
    """清理上一次运行产生的测试数据"""

    # 必须先删除子表数据，再删除父表数据
    delete_messages = delete(ChatMessage).where(
        ChatMessage.session_id == TEST_SESSION_ID
    )
    db.execute(delete_messages)

    delete_session = delete(ChatSession).where(
        ChatSession.id == TEST_SESSION_ID
    )
    db.execute(delete_session)

    delete_enrollment = delete(Enrollment).where(
        Enrollment.student_id == TEST_USER_ID,
        Enrollment.course_id == TEST_COURSE_ID
    )
    db.execute(delete_enrollment)

    delete_course = delete(Course).where(
        Course.id == TEST_COURSE_ID
    )
    db.execute(delete_course)

    delete_user = delete(User).where(
        User.id == TEST_USER_ID
    )
    db.execute(delete_user)

    db.commit()


def run_test():
    """运行长期记忆测试"""

    db = SessionLocal()

    try:
        # 第一步：清理以前的测试数据
        clear_old_test_data(db)

        # 第二步：创建测试学生
        student = User(
            id=TEST_USER_ID,
            name="测试学生",
            role="student"
        )

        # 第三步：创建测试课程
        course = Course(
            id=TEST_COURSE_ID,
            code="TEST101",
            name="Python测试课程",
            description="用于测试长期记忆"
        )

        db.add(student)
        db.add(course)
        db.commit()

        print("学生和课程创建成功")

        # 第四步：建立学生与课程的关系
        enrollment = Enrollment(
            student_id=TEST_USER_ID,
            course_id=TEST_COURSE_ID
        )

        db.add(enrollment)
        db.commit()

        print("选课关系创建成功")

        # 第五步：创建一段对话
        session = create_chat_session(
            db=db,
            session_id=TEST_SESSION_ID,
            user_id=TEST_USER_ID,
            course_id=TEST_COURSE_ID,
            title="Python列表学习"
        )

        print("会话创建成功：", session.id)

        # 第六步：检查会话能否被查询
        saved_session = get_chat_session(
            db=db,
            session_id=TEST_SESSION_ID
        )

        assert saved_session is not None
        assert saved_session.user_id == TEST_USER_ID
        assert saved_session.course_id == TEST_COURSE_ID

        # 第七步：保存用户消息
        add_chat_message(
            db=db,
            session_id=TEST_SESSION_ID,
            role="user",
            content="为什么Python列表索引从0开始？"
        )

        # 第八步：保存助手消息
        add_chat_message(
            db=db,
            session_id=TEST_SESSION_ID,
            role="assistant",
            content="因为Python使用从0开始的索引规则。"
        )

        print("两条长期消息保存成功")

        # 第九步：从SQLite读取消息
        messages = get_recent_chat_messages(
            db=db,
            session_id=TEST_SESSION_ID,
            limit=20
        )

        print("读取到的消息数量：", len(messages))

        for message in messages:
            print(
                f"消息编号={message.id}，"
                f"角色={message.role}，"
                f"内容={message.content}"
            )

        # 第十步：自动判断测试是否正确
        assert len(messages) == 2
        assert messages[0].role == "user"
        assert messages[1].role == "assistant"
        assert messages[0].content == "为什么Python列表索引从0开始？"

        print("SQLite长期记忆测试通过")

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    run_test()