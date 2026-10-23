import unittest
from unittest.mock import MagicMock, patch

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

import agent_runner
from app.skills.registry import read_student_skill
from student_agent import build_student_agent, load_student_skill


class ToolCallingFakeChatModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        return self


class StudentSkillTests(unittest.TestCase):
    def test_registered_skills_load_and_have_workflow(self):
        diagnosis = read_student_skill("wrong_question_diagnosis")
        plan = read_student_skill("grounded_review_plan")
        self.assertEqual(diagnosis["status"], "success")
        self.assertIn("get_current_course_wrong_questions", diagnosis["instructions"])
        self.assertIn("validate_current_course_diagnoses", plan["instructions"])
        self.assertIn("finalize_current_course_review_plan", plan["instructions"])

    def test_only_registered_names_can_be_loaded(self):
        result = read_student_skill("../../.env")
        self.assertEqual(result["status"], "skill_not_found")
        self.assertNotIn("instructions", result)
        schema = load_student_skill.tool_call_schema.model_json_schema()
        self.assertEqual(set(schema["properties"]), {"skill_id"})

    def test_agent_can_load_skill_during_tool_loop(self):
        model = ToolCallingFakeChatModel(responses=[
            AIMessage(content="", tool_calls=[{
                "name": "load_student_skill",
                "args": {"skill_id": "wrong_question_diagnosis"},
                "id": "skill-call",
            }]),
            AIMessage(content="已读取诊断规则。"),
        ])
        agent = build_student_agent(model=model, enable_conversation_summary=False)
        with patch.object(agent_runner, "student_agent", agent):
            result = agent_runner.run_agent(
                messages=[{"role": "user", "content": "诊断错题"}],
                db=MagicMock(), student_id="S008", course_id="PYTHON101",
                verbose=False,
            )
        self.assertEqual(result["called_tools"], ["load_student_skill"])
        self.assertIn('"status": "success"', result["tool_trace"][0]["result_preview"])
        self.assertIn("wrong_question_diagnosis", result["tool_trace"][0]["result_preview"])


if __name__ == "__main__":
    unittest.main()
