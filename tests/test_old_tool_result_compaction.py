"""旧工具结果压缩只影响模型输入，不丢失 checkpoint 中的原文。"""

import sqlite3
import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver

from app.memory.tool_result_compaction import compact_old_tool_results
from app.services.material_search_service import get_indexed_course_material_chunk
from student_agent import (
    StudentAgentContext,
    build_student_agent,
    get_current_course_wrong_question_by_id,
)
import rag_tools


class RecordingModel(FakeMessagesListChatModel):
    seen_messages: list | None = None

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen_messages = list(messages)
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


class OldToolResultCompactionTests(unittest.TestCase):
    def test_index_card_keeps_question_and_source_chunk_ids(self):
        result = {
            "status": "success",
            "course_id": "C001",
            "topic": "Python列表",
            "wrong_questions": [{
                "question_id": "Q001", "topic": "Python列表",
                "stem": "题干" * 1000, "correct_answer": "A",
            }],
            "retrieved_chunks": [{
                "chunk_id": "M001:chunk:1:abc", "topic": "Python列表",
                "material_id": "M001", "original_filename": "list.md",
                "content": "资料正文" * 1000,
            }],
        }
        messages = [
            HumanMessage(content="old question"),
            AIMessage(content="", tool_calls=[{
                "name": "searchlearningmaterial",
                "args": {"topic": "Python列表", "query": "列表索引"},
                "id": "call-old",
            }]),
            ToolMessage(
                content=json.dumps(result, ensure_ascii=False),
                tool_call_id="call-old", name="searchlearningmaterial",
            ),
            AIMessage(content="old answer"),
            HumanMessage(content="刚才那段资料是什么意思？"),
        ]

        card = json.loads(compact_old_tool_results(messages)[2].content)
        self.assertEqual(card["course_id"], "C001")
        self.assertEqual(card["topic"], "Python列表")
        self.assertEqual(card["query"], "列表索引")
        self.assertEqual(card["question_ids"], ["Q001"])
        self.assertEqual(card["material_chunks"][0]["chunk_id"], "M001:chunk:1:abc")
        self.assertEqual(card["material_chunks"][0]["position"], 1)
        self.assertEqual(card["material_chunks"][0]["original_filename"], "list.md")
        self.assertNotIn("stem", card)
        self.assertNotIn("资料正文", json.dumps(card, ensure_ascii=False))

    def test_keeps_current_turn_and_tool_call_ids(self):
        old_result = "old evidence " * 200
        current_result = "current evidence " * 200
        messages = [
            HumanMessage(content="old question"),
            AIMessage(content="", tool_calls=[{
                "name": "searchlearningmaterial", "args": {}, "id": "call-old",
            }]),
            ToolMessage(content=old_result, tool_call_id="call-old", name="searchlearningmaterial"),
            AIMessage(content="old answer"),
            HumanMessage(content="current question"),
            AIMessage(content="", tool_calls=[{
                "name": "searchlearningmaterial", "args": {}, "id": "call-new",
            }]),
            ToolMessage(content=current_result, tool_call_id="call-new", name="searchlearningmaterial"),
        ]

        compacted = compact_old_tool_results(messages)

        self.assertEqual(len(compacted), len(messages))
        self.assertLess(len(compacted[2].content), 100)
        self.assertEqual(compacted[2].tool_call_id, "call-old")
        self.assertEqual(compacted[6].content, current_result)
        self.assertEqual(messages[2].content, old_result)

    def test_model_input_is_shorter_but_checkpoint_keeps_original(self):
        old_result = "source material " * 800
        with tempfile.TemporaryDirectory() as temp_dir:
            connection = sqlite3.connect(
                str(Path(temp_dir) / "checkpoints.db"),
                check_same_thread=False,
            )
            try:
                saver = SqliteSaver(connection)
                saver.setup()
                model = RecordingModel(responses=[AIMessage(content="final answer")])
                agent = build_student_agent(model=model, checkpointer=saver)
                config = {"configurable": {"thread_id": "COMPACT_TEST"}}
                agent.invoke(
                    {"messages": [
                        HumanMessage(content="old question"),
                        AIMessage(content="", tool_calls=[{
                            "name": "searchlearningmaterial", "args": {}, "id": "call-old",
                        }]),
                        ToolMessage(content=old_result, tool_call_id="call-old", name="searchlearningmaterial"),
                        AIMessage(content="old answer"),
                        HumanMessage(content="new question"),
                    ]},
                    config=config,
                    context=StudentAgentContext(db=object(), student_id="S001", course_id="C001"),
                )

                seen_result = next(
                    message for message in model.seen_messages
                    if isinstance(message, ToolMessage)
                )
                stored_result = next(
                    message for message in agent.get_state(config).values["messages"]
                    if isinstance(message, ToolMessage)
                )
                self.assertLess(len(seen_result.content), 100)
                self.assertEqual(stored_result.content, old_result)
            finally:
                connection.close()

    def test_exact_chroma_lookup_rejects_other_course(self):
        class FakeStore:
            def get(self, **kwargs):
                self_ids = kwargs["ids"]
                return {
                    "ids": self_ids,
                    "documents": ["source content"],
                    "metadatas": [{
                        "course_id": "C001", "topic": "Python列表",
                        "material_id": "M001", "original_filename": "list.md",
                    }],
                }

        found = get_indexed_course_material_chunk(
            course_id="C001", chunk_id="M001:chunk:1:abc", vector_store=FakeStore(),
        )
        denied = get_indexed_course_material_chunk(
            course_id="C002", chunk_id="M001:chunk:1:abc", vector_store=FakeStore(),
        )
        self.assertEqual(found["content"], "source content")
        self.assertEqual(denied["status"], "chunk_not_found")
        self.assertNotIn("content", denied)

    def test_followup_uses_chunk_id_and_runtime_course(self):
        model = RecordingModel(responses=[
            AIMessage(content="", tool_calls=[{
                "name": "get_current_course_material_chunk_by_id",
                "args": {"chunk_id": "M001:chunk:1:abc"},
                "id": "refetch-1",
            }]),
            AIMessage(content="下标从 0 开始。"),
        ])
        agent = build_student_agent(model=model)
        with patch("student_agent.load_course_material_chunk", return_value={
            "status": "success", "course_id": "C001",
            "chunk_id": "M001:chunk:1:abc", "content": "第一个元素下标为 0。",
        }) as load_chunk:
            result = agent.invoke(
                {"messages": [HumanMessage(content="刚才那段资料讲什么？")]},
                context=StudentAgentContext(db=object(), student_id="S001", course_id="C001"),
            )
        load_chunk.assert_called_once_with(
            course_id="C001", chunk_id="M001:chunk:1:abc", topic=None,
        )
        self.assertEqual(result["messages"][-1].content, "下标从 0 开始。")

    def test_wrong_question_lookup_uses_student_and_course(self):
        runtime = type("Runtime", (), {
            "context": StudentAgentContext(db=object(), student_id="S001", course_id="C001"),
        })()
        with patch("student_agent.get_course_wrong_question_details", return_value={
            "wrong_questions": [{"question_id": "Q001", "stem": "原题"}],
        }) as load_questions:
            found = get_current_course_wrong_question_by_id.func("Q001", runtime)
            missing = get_current_course_wrong_question_by_id.func("Q999", runtime)
        self.assertEqual(found["wrong_question"]["stem"], "原题")
        self.assertEqual(missing["status"], "wrong_question_not_found")
        self.assertEqual(load_questions.call_args.kwargs["student_id"], "S001")
        self.assertEqual(load_questions.call_args.kwargs["course_id"], "C001")

    def test_legacy_chunk_can_be_refetched_without_embedding(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            course_dir = Path(temp_dir) / "C001"
            course_dir.mkdir()
            (course_dir / "materials.json").write_text(
                json.dumps({"topics": {"Python列表": "list.md"}}), encoding="utf-8",
            )
            (course_dir / "list.md").write_text(
                "# Python列表\n\n## 索引\n第一个元素下标为 0。", encoding="utf-8",
            )
            with patch.object(rag_tools, "KNOWLEDGE_DIR", Path(temp_dir)), patch.object(
                rag_tools, "SessionLocal"
            ), patch.object(rag_tools, "has_indexed_course_materials", return_value=False):
                found = rag_tools.get_course_material_chunk("C001", "1", "Python列表")
                missing = rag_tools.get_course_material_chunk("C002", "1", "Python列表")
            self.assertEqual(found["status"], "success")
            self.assertIn("下标为 0", found["content"])
            self.assertNotEqual(missing["status"], "success")


if __name__ == "__main__":
    unittest.main()
