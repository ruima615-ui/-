"""长会话摘要写入 checkpoint，并保留本轮工具链。"""

import sqlite3
import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, ToolMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.checkpoint.sqlite import SqliteSaver

import agent_runner
from app.memory.conversation_summary import (
    SUMMARY_REFERENCE_MARKER,
    StudentConversationSummarizationMiddleware,
)
from student_agent import build_student_agent


class ToolReadyFakeModel(FakeMessagesListChatModel):
    seen_messages: list | None = None
    calls: int = 0

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        self.seen_messages = list(messages)
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


class RecordingSummaryModel(FakeMessagesListChatModel):
    calls: int = 0
    seen_prompts: list[str] = []

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        self.seen_prompts.append("\n".join(str(message.content) for message in messages))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def make_agent(path, main_responses, summary_model):
    connection = sqlite3.connect(str(path), check_same_thread=False)
    saver = SqliteSaver(connection)
    saver.setup()
    model = ToolReadyFakeModel(responses=main_responses)
    agent = build_student_agent(model=model, summary_model=summary_model, checkpointer=saver)
    return connection, agent, model


def run_turn(agent, thread_id, text):
    with patch.object(agent_runner, "student_agent", agent):
        return agent_runner.run_agent(
            messages=[{"role": "user", "content": text}],
            db=object(), student_id="S_SUMMARY", course_id="C_SUMMARY",
            session_id=thread_id, verbose=False,
        )


