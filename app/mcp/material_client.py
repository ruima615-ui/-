"""MCP client used by the student's course-scoped material tool."""

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


PROJECT_DIR = Path(__file__).resolve().parents[2]
TOOL_NAME = "search_course_material"


async def search_material_async(*, course_id: str, topic: str, query: str) -> dict:
    # The server is a local process; PYTHONPATH makes module loading independent
    # of the web server's working directory. No student data is sent.
    forwarded = (
        "PATH", "SystemRoot", "WINDIR", "TEMP", "TMP",
        "DASHSCOPE_API_KEY", "DASHSCOPE_BASE_URL", "DASHSCOPE_TRUST_ENV",
        "PRIMARY_EMBEDDING_MODEL", "BACKUP_EMBEDDING_MODEL",
        "EMBEDDING_DIMENSION", "OLLAMA_EMBED_URL",
    )
    environment = {key: os.environ[key] for key in forwarded if key in os.environ}
    existing_path = os.environ.get("PYTHONPATH")
    environment["PYTHONPATH"] = str(PROJECT_DIR) + (
        os.pathsep + existing_path if existing_path else ""
    )
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp.material_server"],
        cwd=PROJECT_DIR,
        env=environment,
    )
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                TOOL_NAME,
                arguments={"course_id": course_id, "topic": topic, "query": query},
            )
    if result.isError:
        raise RuntimeError("MCP material search tool returned an error")
    if isinstance(result.structuredContent, dict):
        return result.structuredContent
    for block in result.content:
        if block.type == "text":
            parsed = json.loads(block.text)
            if isinstance(parsed, dict):
                return parsed
    raise ValueError("MCP material search returned no structured result")


def search_material(*, course_id: str, topic: str, query: str) -> dict:
    """Sync bridge for the existing LangChain tool."""
    try:
        return asyncio.run(search_material_async(
            course_id=course_id, topic=topic, query=query,
        ))
    except Exception as exc:
        return {
            "status": "mcp_unavailable",
            "course_id": course_id,
            "topic": topic,
            "message": f"Course material MCP call failed: {type(exc).__name__}",
        }
