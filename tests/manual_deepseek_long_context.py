"""真实 DeepSeek 长会话小样本；仅使用合成资料、错题和临时 checkpoint。

运行：python -m tests.manual_deepseek_long_context
需要 DEEPSEEK_API_KEY；会发送合成会话并产生实际 API 调用费用。
"""

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_deepseek import ChatDeepSeek
from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import Field

import agent_runner
from student_agent import build_student_agent
from tests.manual_benchmark_long_context import (
    CHUNKS, COURSE_ID, QUESTION_FACT, QUESTION_ID, SECOND_CHUNK_FACT,
    _material_chunk, _material_result, _wrong_questions,
)


class MeasuredDeepSeek(ChatDeepSeek):
    input_tokens_seen: list[int] = Field(default_factory=list)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        result = super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        usage = result.generations[0].message.usage_metadata or {}
        self.input_tokens_seen.append(int(usage.get("input_tokens") or 0))
        return result


def seeded_messages():
    material = _material_result(course_id=COURSE_ID, topic="Python列表", query="索引边界")
    wrong = _wrong_questions(db=object(), student_id="BENCH_STUDENT", course_id=COURSE_ID)
    messages = [
        HumanMessage(content="请查看 Python 列表索引资料和 Q03 错题。"),
        AIMessage(content="", tool_calls=[
            {"name": "searchlearningmaterial", "args": {
                "topic": "Python列表", "query": "索引边界",
            }, "id": "seed-material"},
            {"name": "get_current_course_wrong_questions", "args": {},
             "id": "seed-wrong"},
        ]),
        ToolMessage(content=json.dumps(material, ensure_ascii=False),
                    tool_call_id="seed-material", name="searchlearningmaterial"),
        ToolMessage(content=json.dumps(wrong, ensure_ascii=False),
                    tool_call_id="seed-wrong", name="get_current_course_wrong_questions"),
        AIMessage(content="已查看两段资料和 Q03 错题。"),
    ]
    for turn in range(1, 19):
        messages.extend([
            HumanMessage(content=f"第 {turn} 轮继续学习列表索引。" + "请结合边界说明。" * 45),
            AIMessage(content="列表索引应检查范围。" * 35),
        ])
    return messages


def measure(enabled):
    model = MeasuredDeepSeek(model="deepseek-chat", api_key=os.environ["DEEPSEEK_API_KEY"],
                             temperature=0, max_retries=2)
    summary_model = MeasuredDeepSeek(model="deepseek-chat", api_key=os.environ["DEEPSEEK_API_KEY"],
                                     temperature=0, max_retries=2)
    results = []
    with tempfile.TemporaryDirectory() as temp_dir:
        connection = sqlite3.connect(str(Path(temp_dir) / "checkpoint.db"), check_same_thread=False)
        try:
            saver = SqliteSaver(connection)
            saver.setup()
            agent = build_student_agent(model=model, summary_model=summary_model,
                                        checkpointer=saver,
                                        enable_conversation_summary=enabled)
            config = {"configurable": {"thread_id": "LIVE_BENCH_THREAD"}}
            agent.update_state(config, {"messages": seeded_messages()})
            with patch("student_agent.get_course_wrong_question_details", side_effect=_wrong_questions), \
                 patch("student_agent.load_course_material_chunk", side_effect=_material_chunk), \
                 patch("student_agent.search_course_material", side_effect=_material_result), \
                 patch.object(agent_runner, "student_agent", agent):
                for question, expected, tool in [
                    ("刚才同一次检索的第二段资料讲了什么？请按片段 ID 重新读取后回答。",
                     SECOND_CHUNK_FACT, "get_current_course_material_chunk_by_id"),
                    ("请重新读取 Q03，解释我为什么做错。",
                     QUESTION_FACT, "get_current_course_wrong_question_by_id"),
                ]:
                    main_start, summary_start = len(model.input_tokens_seen), len(summary_model.input_tokens_seen)
                    started = perf_counter()
                    result = agent_runner.run_agent(
                        messages=[{"role": "user", "content": question}],
                        db=object(), student_id="BENCH_STUDENT", course_id=COURSE_ID,
                        session_id="LIVE_BENCH_THREAD", verbose=False,
                    )
                    results.append({
                        "question": "second_chunk" if tool.endswith("chunk_by_id") else "question_q03",
                        "correct": expected in result["answer"] and tool in result["called_tools"],
                        "called_tools": result["called_tools"],
                        "main_input_tokens": sum(model.input_tokens_seen[main_start:]),
                        "summary_input_tokens": sum(summary_model.input_tokens_seen[summary_start:]),
                        "elapsed_s": round(perf_counter() - started, 2),
                        "answer_excerpt": result["answer"][:80],
                    })
            if enabled and not any(item["summary_input_tokens"] for item in results):
                raise AssertionError("合成会话未达到摘要触发条件，结果不可用于压缩对照")
            return {"mode": "summary" if enabled else "baseline", "cases": results}
        finally:
            connection.close()


if __name__ == "__main__":
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("DEEPSEEK_API_KEY is required")
    print(json.dumps([measure(False), measure(True)], ensure_ascii=True, indent=2))
