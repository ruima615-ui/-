# 课程资料检索 MCP 接入

MCP（Model Context Protocol）把可调用能力表示为带名称、输入 Schema 和结果的工具。Server 提供工具，Client 连接 Server 并发起调用；`stdio` 是本项目使用的本地进程传输方式。协议只规定如何发现和调用工具，不负责课程权限，也不替代检索算法。可参考 [MCP Python SDK 的客户端传输说明](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/client/transports.md)。

本阶段只迁移学生 Agent 的 `searchlearningmaterial` 资料检索工具：

```text
已授权的学生会话 course_id
  → student_agent.searchlearningmaterial(topic, query)
  → app/mcp/material_client.py（MCP Client）
  → stdio → app/mcp/material_server.py（MCP Server）
  → app/services/material_search_service.py
  → 现有 Chroma 双索引 / embedding 降级逻辑
```

Server 的 `search_course_material(course_id, topic, query)` 原样调用已有的 `search_course_materials_with_fallback(..., top_k=3)`，不实现另一套向量检索。Client 只从 Agent 的 `StudentAgentContext` 接收当前会话的 `course_id`；模型只提供 `topic` 和 `query`。错题明细、薄弱点和学生身份仍留在原有业务工具中，MCP Server 不接收学生 ID。此 Server 只作为本地子进程使用；若未来改成网络服务，需要独立增加身份验证和课程授权，不能把当前 `course_id` 参数当作授权凭证。

依赖写在 [`requirements-mcp.txt`](../requirements-mcp.txt)。本机安装的是 `mcp 1.30.0`。可在项目目录运行：

```powershell
..\.venv\Scripts\python.exe -m pip install -r requirements-mcp.txt
..\.venv\Scripts\python.exe -m unittest discover -s tests -q
..\.venv\Scripts\python.exe -m evals.mcp_material_agent_smoke
```

2026-10-10 的联调结果保存在 [MCP Agent 烟测结果](../eval_results/mcp_material_agent_smoke.json)。离线假模型只负责确定性地触发真实 Agent 工具调用；Agent 实际通过 MCP Client/Server 访问现有 Chroma 检索。`tool_trace` 记录 `searchlearningmaterial` 成功调用，完整 MCP 结果的 `status=success`，主索引 `course_material_chunks_primary` 返回 `python_list.md` 的 2 个片段，包含 `chunk_id`、`material_id`、`original_filename`、`source_type` 和片段正文。项目的 105 个单元测试通过。

本次没有完成真实 DeepSeek 驱动的 MCP Agent 联调：自动审批拒绝了将本地课程资料及 Agent 上下文发送到外部 DeepSeek 的运行。离线烟测只证明 Agent→MCP→检索服务的工具链能工作，不证明模型自主选择工具和最终回答质量。此前的单 Agent 真实基线仍保留，便于后续获得外部调用许可后比较。
