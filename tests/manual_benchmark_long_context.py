"""离线复现长会话：对比摘要前后的模型输入、精确重取和本地耗时。

运行：python -m tests.manual_benchmark_long_context
使用临时 SQLite checkpoint 和固定的模拟工具结果，不访问 DeepSeek 或生产数据库。
"""

import json
import sqlite3
import tempfile
from pathlib import Path
from statistics import mean, stdev
from time import perf_counter
from unittest.mock import patch

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.messages.utils import count_tokens_approximately
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import Field

import agent_runner
from app.memory.conversation_summary import SUMMARY_REFERENCE_MARKER
from student_agent import build_student_agent


COURSE_ID = "BENCH_COURSE"
QUESTION_ID = "Q03"
CHUNKS = ("M001:chunk:1", "M001:chunk:2")
SECOND_CHUNK_FACT = "第二段指出：访问索引时应先检查索引是否小于列表长度。"
QUESTION_FACT = "Q03 的错误原因是把列表长度当成最后一个合法索引。"


def _cards(messages):
    """从模型真实可见的消息里读取引用，而非直接读取测试常量。"""
    cards = []
    for message in messages:
        content = str(message.content)
        if isinstance(message, HumanMessage) and SUMMARY_REFERENCE_MARKER in content:
            content = content.rsplit(SUMMARY_REFERENCE_MARKER, 1)[1]
        elif not isinstance(message, ToolMessage):
            continue
        try:
            value = json.loads(content)
        except ValueError:
            continue
        if isinstance(value, list):
            cards.extend(item for item in value if isinstance(item, dict))
        elif isinstance(value, dict):
            cards.append(value)
    return cards


class BenchmarkModel(FakeMessagesListChatModel):
    input_tokens: list[int] = Field(default_factory=list)

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.input_tokens.append(count_tokens_approximately(messages))
        latest_user = max(
            index for index, message in enumerate(messages)
            if isinstance(message, HumanMessage)
            and message.additional_kwargs.get("lc_source") != "summarization"
        )
        question = str(messages[latest_user].content)
        current_tools = [
            message for message in messages[latest_user + 1:]
            if isinstance(message, ToolMessage)
        ]

        if question.startswith("初始化检索"):
            if not current_tools:
                response = AIMessage(content="", tool_calls=[
                    {"name": "searchlearningmaterial", "args": {
                        "topic": "Python列表", "query": "索引边界",
                    }, "id": "initial-material"},
                    {"name": "get_current_course_wrong_questions", "args": {},
                     "id": "initial-question"},
                ])
            else:
                response = AIMessage(content="已经查看课程资料和错题。")
        elif "第二段资料" in question:
            exact = next((item for item in current_tools
                          if item.name == "get_current_course_material_chunk_by_id"), None)
            if exact:
                result = json.loads(exact.text)
                response = AIMessage(content=result.get("content", "找不到资料"))
            else:
                chunks = [chunk for card in _cards(messages)
                          for chunk in card.get("material_chunks", card.get("retrieved_chunks", []))]
                second = next((chunk for chunk in chunks if chunk.get("position") == 2), None)
                response = AIMessage(content="", tool_calls=[{
                    "name": "get_current_course_material_chunk_by_id",
                    "args": {"chunk_id": second["chunk_id"], "topic": "Python列表"},
                    "id": "refetch-second-chunk",
                }]) if second else AIMessage(content="找不到第二段资料的索引")
        elif QUESTION_ID in question:
            exact = next((item for item in current_tools
                          if item.name == "get_current_course_wrong_question_by_id"), None)
            if exact:
                result = json.loads(exact.text)
                response = AIMessage(content=result.get("wrong_question", {}).get("explanation", "找不到错题"))
            else:
                ids = [identifier for card in _cards(messages)
                       for identifier in card.get("question_ids", [])]
                ids.extend(item.get("question_id") for card in _cards(messages)
                           for item in card.get("wrong_questions", []))
                response = AIMessage(content="", tool_calls=[{
                    "name": "get_current_course_wrong_question_by_id",
                    "args": {"question_id": QUESTION_ID}, "id": "refetch-q03",
                }]) if QUESTION_ID in ids else AIMessage(content="找不到 Q03 的索引")
        else:
            response = AIMessage(content="继续学习列表索引。" + "边界检查很重要。" * 65)
        return ChatResult(generations=[ChatGeneration(message=response)])


class CountingSummaryModel(FakeMessagesListChatModel):
    input_tokens: list[int] = Field(default_factory=list)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.input_tokens.append(count_tokens_approximately(messages))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def _make_agent(path, model, summary_model, enabled):
    connection = sqlite3.connect(str(path), check_same_thread=False)
    saver = SqliteSaver(connection)
    saver.setup()
    agent = build_student_agent(
        model=model, summary_model=summary_model, checkpointer=saver,
        enable_conversation_summary=enabled,
    )
    return connection, agent


