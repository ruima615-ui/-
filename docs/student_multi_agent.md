# 学生复习计划的最小 Multi-Agent 流程

入口为 `POST /api/chat/review-plan-multi`，请求体沿用 `/api/chat` 的
`session_id` 和 `message`。登录学生、会话归属和选课权限仍由原有聊天入口验证。
原有 `POST /api/chat` 继续运行单 Agent，便于使用同一评测集做对照。

```
Coordinator：一次读取后端 Top-2 薄弱点和错题证据
  ├─ 零错题或基础查询失败 → 结束
  ↓
诊断 Agent：证据 → priority_topics / evidence_question_ids / reason / diagnoses
  ↓ 后端核对知识点、题目 ID 和诊断结构
Coordinator：按已校验诊断为各知识点调用 MCP 资料检索
  ├─ 全部不可用 → 结束，不生成无依据任务
  ↓
计划 Agent：已校验诊断 + 课程资料片段 → ReviewTask 候选
  ↓ 后端核对任务知识点、错误类型、优先级和 Chunk ID
Coordinator：输出 ReviewPlanResponse 和 tool_trace
```

关键代码：`app/workflows/student_multi_agent.py` 是显式 LangGraph；
`agent_runner.py` 将其接入现有会话权限和消息保存；
`app/api/chat.py` 提供独立入口。模型工作节点只看 Coordinator 给的
证据，不接触数据库会话或学生 ID。身份和课程 ID 仅保存在图运行配置中，
由 Coordinator 调用已有业务服务及 MCP Client。

诊断/计划校验复用 `review_plan_service.py` 的证据关联和任务校验函数。
资料检索复用 `app/mcp/material_client.py`，不另写向量检索。
任一模型输出不符合 Schema 或引用未授权 ID 时，不把候选计划作为正式结果。
基础查询、检索故障、零错题分别返回受限状态与原因。MCP 连接或检索异常
返回 `material_retrieval_failed`；确无索引资料返回
`course_materials_not_configured`；有索引但无相关片段返回
`course_materials_insufficient`。各知识点组保留原始 `status`。
检索部分成功时，
仅对有真实资料片段的知识点生成任务。

该图本身没有 LangGraph checkpointer。跨轮诊断复用使用现有
`StudentSessionDiagnosis` 快照：按学生、课程、会话读取，经有效期和当前
错题证据指纹校验后复用；过期或证据改变时重新调用诊断 Agent，校验通过后
覆盖快照。每轮仍重新读取后端基础数据并重新检索资料。原单 Agent 的
checkpoint 与此图是两套独立的会话机制。

离线验证：`python -m unittest tests.test_student_multi_agent -v`。
覆盖正常交接、零错题、MCP 故障、非法题目 ID 和基础查询失败。
真实 DeepSeek + MCP 的在线调用尚需使用独立入口和现有评测数据验收；
离线测试不能证明模型在真实环境中的输出质量。
