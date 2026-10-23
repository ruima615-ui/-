# Harness 与系统架构

`app/harness/` 是项目内可复用的执行边界，不包含错题诊断 Prompt、知识点规则或课程资料索引逻辑。

## 两种 harness

- `AgentRuntimeHarness`：注入数据库会话、单 Agent、上下文读写、单/多 Agent 执行器。统一校验学生身份、会话所有权与状态、课程状态和选课关系；单 Agent 从 checkpoint 或消息库恢复上下文；只有执行成功后才保存本轮用户和助手消息。`agent_runner.run_agent_with_memory()` 保留原有入口并装配这些依赖，API 和现有评测无需更改调用方式。
- `EvaluationHarness`：接受任意用例、`invoke` 回调、评分器和失败诊断器；统一捕获执行异常、耗时和可选的模型 Token 用量，返回 `EvaluationOutcome`。`evals/review_plan_multi_comparison.py` 将自己的固定数据、评分规则和失败字段注入其中。其他评测可复用执行边界，但应定义自己的 Gold 与评分规则。

两者分离：运行时 harness 不知道评测用例；评测 harness 不查询生产数据库。评测脚本用隔离 SQLite、固定资料返回和注入模型运行同一运行时入口。`--validate` 只检查固定数据，不请求真实模型；正式对照运行才会请求模型。评测结果的业务规则通过率不等于资料召回质量或教学质量。

## 当前层次

```text
独立 Web 前端 web/（同源静态页面）
  → FastAPI app/api/（认证、身份与 HTTP 输入输出）
    → app/harness/runtime.py（会话范围、执行、持久化）
      → agent_runner.py（具体单/多 Agent 适配）
        → student_agent.py（默认单 Agent 与工具）
        → app/workflows/student_multi_agent.py（按需调用的 Coordinator → 诊断 → 计划）
    → app/services/（课程、试题、考试、错题、计划等业务规则）
      → app/repositories/ + app/models/（SQLite 持久化）
      → app/mcp/ + rag_tools.py（课程资料 MCP 检索与 Chroma 索引）
evals/（固定数据、独立评分、报告）
  → app/harness/evaluation.py（用例执行与指标采集）
  → 同一 agent_runner.py 入口
```

普通 `/api/chat` 使用单 Agent；`/api/chat/review-plan-multi` 才运行 Multi-Agent。前者有 SQLite LangGraph checkpoint 和消息存储；后者的图是请求内流程，跨轮复用经已校验诊断快照完成。Redis 是短期消息缓存，SQLite 是业务记录和长期消息的来源；Chroma 保存课程资料向量索引。此项目是一个 FastAPI 应用，不是微服务系统。

## 验证

```powershell
..\.venv\Scripts\python.exe -m unittest tests.test_harness tests.test_agent_loop tests.test_agent_checkpoint tests.test_review_plan_comparison_v3 -v
..\.venv\Scripts\python.exe -m evals.review_plan_multi_comparison --validate
```
