import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain_core.language_models.fake_chat_models import (
    FakeMessagesListChatModel,
)
from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite import SqliteSaver

import agent_runner
from student_agent import build_student_agent


class ToolCallingFakeChatModel(FakeMessagesListChatModel):
    """让固定回复模型满足 create_agent() 的工具绑定接口。"""

    def bind_tools(
        self,
        tools,
        *,
        tool_choice=None,
        **kwargs,
    ):
        return self


def create_persistent_test_agent(database_file, responses):
    """创建使用临时 SQLite checkpoint 的无网络 Agent。"""

    connection = sqlite3.connect(
        str(database_file),
        check_same_thread=False,
    )
    checkpointer = SqliteSaver(connection)
    checkpointer.setup()

    model = ToolCallingFakeChatModel(
        responses=responses,
    )
    agent = build_student_agent(
        model=model,
        checkpointer=checkpointer,
    )

    return connection, agent


class AgentCheckpointTests(unittest.TestCase):
    def test_same_thread_survives_agent_recreation(self):
        """同一 thread_id 两轮后，新 Agent 仍能恢复旧消息。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            database_file = (
                Path(temp_dir) / "checkpoints.db"
            )
            thread_id = "SESSION_CHECKPOINT_001"

            connection_1, agent_1 = (
                create_persistent_test_agent(
                    database_file,
                    [
                        AIMessage(content="first answer"),
                        AIMessage(content="second answer"),
                    ],
                )
            )

            try:
                with patch.object(
                    agent_runner,
                    "student_agent",
                    agent_1,
                ):
                    first_result = agent_runner.run_agent(
                        messages=[{
                            "role": "user",
                            "content": "first question",
                        }],
                        db=object(),
                        student_id="STUDENT_001",
                        course_id="COURSE_001",
                        session_id=thread_id,
                        verbose=False,
                    )
                    second_result = agent_runner.run_agent(
                        messages=[{
                            "role": "user",
                            "content": "second question",
                        }],
                        db=object(),
                        student_id="STUDENT_001",
                        course_id="COURSE_001",
                        session_id=thread_id,
                        verbose=False,
                    )

                self.assertEqual(
                    first_result["answer"],
                    "first answer",
                )
                self.assertEqual(
                    second_result["answer"],
                    "second answer",
                )
                self.assertEqual(first_result["steps"], 1)
                self.assertEqual(second_result["steps"], 1)
            finally:
                connection_1.close()

            # 使用同一文件和 thread_id 创建全新的连接及 Agent，
            # 模拟应用重启后的状态恢复。
            connection_2, agent_2 = (
                create_persistent_test_agent(
                    database_file,
                    [AIMessage(content="third answer")],
                )
            )

            try:
                config = {
                    "configurable": {
                        "thread_id": thread_id,
                    }
                }
                restored_state = agent_2.get_state(config)
                restored_contents = [
                    message.content
                    for message in restored_state.values.get(
                        "messages",
                        [],
                    )
                ]

                self.assertIn(
                    "first question",
                    restored_contents,
                )
                self.assertIn(
                    "first answer",
                    restored_contents,
                )
                self.assertIn(
                    "second question",
                    restored_contents,
                )
                self.assertIn(
                    "second answer",
                    restored_contents,
                )

                with patch.object(
                    agent_runner,
                    "student_agent",
                    agent_2,
                ):
                    third_result = agent_runner.run_agent(
                        messages=[{
                            "role": "user",
                            "content": "third question",
                        }],
                        db=object(),
                        student_id="STUDENT_001",
                        course_id="COURSE_001",
                        session_id=thread_id,
                        verbose=False,
                    )

                self.assertEqual(
                    third_result["answer"],
                    "third answer",
                )
                self.assertEqual(third_result["steps"], 1)
            finally:
                connection_2.close()

    def test_different_threads_are_isolated(self):
        """不同 thread_id 不能读取彼此的消息状态。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            database_file = (
                Path(temp_dir) / "checkpoints.db"
            )
            connection, agent = (
                create_persistent_test_agent(
                    database_file,
                    [
                        AIMessage(content="answer for A"),
                        AIMessage(content="answer for B"),
                    ],
                )
            )

            try:
                with patch.object(
                    agent_runner,
                    "student_agent",
                    agent,
                ):
                    agent_runner.run_agent(
                        messages=[{
                            "role": "user",
                            "content": "question from A",
                        }],
                        db=object(),
                        student_id="STUDENT_A",
                        course_id="COURSE_001",
                        session_id="SESSION_A",
                        verbose=False,
                    )
                    agent_runner.run_agent(
                        messages=[{
                            "role": "user",
                            "content": "question from B",
                        }],
                        db=object(),
                        student_id="STUDENT_B",
                        course_id="COURSE_001",
                        session_id="SESSION_B",
                        verbose=False,
                    )

                state_a = agent.get_state({
                    "configurable": {
                        "thread_id": "SESSION_A",
                    }
                })
                state_b = agent.get_state({
                    "configurable": {
                        "thread_id": "SESSION_B",
                    }
                })

                contents_a = {
                    message.content
                    for message in state_a.values.get(
                        "messages",
                        [],
                    )
                }
                contents_b = {
                    message.content
                    for message in state_b.values.get(
                        "messages",
                        [],
                    )
                }

                self.assertEqual(
                    contents_a,
                    {"question from A", "answer for A"},
                )
                self.assertEqual(
                    contents_b,
                    {"question from B", "answer for B"},
                )
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
