"""离线测量学生 Agent 的会话消息增长；不访问模型网络。"""

import sqlite3
import tempfile
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite import SqliteSaver

import agent_runner
from app.core.config import AGENT_CHECKPOINT_FILE
from app.memory.tool_result_compaction import compact_old_tool_results
from student_agent import build_student_agent


class RecordingFakeModel(FakeMessagesListChatModel):
    input_sizes: list[tuple[int, int]] = []

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.input_sizes.append((
            len(messages),
            sum(len(str(message.content)) for message in messages),
        ))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def measure_existing_checkpoint():
    uri = AGENT_CHECKPOINT_FILE.as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        rows = connection.execute(
            "SELECT thread_id, MAX(checkpoint_id) FROM checkpoints GROUP BY thread_id"
        ).fetchall()
        saver = SqliteSaver(connection)
        measurements = []
        for thread_id, _ in rows:
            state = saver.get_tuple({"configurable": {"thread_id": thread_id}})
            if not state:
                continue
            messages = state.checkpoint.get("channel_values", {}).get("messages", [])
            text_chars = sum(len(str(message.content)) for message in messages)
            compacted_chars = sum(
                len(str(message.content))
                for message in compact_old_tool_results(messages)
            )
            kinds = dict(Counter(type(message).__name__ for message in messages))
            longest = max((len(str(message.content)) for message in messages), default=0)
            measurements.append((len(messages), text_chars, compacted_chars, longest, kinds))
        measurements.sort(reverse=True)
        print("EXISTING", {"threads": len(measurements), "largest": measurements[:5]})
    finally:
        connection.close()


def measure_simulated_conversation():
    with tempfile.TemporaryDirectory() as temp_dir:
        connection = sqlite3.connect(str(Path(temp_dir) / "checkpoints.db"), check_same_thread=False)
        saver = SqliteSaver(connection)
        saver.setup()
        model = RecordingFakeModel(responses=[
            AIMessage(content="答复" * 100, id=f"reply-{turn}")
            for turn in range(1, 46)
        ])
        summary_model = FakeMessagesListChatModel(responses=[
            AIMessage(content="学生正在复习列表索引，后续问题需要按课程资料和错题 ID 核对。")
        ])
        agent = build_student_agent(
            model=model, checkpointer=saver, summary_model=summary_model,
        )
        try:
            with patch.object(agent_runner, "student_agent", agent):
                for turn in range(1, 46):
                    agent_runner.run_agent(
                        messages=[{"role": "user", "content": f"第{turn}轮：" + "问题" * 300}],
                        db=object(), student_id="MEASURE_STUDENT", course_id="MEASURE_COURSE",
                        session_id="MEASURE_THREAD", verbose=False,
                    )
                    if turn in {1, 5, 10, 20, 30, 40, 45}:
                        state = agent.get_state({"configurable": {"thread_id": "MEASURE_THREAD"}})
                        messages = state.values["messages"]
                        print("SIMULATED", {
                            "turn": turn,
                            "checkpoint_messages": len(messages),
                            "checkpoint_content_chars": sum(len(str(m.content)) for m in messages),
                            "model_input_messages": model.input_sizes[-1][0],
                            "model_input_content_chars": model.input_sizes[-1][1],
                        })
        finally:
            connection.close()


if __name__ == "__main__":
    measure_existing_checkpoint()
    measure_simulated_conversation()
