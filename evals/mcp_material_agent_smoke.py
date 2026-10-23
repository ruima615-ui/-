"""Offline model drives a real Agent -> MCP -> Chroma tool call."""

import json
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

import agent_runner
import student_agent as student_agent_module
from app.core.database import SessionLocal
from app.mcp.material_client import search_material
from student_agent import build_student_agent


class ToolCallingFakeChatModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        return self


def main() -> None:
    started = perf_counter()
    captured = []

    def capture_real_mcp_call(*, course_id, topic, query):
        result = search_material(course_id=course_id, topic=topic, query=query)
        captured.append(result)
        return result

    model = ToolCallingFakeChatModel(responses=[
        AIMessage(content="", tool_calls=[{
            "name": "searchlearningmaterial",
            "args": {"topic": "Python列表", "query": "列表索引从哪里开始"},
            "id": "mcp-material-smoke-call",
        }]),
        AIMessage(content="课程资料检索工具已返回结果；请核对工具轨迹中的状态和来源。"),
    ])
    with SessionLocal() as db, patch.object(
        agent_runner, "student_agent", build_student_agent(model=model, checkpointer=None)
    ), patch.object(student_agent_module, "search_course_material", capture_real_mcp_call):
        result = agent_runner.run_agent(
            messages=[{"role": "user", "content":
                       "请检索当前课程 Python列表 的学习资料，解释列表索引从哪里开始，并给出资料来源。"}],
            db=db,
            student_id="S008",
            course_id="PYTHON101",
            verbose=False,
        )
    material_calls = [item for item in result["tool_trace"]
                      if item["tool_name"] == "searchlearningmaterial"]
    if not material_calls or not any(
        '"status": "success"' in item["result_preview"] for item in material_calls
    ) or not captured or not captured[0].get("retrieved_chunks"):
        raise RuntimeError("Agent did not receive a successful MCP material result")
    output = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "course_id": "PYTHON101", "student_id": "S008",
        "model": "offline_fake_tool_caller",
        "mcp_server_tool": "search_course_material",
        "agent_tool": "searchlearningmaterial",
        "answer": result["answer"], "called_tools": result["called_tools"],
        "tool_trace": result["tool_trace"],
        "mcp_result": captured[0],
        "elapsed_s": round(perf_counter() - started, 3),
    }
    path = Path(__file__).resolve().parents[1] / "eval_results" / "mcp_material_agent_smoke.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"path": str(path), "called_tools": output["called_tools"],
                      "elapsed_s": output["elapsed_s"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