class LongConversationSummaryTests(unittest.TestCase):
    def test_retention_starts_at_a_user_turn_and_keeps_tool_chains_together(self):
        middleware = StudentConversationSummarizationMiddleware(
            model=RecordingSummaryModel(responses=[AIMessage(content="摘要")]),
            trigger={"tokens": 4000, "messages": 12}, keep=("messages", 8),
        )
        messages = []
        for turn in range(5):
            messages.extend([
                HumanMessage(content=f"问题 {turn}"),
                AIMessage(content="", tool_calls=[{
                    "name": "searchlearningmaterial", "args": {}, "id": f"call-{turn}",
                }]),
                ToolMessage(content="结果", tool_call_id=f"call-{turn}"),
                AIMessage(content=f"回答 {turn}"),
            ])
        messages.append(HumanMessage(content="继续"))
        cutoff = middleware._determine_cutoff_index(messages)
        self.assertEqual(cutoff, 12)
        self.assertEqual([m.content for m in messages[cutoff:] if isinstance(m, HumanMessage)],
                         ["问题 3", "问题 4", "继续"])

        middleware._partial_token_counter = lambda retained: len(retained) * 1000
        self.assertEqual(middleware._determine_cutoff_index(messages), len(messages) - 1)

    def test_explicit_question_id_beats_recent_unrelated_references(self):
        messages = []
        for index in range(10):
            messages.extend([
                AIMessage(content="", tool_calls=[{
                    "name": "get_current_course_wrong_questions", "args": {},
                    "id": f"call-{index}",
                }]),
                ToolMessage(content=json.dumps({
                    "course_id": "C_SUMMARY", "topic": "索引",
                    "wrong_questions": [{"question_id": f"Q{index:02d}"}],
                }), tool_call_id=f"call-{index}", name="get_current_course_wrong_questions"),
            ])
        messages.append(HumanMessage(content="刚才 Q00 为什么错？"))
        update = {"messages": [
            RemoveMessage(id=REMOVE_ALL_MESSAGES),
            HumanMessage(content="摘要", additional_kwargs={"lc_source": "summarization"}),
            messages[-1],
        ]}
        result = StudentConversationSummarizationMiddleware._add_reference_index(
            {"messages": messages}, update,
        )
        index = json.loads(result["messages"][1].content.split(SUMMARY_REFERENCE_MARKER)[1])
        self.assertEqual(index[0]["question_ids"], ["Q00"])
        self.assertLessEqual(len(index), 8)

    def test_second_material_chunk_keeps_its_original_position(self):
        messages = [
            HumanMessage(content="检索列表资料"),
            AIMessage(content="", tool_calls=[{
                "name": "searchlearningmaterial", "args": {"topic": "Python列表"},
                "id": "search-six",
            }]),
            ToolMessage(content=json.dumps({
                "course_id": "C_SUMMARY", "topic": "Python列表",
                "retrieved_chunks": [
                    {"chunk_id": f"M001:chunk:{index}", "content": "正文" * 100}
                    for index in range(1, 7)
                ],
            }), tool_call_id="search-six", name="searchlearningmaterial"),
            AIMessage(content="找到资料"),
            HumanMessage(content="刚才第二段资料讲的是什么？"),
        ]
        update = {"messages": [
            RemoveMessage(id=REMOVE_ALL_MESSAGES),
            HumanMessage(content="摘要", additional_kwargs={"lc_source": "summarization"}),
            messages[-1],
        ]}
        result = StudentConversationSummarizationMiddleware._add_reference_index(
            {"messages": messages}, update,
        )
        index = json.loads(result["messages"][1].content.split(SUMMARY_REFERENCE_MARKER)[1])
        chunks = index[0]["material_chunks"]
        self.assertEqual([chunk["position"] for chunk in chunks], [1, 2, 3, 4])
        self.assertEqual(chunks[1]["chunk_id"], "M001:chunk:2")

    def test_reference_ids_survive_rolling_summary(self):
        old_messages = [
            HumanMessage(content="查找列表索引资料"),
            AIMessage(content="", tool_calls=[{
                "name": "searchlearningmaterial",
                "args": {"topic": "Python列表", "query": "索引"},
                "id": "old-search",
            }]),
            ToolMessage(
                content=json.dumps({
                    "course_id": "C_SUMMARY", "topic": "Python列表",
                    "retrieved_chunks": [{
                        "chunk_id": "M001:chunk:1:abc", "material_id": "M001",
                        "original_filename": "list.md", "content": "原文" * 1000,
                    }],
                    "wrong_questions": [{"question_id": "Q001", "stem": "题干" * 1000}],
                }, ensure_ascii=False),
                tool_call_id="old-search", name="searchlearningmaterial",
            ),
            AIMessage(content="已回答"),
            HumanMessage(content="继续提问"),
        ]
        update = {"messages": [
            RemoveMessage(id=REMOVE_ALL_MESSAGES),
            HumanMessage(content="旧对话摘要", additional_kwargs={"lc_source": "summarization"}),
            old_messages[-1],
        ]}
        first = StudentConversationSummarizationMiddleware._add_reference_index(
            {"messages": old_messages}, update,
        )
        summary = first["messages"][1]
        self.assertIn(SUMMARY_REFERENCE_MARKER, summary.content)
        self.assertIn("M001:chunk:1:abc", summary.content)
        self.assertIn("Q001", summary.content)
        self.assertNotIn("原文原文", summary.content)

        second = StudentConversationSummarizationMiddleware._add_reference_index(
            {"messages": [summary, HumanMessage(content="第三轮")]},
            {"messages": [
                RemoveMessage(id=REMOVE_ALL_MESSAGES),
                HumanMessage(content="合并摘要", additional_kwargs={"lc_source": "summarization"}),
                HumanMessage(content="第三轮"),
            ]},
        )
        self.assertIn("M001:chunk:1:abc", second["messages"][1].content)

    def test_five_model_decisions_fit_graph_limit_with_summary_middleware(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            summary_model = RecordingSummaryModel(responses=[AIMessage(content="摘要")])
            responses = [
                AIMessage(content="", id=f"decision-{index}", tool_calls=[{
                    "name": "searchlearningmaterial",
                    "args": {"topic": "Python列表", "query": f"问题{index}"},
                    "id": f"call-{index}",
                }])
                for index in range(1, 5)
            ] + [AIMessage(content="完成回答", id="decision-5")]
            connection, agent, _ = make_agent(
                Path(temp_dir) / "limit.db", responses, summary_model,
            )
            try:
                with patch("student_agent.search_course_material", return_value={
                    "status": "success", "course_id": "C_SUMMARY", "topic": "Python列表",
                    "retrieved_chunks": [],
                }):
                    result = run_turn(agent, "THREAD_LIMIT", "请分步骤查询资料")
                self.assertEqual(result["steps"], 5)
                self.assertEqual(len(result["called_tools"]), 4)
            finally:
                connection.close()

    def test_summary_replaces_old_state_and_survives_agent_recreation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "summary.db"
            summary_model = RecordingSummaryModel(responses=[
                AIMessage(content="学生正在学习 Python 列表索引；待解决问题是下标边界。")
            ])
            connection, agent, model = make_agent(
                path,
                [AIMessage(content=f"answer {turn}", id=f"answer-{turn}") for turn in range(1, 17)],
                summary_model,
            )
            config = {"configurable": {"thread_id": "THREAD_SUMMARY"}}
            try:
                for turn in range(1, 17):
                    result = run_turn(agent, "THREAD_SUMMARY", f"第 {turn} 轮：" + "列表索引与边界" * 240)
                    self.assertEqual(result["steps"], 1)
                state = agent.get_state(config).values["messages"]
                self.assertGreater(summary_model.calls, 0)
                self.assertLess(len(state), 32)
                if summary_model.calls > 1:
                    self.assertTrue(any(
                        "学生正在学习 Python 列表索引" in prompt
                        for prompt in summary_model.seen_prompts[1:]
                    ))
                self.assertTrue(any(
                    isinstance(message, HumanMessage)
                    and message.additional_kwargs.get("lc_source") == "summarization"
                    for message in state
                ))
            finally:
                connection.close()

            restart_summary_model = RecordingSummaryModel(responses=[AIMessage(content="再次压缩")])
            connection2, new_agent, new_model = make_agent(
                path, [AIMessage(content="继续复习边界", id="answer-restarted")],
                restart_summary_model,
            )
            try:
                resumed = run_turn(new_agent, "THREAD_SUMMARY", "继续刚才的学习目标")
                self.assertEqual(resumed["answer"], "继续复习边界")
                self.assertTrue(any(
                    isinstance(message, HumanMessage)
                    and "学生正在学习 Python 列表索引" in str(message.content)
                    for message in new_model.seen_messages
                ))
                other = new_agent.get_state({"configurable": {"thread_id": "OTHER_THREAD"}})
                self.assertEqual(other.values.get("messages", []), [])
            finally:
                connection2.close()

    def test_large_current_tool_result_is_not_summarized_mid_turn(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            summary_model = RecordingSummaryModel(responses=[AIMessage(content="不应调用")])
            responses = [
                AIMessage(content=f"answer {turn}", id=f"old-answer-{turn}")
                for turn in range(1, 6)
            ] + [
                AIMessage(content="", id="tool-call", tool_calls=[{
                    "name": "searchlearningmaterial",
                    "args": {"topic": "Python列表", "query": "索引"},
                    "id": "lookup-chunk",
                }]),
                AIMessage(content="已读取当前资料", id="final-answer"),
            ]
            connection, agent, model = make_agent(
                Path(temp_dir) / "current-turn.db", responses, summary_model,
            )
            try:
                for turn in range(1, 6):
                    run_turn(agent, "THREAD_TOOL", f"短问题 {turn}")
                with patch("student_agent.search_course_material", return_value={
                    "status": "success", "course_id": "C_SUMMARY", "topic": "Python列表",
                    "retrieved_chunks": [{"chunk_id": "chunk-1", "content": "资料" * 6000}],
                }):
                    result = run_turn(agent, "THREAD_TOOL", "请查询课程资料")

                self.assertEqual(summary_model.calls, 0)
                self.assertEqual(result["called_tools"], ["searchlearningmaterial"])
                self.assertEqual(result["steps"], 2)
                self.assertEqual(len(result["tool_trace"]), 1)
                self.assertTrue(any(
                    isinstance(message, ToolMessage) and len(str(message.content)) > 5000
                    for message in model.seen_messages
                ))
            finally:
                connection.close()

    def test_tool_trace_is_correct_when_summary_runs_before_new_turn(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            summary_model = RecordingSummaryModel(responses=[
                AIMessage(content="前几轮在学习 Python 列表索引。")
            ])
            responses = [
                AIMessage(content=f"answer {turn}", id=f"old-long-{turn}")
                for turn in range(1, 7)
            ] + [
                AIMessage(content="", id="search-call", tool_calls=[{
                    "name": "searchlearningmaterial",
                    "args": {"topic": "Python列表", "query": "索引"},
                    "id": "search-after-summary",
                }]),
                AIMessage(content="基于当前课程资料回答。", id="answer-after-summary"),
            ]
            connection, agent, _ = make_agent(
                Path(temp_dir) / "trace.db", responses, summary_model,
            )
            try:
                for turn in range(1, 7):
                    run_turn(agent, "THREAD_TRACE", f"第 {turn} 轮" + "列表索引" * 1000)
                with patch("student_agent.search_course_material", return_value={
                    "status": "success", "course_id": "C_SUMMARY", "topic": "Python列表",
                    "retrieved_chunks": [{"chunk_id": "chunk-1", "content": "索引从 0 开始"}],
                }):
                    result = run_turn(agent, "THREAD_TRACE", "现在请检索资料解释列表索引")
                self.assertGreater(summary_model.calls, 0)
                self.assertEqual(result["called_tools"], ["searchlearningmaterial"])
                self.assertEqual(result["steps"], 2)
                self.assertEqual(result["tool_trace"][0]["tool_name"], "searchlearningmaterial")
                self.assertEqual(result["tool_trace"][0]["arguments"]["query"], "索引")
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
