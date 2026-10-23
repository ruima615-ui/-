"""教师组卷发布到学生 Agent 读取错题的完整离线业务回归。"""

import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import agent_runner
from app.api import exam_dependencies
from app.core.database import Base
from app.core.security import hash_password
from app.main import app
from app.models.entities import (
    ChatMessage, ChatSession, Course, Enrollment, Question,
    TeacherCourseAssignment, User, UserCredential, WrongQuestion,
)
from app.services import memory_service
from student_agent import build_student_agent


class EvidenceAwareModel(FakeMessagesListChatModel):
    """只替代模型决策；工具、接口、数据库仍运行项目真实代码。"""

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        results = [message for message in messages if isinstance(message, ToolMessage)]
        if not results:
            answer = AIMessage(content="", tool_calls=[{
                "name": "get_current_course_wrong_questions",
                "args": {}, "id": "lookup-wrong",
            }])
        elif len(results) == 1:
            wrong = json.loads(results[0].text)
            assert wrong["course_id"] == "COURSE_AGENT_FLOW"
            assert wrong["wrong_questions"][0]["question_id"] == "Q_AGENT_FLOW"
            answer = AIMessage(content="", tool_calls=[{
                "name": "analyze_current_course_wrong_questions",
                "args": {}, "id": "analyze-weakness",
            }])
        else:
            wrong = json.loads(results[0].text)
            analysis = json.loads(results[1].text)
            question = wrong["wrong_questions"][0]
            assert analysis["priority_topic"] == question["topic"]
            answer = AIMessage(content=(
                f"你在 {question['topic']} 的题目 {question['question_id']} 答错了；"
                f"正确答案是 {question['correct_answer']}。"
                "建议先复习列表索引，再做同类题。"
            ))
        return ChatResult(generations=[ChatGeneration(message=answer)])


class ExamToStudentAgentFlowTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.password = "FlowTest-Password-123"
        with self.Session() as db:
            db.add_all([
                User(id="A_AGENT_FLOW", name="管理员", role="admin", status="active"),
                User(id="T_AGENT_FLOW", name="授课教师", role="teacher", status="active"),
                User(id="T_OTHER_FLOW", name="其他教师", role="teacher", status="active"),
                User(id="S_AGENT_FLOW", name="学生", role="student", status="active"),
                User(id="S_OTHER_FLOW", name="其他学生", role="student", status="active"),
                Course(id="COURSE_AGENT_FLOW", code="AGENTFLOW", name="Python 测试课", status="active"),
                Question(
                    id="Q_AGENT_FLOW", course_id="COURSE_AGENT_FLOW",
                    question_type="single_choice", topic="Python列表",
                    difficulty="easy", knowledge_count_level=1, reasoning_level=0,
                    transfer_level=0, distractor_level=0, difficulty_score=1,
                    stem="列表第一个元素的索引是？", options={"A": "0", "B": "1"},
                    answer_key="A", explanation="列表索引从 0 开始。", max_score=5.0,
                ),
                TeacherCourseAssignment(
                    teacher_id="T_AGENT_FLOW", course_id="COURSE_AGENT_FLOW",
                    assigned_by="A_AGENT_FLOW",
                ),
                Enrollment(student_id="S_AGENT_FLOW", course_id="COURSE_AGENT_FLOW"),
                ChatSession(
                    id="SESSION_AGENT_FLOW", user_id="S_AGENT_FLOW",
                    course_id="COURSE_AGENT_FLOW", status="active",
                ),
            ])
            db.commit()
            password_hash = hash_password(self.password)
            db.add_all([
                UserCredential(user_id=user_id, password_hash=password_hash)
                for user_id in (
                    "A_AGENT_FLOW", "T_AGENT_FLOW", "T_OTHER_FLOW",
                    "S_AGENT_FLOW", "S_OTHER_FLOW",
                )
            ])
            db.commit()

        def test_db():
            with self.Session() as db:
                yield db

        app.dependency_overrides[exam_dependencies.get_db] = test_db
        self.client = TestClient(app)
        self.tokens = {}
        self.agent = build_student_agent(
            model=EvidenceAwareModel(responses=[]), checkpointer=InMemorySaver(),
        )
        self.patches = [
            patch.object(agent_runner, "SessionLocal", self.Session),
            patch.object(agent_runner, "student_agent", self.agent),
            patch.object(memory_service, "get_short_term_messages", return_value=[]),
            patch.object(memory_service, "add_short_term_message"),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.client.close()
        app.dependency_overrides.clear()
        self.engine.dispose()

    def headers(self, user_id):
        if user_id not in self.tokens:
            login = self.client.post(
                "/api/auth/login",
                data={"username": user_id, "password": self.password},
            )
            self.assertEqual(login.status_code, 200, login.text)
            self.tokens[user_id] = login.json()["access_token"]
        return {"Authorization": f"Bearer {self.tokens[user_id]}"}

    def test_teacher_exam_submission_wrong_record_and_agent_advice(self):
        draft_body = {
            "course_id": "COURSE_AGENT_FLOW", "title": "列表测验",
            "duration_minutes": 30,
            "items": [{"question_id": "Q_AGENT_FLOW", "points": 5}],
        }
        self.assertEqual(
            self.client.post("/api/exams/drafts", json=draft_body, headers=self.headers("A_AGENT_FLOW")).status_code,
            403,
        )
        self.assertEqual(
            self.client.post("/api/exams/drafts", json=draft_body, headers=self.headers("T_OTHER_FLOW")).status_code,
            403,
        )

        draft = self.client.post(
            "/api/exams/drafts", json=draft_body, headers=self.headers("T_AGENT_FLOW"),
        )
        self.assertEqual(draft.status_code, 200, draft.text)
        exam_id = draft.json()["exam_id"]
        self.assertEqual(draft.json()["status"], "draft")
        published = self.client.post(
            f"/api/exams/{exam_id}/publish", headers=self.headers("T_AGENT_FLOW"),
        )
        self.assertEqual(published.json()["status"], "published")

        available = self.client.get("/api/exams/available", headers=self.headers("S_AGENT_FLOW"))
        self.assertEqual(available.status_code, 200)
        self.assertIn(exam_id, [item["exam_id"] for item in available.json()])
        other_available = self.client.get("/api/exams/available", headers=self.headers("S_OTHER_FLOW"))
        self.assertEqual(other_available.json(), [])

        attempt = self.client.post(
            f"/api/exams/{exam_id}/attempts", headers=self.headers("S_AGENT_FLOW"),
        )
        self.assertEqual(attempt.status_code, 200, attempt.text)
        attempt_id = attempt.json()["attempt_id"]
        paper = self.client.get(
            f"/api/exams/attempts/{attempt_id}/paper", headers=self.headers("S_AGENT_FLOW"),
        )
        self.assertEqual(paper.status_code, 200)
        self.assertNotIn("answer_key", paper.text)
        self.assertNotIn("explanation", paper.text)

        submitted = self.client.post(
            f"/api/exams/attempts/{attempt_id}/submit",
            json={"answers": [{"question_id": "Q_AGENT_FLOW", "answer": "B"}]},
            headers=self.headers("S_AGENT_FLOW"),
        )
        self.assertEqual(submitted.status_code, 200, submitted.text)
        self.assertEqual(submitted.json()["status"], "graded")
        self.assertEqual(submitted.json()["total_score"], 0)
        self.assertFalse(submitted.json()["answers"][0]["is_correct"])
        self.assertEqual(submitted.json()["answers"][0]["stem"], "列表第一个元素的索引是？")
        self.assertEqual(submitted.json()["answers"][0]["correct_answer"], "A")
        mine = self.client.get("/api/exams/attempts/mine", headers=self.headers("S_AGENT_FLOW"))
        self.assertEqual(mine.status_code, 200)
        self.assertEqual(mine.json()[0]["attempt_id"], attempt_id)
        self.assertEqual(self.client.get(
            "/api/exams/attempts/mine", headers=self.headers("S_OTHER_FLOW")
        ).json(), [])

        with self.Session() as db:
            wrong = db.scalar(select(WrongQuestion).where(WrongQuestion.student_id == "S_AGENT_FLOW"))
            self.assertIsNotNone(wrong)
            self.assertEqual(wrong.question_id, "Q_AGENT_FLOW")

        response = self.client.post(
            "/api/chat",
            json={"session_id": "SESSION_AGENT_FLOW", "message": "结合我的考试错题给出建议"},
            headers=self.headers("S_AGENT_FLOW"),
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("Q_AGENT_FLOW", response.json()["answer"])
        self.assertEqual(response.json()["called_tools"], [
            "get_current_course_wrong_questions",
            "analyze_current_course_wrong_questions",
        ])
        self.assertEqual(response.json()["steps"], 3)

        with self.Session() as db:
            saved = db.scalars(select(ChatMessage).where(ChatMessage.session_id == "SESSION_AGENT_FLOW")).all()
            self.assertEqual([message.role for message in saved], ["user", "assistant"])
            self.assertEqual(json.loads(saved[1].metadata_json)["steps"], 3)

        denied_chat = self.client.post(
            "/api/chat",
            json={"session_id": "SESSION_AGENT_FLOW", "message": "查看错题"},
            headers=self.headers("S_OTHER_FLOW"),
        )
        self.assertEqual(denied_chat.status_code, 403)


if __name__ == "__main__":
    unittest.main()