def _material_result(*, course_id, topic, query):
    assert course_id == COURSE_ID
    return {
        "status": "success", "course_id": course_id, "topic": topic,
        "source": "chroma", "retrieved_chunks": [
            {"chunk_id": CHUNKS[0], "material_id": "M001",
             "original_filename": "python_list.md", "content": "第一段：列表可用下标访问。" * 130},
            {"chunk_id": CHUNKS[1], "material_id": "M001",
             "original_filename": "python_list.md", "content": SECOND_CHUNK_FACT * 100},
        ],
    }


def _wrong_questions(*, db, student_id, course_id):
    assert student_id == "BENCH_STUDENT" and course_id == COURSE_ID
    return {"status": "success", "wrong_questions": [
        {"question_id": QUESTION_ID, "topic": "Python列表",
         "explanation": QUESTION_FACT, "stem": "列表 [1,2,3] 的最后合法索引是多少？"},
    ]}


def _material_chunk(*, course_id, chunk_id, topic=None):
    assert course_id == COURSE_ID
    if chunk_id != CHUNKS[1]:
        return {"status": "chunk_not_found", "course_id": course_id}
    return {"status": "success", "course_id": course_id,
            "chunk_id": chunk_id, "content": SECOND_CHUNK_FACT}


def measure(enabled):
    model = BenchmarkModel(responses=[AIMessage(content="unused")])
    summary_model = CountingSummaryModel(responses=[AIMessage(
        content="学生正在学习 Python 列表索引；早先查看过课程资料和 Q03 错题。"
    )])
    per_turn = []
    checks = []
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "checkpoint.db"
        connection, agent = _make_agent(db_path, model, summary_model, enabled)
        try:
            with patch("student_agent.search_course_material", side_effect=_material_result), \
                 patch("student_agent.get_course_wrong_question_details", side_effect=_wrong_questions), \
                 patch("student_agent.load_course_material_chunk", side_effect=_material_chunk):
                questions = ["初始化检索课程资料和 Q03 错题"]
                questions.extend("第 %s 轮学习列表索引：%s" % (turn, "如何检查边界？" * 45)
                                 for turn in range(1, 23))
                questions.extend(["刚才第二段资料讲的是什么？", "Q03 为什么做错？"])
                for turn, question in enumerate(questions):
                    if turn == 12:  # 关闭并重新创建 Agent，从磁盘 checkpoint 恢复。
                        connection.close()
                        connection, agent = _make_agent(db_path, model, summary_model, enabled)
                    model_start = len(model.input_tokens)
                    summary_start = len(summary_model.input_tokens)
                    start = perf_counter()
                    with patch.object(agent_runner, "student_agent", agent):
                        result = agent_runner.run_agent(
                            messages=[{"role": "user", "content": question}],
                            db=object(), student_id="BENCH_STUDENT",
                            course_id=COURSE_ID, session_id="BENCH_THREAD", verbose=False,
                        )
                    per_turn.append({
                        "main_tokens": sum(model.input_tokens[model_start:]),
                        "summary_tokens": sum(summary_model.input_tokens[summary_start:]),
                        "elapsed_ms": (perf_counter() - start) * 1000,
                    })
                    if "第二段资料" in question:
                        checks.append(SECOND_CHUNK_FACT in result["answer"]
                                      and "get_current_course_material_chunk_by_id" in result["called_tools"])
                    elif question.startswith(QUESTION_ID):
                        checks.append(QUESTION_FACT in result["answer"]
                                      and "get_current_course_wrong_question_by_id" in result["called_tools"])
                state = agent.get_state({"configurable": {"thread_id": "BENCH_THREAD"}}).values
                return {
                    "mode": "summary" if enabled else "baseline",
                    "turns": len(questions),
                    "model_calls": len(model.input_tokens),
                    "summary_calls": len(summary_model.input_tokens),
                    "mean_main_input_tokens_per_turn": round(
                        sum(row["main_tokens"] for row in per_turn) / len(per_turn), 1),
                    "mean_total_input_tokens_per_turn": round(
                        sum(row["main_tokens"] + row["summary_tokens"] for row in per_turn)
                        / len(per_turn), 1),
                    "mean_elapsed_ms_per_turn": round(
                        sum(row["elapsed_ms"] for row in per_turn) / len(per_turn), 1),
                    "followup_exact_refetch": f"{sum(checks)}/{len(checks)}",
                    "checkpoint_messages": len(state["messages"]),
                    "last_turn_input_tokens": per_turn[-1]["main_tokens"],
                }
        finally:
            connection.close()


if __name__ == "__main__":
    results = []
    for enabled in (False, True):
        runs = [measure(enabled) for _ in range(3)]
        result = {**runs[0], "timing_runs": len(runs)}
        result["mean_elapsed_ms_per_turn"] = round(mean(
            run["mean_elapsed_ms_per_turn"] for run in runs
        ), 1)
        result["elapsed_ms_per_turn_stdev"] = round(stdev(
            run["mean_elapsed_ms_per_turn"] for run in runs
        ), 1)
        results.append(result)
    print(json.dumps(results, ensure_ascii=True, indent=2))
