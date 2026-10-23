import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from langchain_core.language_models.fake_chat_models import (
    FakeMessagesListChatModel,
)
from langchain_core.messages import AIMessage


# 允许直接运行本测试文件。
PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

# 导入 student_agent 时只创建客户端，不发送网络请求。
os.environ.setdefault(
    "DEEPSEEK_API_KEY",
    "test-api-key",
)

import agent_runner
import student_agent as student_agent_module
from student_agent import build_student_agent


class ToolCallingFakeChatModel(
    FakeMessagesListChatModel
):
    """支持 bind_tools 的确定性假聊天模型。"""

    def bind_tools(
        self,
        tools,
        *,
        tool_choice=None,
        **kwargs,
    ):
        return self


def make_test_agent(*responses):
    """用预设模型回复构建 LangChain Agent。"""

    model = ToolCallingFakeChatModel(
        responses=list(responses),
    )
    return build_student_agent(model=model)


class LangChainAgentLoopTests(unittest.TestCase):
    def test_review_plan_tool_schema_hides_runtime_context(self):
        """模型只应看到诊断数据，不能看到数据库运行时上下文。"""

        prepare_schema = (
            student_agent_module
            .prepare_current_course_review_plan
            .tool_call_schema
            .model_json_schema()
        )
        diagnosis_schema = (
            student_agent_module
            .validate_current_course_diagnoses
            .tool_call_schema
            .model_json_schema()
        )
        finalize_schema = (
            student_agent_module
            .finalize_current_course_review_plan
            .tool_call_schema
            .model_json_schema()
        )

        self.assertEqual(
            prepare_schema["properties"],
            {},
        )
        self.assertEqual(
            set(diagnosis_schema["properties"]),
            {"diagnoses"},
        )
        self.assertNotIn(
            "runtime",
            diagnosis_schema["properties"],
        )
        self.assertNotIn(
            "db",
            diagnosis_schema["properties"],
        )
        self.assertEqual(
            set(finalize_schema["properties"]),
            {"diagnoses", "review_tasks"},
        )
        self.assertNotIn(
            "runtime",
            finalize_schema["properties"],
        )
        self.assertNotIn(
            "db",
            finalize_schema["properties"],
        )

    def test_error_diagnosis_contract_is_registered(self):
        """核心提示词负责路由，详细诊断规则由 Skill 按需加载。"""

        prompt = student_agent_module.STUDENT_SYSTEM_PROMPT
        skill = student_agent_module.read_student_skill("wrong_question_diagnosis")
        self.assertEqual(skill["status"], "success")
        instructions = skill["instructions"]
        tool_description = (
            student_agent_module
            .get_current_course_wrong_questions
            .description
        )

        for error_type in (
            "concept_misunderstanding",
            "reasoning_error",
            "knowledge_application_error",
            "answer_format_error",
            "insufficient_evidence",
        ):
            self.assertIn(error_type, instructions)

        self.assertIn("load_student_skill", prompt)
        self.assertIn("confidence", instructions)
        self.assertIn("direct_evidence", instructions)
        self.assertIn("inference_reason", instructions)
        self.assertIn("alternative_explanations", instructions)
        self.assertIn("仅一次错误作答", instructions)
        self.assertIn("一次作答", instructions)
        self.assertIn("medium", instructions)
        self.assertIn("诊断错误类型", tool_description)
        self.assertIn("完整选项内容", tool_description)

    def test_error_diagnosis_reads_current_course_wrong_questions(self):
        """诊断前必须读取后端限定学生和课程的具体错题。"""

        fake_agent = make_test_agent(
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": (
                            "get_current_course_"
                            "wrong_questions"
                        ),
                        "args": {},
                        "id": "call_diagnose_001",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(
                content=(
                    "题目：LIST_Q1\n"
                    "初步错误类型：concept_misunderstanding\n"
                    "直接证据：学生选择 C「3」，正确答案为 B「2」。\n"
                    "推断理由：该选择与把长度误认为最大索引的模式一致。\n"
                    "其他可能：不能排除临时猜测或审题偏差。\n"
                    "置信度：medium"
                )
            ),
        )

        fake_db = object()
        detail_requests = []

        def fake_details(
            db,
            student_id,
            course_id,
        ):
            detail_requests.append({
                "db": db,
                "student_id": student_id,
                "course_id": course_id,
            })
            return {
                "status": "success",
                "student_id": student_id,
                "course_id": course_id,
                "total_wrong_questions": 1,
                "wrong_questions": [
                    {
                        "question_id": "LIST_Q1",
                        "topic": "Python列表",
                        "question_type": "single_choice",
                        "difficulty": "medium",
                        "difficulty_score": 4,
                        "stem": "长度为 3 的列表最大索引是多少？",
                        "options": {
                            "A": "1",
                            "B": "2",
                            "C": "3",
                            "D": "4",
                        },
                        "student_answer": "C",
                        "correct_answer": "B",
                        "explanation": (
                            "列表索引从 0 开始，最大索引是长度减 1。"
                        ),
                    }
                ],
            }

        with (
            patch.object(
                agent_runner,
                "student_agent",
                fake_agent,
            ),
            patch.object(
                student_agent_module,
                "get_course_wrong_question_details",
                fake_details,
            ),
        ):
            result = agent_runner.run_agent(
                messages=[
                    {
                        "role": "user",
                        "content": "分析我为什么做错了这道题",
                    }
                ],
                db=fake_db,
                student_id="STUDENT_001",
                course_id="COURSE_A",
                verbose=False,
            )

        self.assertEqual(
            detail_requests,
            [
                {
                    "db": fake_db,
                    "student_id": "STUDENT_001",
                    "course_id": "COURSE_A",
                }
            ],
        )
        self.assertEqual(
            result["called_tools"],
            ["get_current_course_wrong_questions"],
        )
        self.assertEqual(len(result["tool_trace"]), 1)
        self.assertEqual(
            result["tool_trace"][0]["status"],
            "success",
        )
        self.assertEqual(result["steps"], 2)
        self.assertIn("LIST_Q1", result["answer"])
        self.assertIn(
            "concept_misunderstanding",
            result["answer"],
        )
        self.assertIn("直接证据", result["answer"])
        self.assertIn("C「3」", result["answer"])
        self.assertIn("B「2」", result["answer"])
        self.assertIn("推断理由", result["answer"])
        self.assertIn("其他可能", result["answer"])
        self.assertIn("置信度：medium", result["answer"])

    def test_finalize_review_plan_tool_uses_runtime_context(self):
        diagnosis = {
            "question_id": "LIST_1",
            "topic": "Python列表",
            "error_type": "concept_misunderstanding",
            "direct_evidence": ["学生答案与正确答案不同。"],
            "inference_reason": "可能没有掌握索引规则。",
            "alternative_explanations": [],
            "confidence": "medium",
        }
        task = {
            "task_id": "review_list_1",
            "topic": "Python列表",
            "priority_rank": 1,
            "objective": "掌握列表索引规则。",
            "related_error_types": ["concept_misunderstanding"],
            "action_steps": ["阅读列表索引资料。"],
            "material_chunk_ids": ["CHUNK_LIST"],
            "self_check_questions": ["列表首项索引是什么？"],
        }
        fake_agent = make_test_agent(
            AIMessage(
                content="",
                tool_calls=[{
                    "name": "finalize_current_course_review_plan",
                    "args": {
                        "diagnoses": [diagnosis],
                        "review_tasks": [task],
                    },
                    "id": "call_finalize_001",
                    "type": "tool_call",
                }],
            ),
            AIMessage(content="结构化复习计划已经通过后端校验。"),
        )
        requests = []

        def fake_finalize(
            db,
            student_id,
            course_id,
            diagnoses,
            review_tasks,
        ):
            requests.append({
                "db": db,
                "student_id": student_id,
                "course_id": course_id,
                "diagnoses": diagnoses,
                "review_tasks": review_tasks,
            })
            return {
                "status": "success",
                "review_tasks": review_tasks,
            }

        fake_db = object()
        with (
            patch.object(agent_runner, "student_agent", fake_agent),
            patch.object(
                student_agent_module,
                "finalize_grounded_review_plan",
                fake_finalize,
            ),
        ):
            result = agent_runner.run_agent(
                messages=[{
                    "role": "user",
                    "content": "生成结构化复习计划",
                }],
                db=fake_db,
                student_id="S007",
                course_id="PYTHON101",
                verbose=False,
            )

        self.assertEqual(len(requests), 1)
        self.assertIs(requests[0]["db"], fake_db)
        self.assertEqual(requests[0]["student_id"], "S007")
        self.assertEqual(requests[0]["course_id"], "PYTHON101")
        self.assertEqual(
            result["called_tools"],
            ["finalize_current_course_review_plan"],
        )
        self.assertEqual(result["steps"], 2)
        self.assertEqual(
            result["review_plan"]["status"],
            "success",
        )
        self.assertEqual(
            result["review_plan"]["review_tasks"][0]["topic"],
            "Python列表",
        )

    def test_direct_answer_without_tool(self):
        """普通回答不应产生工具调用。"""

        fake_agent = make_test_agent(
            AIMessage(content="你好，我是课程学习助手。"),
        )

        with patch.object(
            agent_runner,
            "student_agent",
            fake_agent,
        ):
            result = agent_runner.run_agent(
                messages=[
                    {
                        "role": "user",
                        "content": "你好",
                    }
                ],
                db=object(),
                student_id="STUDENT_001",
                course_id="COURSE_A",
                verbose=False,
            )

        self.assertEqual(
            result["answer"],
            "你好，我是课程学习助手。",
        )
        self.assertEqual(result["called_tools"], [])
        self.assertEqual(result["tool_trace"], [])
        self.assertEqual(result["steps"], 1)

    def test_wrong_question_then_course_rag(self):
        """验证错题分析后继续检索当前课程资料。"""

        fake_agent = make_test_agent(
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": (
                            "analyze_current_course_"
                            "wrong_questions"
                        ),
                        "args": {},
                        "id": "call_analyze_001",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "searchlearningmaterial",
                        "args": {
                            "topic": "Python列表",
                            "query": (
                                "根据列表索引错题给出复习建议"
                            ),
                        },
                        "id": "call_rag_001",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(
                content=(
                    "你应优先复习列表索引范围，"
                    "资料来源为 python_list.md。"
                )
            ),
        )

        fake_db = object()
        analyze_requests = []
        rag_requests = []

        def fake_analyze(
            db,
            student_id,
            course_id,
        ):
            analyze_requests.append({
                "db": db,
                "student_id": student_id,
                "course_id": course_id,
            })
            return {
                "status": "success",
                "course_id": course_id,
                "priority_topic": "Python列表",
                "total_wrong_questions": 2,
            }

        def fake_search(
            course_id,
            topic,
            query,
        ):
            rag_requests.append({
                "course_id": course_id,
                "topic": topic,
                "query": query,
            })
            return {
                "status": "success",
                "course_id": course_id,
                "topic": topic,
                "source": "python_list.md",
                "retrieved_chunks": [
                    {
                        "content": (
                            "列表有效索引范围是"
                            "0到len(list)-1。"
                        )
                    }
                ],
            }

        with (
            patch.object(
                agent_runner,
                "student_agent",
                fake_agent,
            ),
            patch.object(
                student_agent_module,
                "analyze_course_wrong_questions",
                fake_analyze,
            ),
            patch.object(
                student_agent_module,
                "search_course_material",
                fake_search,
            ),
        ):
            result = agent_runner.run_agent(
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "分析我的错题并给出复习建议"
                        ),
                    }
                ],
                db=fake_db,
                student_id="STUDENT_001",
                course_id="COURSE_A",
                verbose=False,
            )

        self.assertEqual(
            analyze_requests,
            [
                {
                    "db": fake_db,
                    "student_id": "STUDENT_001",
                    "course_id": "COURSE_A",
                }
            ],
        )
        self.assertEqual(
            rag_requests,
            [
                {
                    "course_id": "COURSE_A",
                    "topic": "Python列表",
                    "query": (
                        "根据列表索引错题给出复习建议"
                    ),
                }
            ],
        )
        self.assertEqual(
            result["called_tools"],
            [
                "analyze_current_course_wrong_questions",
                "searchlearningmaterial",
            ],
        )
        self.assertEqual(len(result["tool_trace"]), 2)
        self.assertTrue(
            all(
                item["status"] == "success"
                for item in result["tool_trace"]
            )
        )
        self.assertEqual(result["steps"], 3)
        self.assertIn(
            "python_list.md",
            result["answer"],
        )

    def test_invalid_tool_arguments_become_tool_error(self):
        """缺少 query 时，Agent 能读取工具错误并回答。"""

        fake_agent = make_test_agent(
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "searchlearningmaterial",
                        "args": {
                            "topic": "Python列表",
                        },
                        "id": "call_invalid_001",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(
                content=(
                    "检索参数不完整，暂时无法查询资料。"
                )
            ),
        )

        with patch.object(
            agent_runner,
            "student_agent",
            fake_agent,
        ):
            result = agent_runner.run_agent(
                messages=[
                    {
                        "role": "user",
                        "content": "查找列表资料",
                    }
                ],
                db=object(),
                student_id="STUDENT_001",
                course_id="COURSE_A",
                verbose=False,
            )

        self.assertEqual(
            result["called_tools"],
            ["searchlearningmaterial"],
        )
        self.assertEqual(len(result["tool_trace"]), 1)
        self.assertEqual(
            result["tool_trace"][0]["status"],
            "error",
        )
        self.assertIn(
            "Field required",
            result["tool_trace"][0]["error"],
        )
        self.assertEqual(result["steps"], 2)

    def test_course_is_required_before_agent_invocation(self):
        """没有课程的会话不能运行学生课程 Agent。"""

        fake_agent = MagicMock()

        with patch.object(
            agent_runner,
            "student_agent",
            fake_agent,
        ):
            with self.assertRaisesRegex(
                ValueError,
                "必须关联课程",
            ):
                agent_runner.run_agent(
                    messages=[
                        {
                            "role": "user",
                            "content": "分析错题",
                        }
                    ],
                    db=object(),
                    student_id="STUDENT_001",
                    course_id=None,
                    verbose=False,
                )

        fake_agent.invoke.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
