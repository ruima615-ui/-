"""Session-safe agent execution independent of a specific workflow implementation."""

from dataclasses import dataclass
from typing import Callable

from app.models.entities import ChatSession, Course, Enrollment, User


@dataclass(frozen=True)
class AgentRuntimeHarness:
    session_factory: Callable
    single_agent: object
    load_context: Callable
    save_message: Callable
    run_single: Callable
    run_multi: Callable

    def run(self, *, user_id: str, session_id: str, user_input: str,
            workflow: str = "single", capture_failure_diagnostics: bool = False) -> dict:
        if workflow not in {"single", "multi_agent_review"}:
            raise ValueError("未知的学生 Agent 工作流")
        db = self.session_factory()
        try:
            chat_session = db.get(ChatSession, session_id)
            if chat_session is None:
                raise ValueError(f"会话不存在：{session_id}")
            if chat_session.user_id != user_id:
                raise PermissionError("无权访问该会话")
            if chat_session.status != "active":
                raise PermissionError("当前会话已经关闭，不能继续聊天")

            user = db.get(User, user_id)
            if user is None or user.role != "student" or user.status != "active":
                raise PermissionError("当前用户不是正常状态的学生")
            course_id = chat_session.course_id
            if course_id is None:
                raise ValueError("学生 Agent 会话必须关联课程")
            course = db.get(Course, course_id)
            if course is None or course.status != "active":
                raise ValueError("当前课程不存在或不可用")
            if db.get(Enrollment, (user_id, course_id)) is None:
                raise PermissionError("学生未选修当前会话所属课程")

            if workflow == "single":
                checkpoint = self.single_agent.get_state(
                    {"configurable": {"thread_id": session_id}})
                checkpoint_messages = checkpoint.values.get("messages", []) if checkpoint else []
                messages = [] if checkpoint_messages else list(self.load_context(
                    db=db, user_id=user_id, session_id=session_id, limit=20))
                messages.append({"role": "user", "content": user_input})
                result = self.run_single(messages=messages, db=db, student_id=user_id,
                                         course_id=course_id, session_id=session_id)
            else:
                result = self.run_multi(
                    db=db, student_id=user_id, course_id=course_id, session_id=session_id,
                    capture_failure_diagnostics=capture_failure_diagnostics)

            self.save_message(db=db, user_id=user_id, session_id=session_id,
                              role="user", content=user_input)
            self.save_message(db=db, user_id=user_id, session_id=session_id,
                              role="assistant", content=result["answer"], metadata={
                                  "review_plan": result.get("review_plan"),
                                  "called_tools": result["called_tools"],
                                  "steps": result["steps"],
                                  "tool_trace": result.get("tool_trace", []),
                              })
            return result
        finally:
            db.close()
