# 真实考试后的单 Agent 基线（2026-10-10）

本基线使用 `PYTHON101` 现有已评分考试记录，不造题、不修改成绩。`S008` 的 1 次已评分考试有 3 道错题（`PY_LIST_001`、`PY_LIST_002`、`PY_RETURN_001`）；`S007` 的 1 次已评分考试有 3 次正确作答、0 道错题。两人均选修该课程。

运行脚本是 [`evals/real_exam_single_agent_baseline.py`](../evals/real_exam_single_agent_baseline.py)。它先用 SQLite backup API 保存业务库快照，在快照中创建独立评测会话；LangGraph checkpoint 也放在独立目录。Redis 短期缓存被隔离，避免旧会话污染；Agent、DeepSeek、实际课程资料和 Chroma 检索没有模拟。先预检资料索引，再在同一有错题会话中依次询问薄弱点、课程资料、完整复习计划；另开零错题会话核查。逐轮保存回答、完整 `tool_trace`、工具列表、结构化计划、耗时和异常。

运行命令（在 `agentproject` 目录）：

```powershell
Remove-Item Env:HTTP_PROXY,Env:HTTPS_PROXY,Env:ALL_PROXY -ErrorAction SilentlyContinue
..\.venv\Scripts\python.exe -m evals.real_exam_single_agent_baseline
```

本次成功运行编号 `20261010T124107Z_5defb25a`。原始逐轮结果在 [JSONL](../eval_results/real_exam_single_agent_20261010T124107Z_5defb25a.jsonl)，来源证据、规则检查和人工复核在 [汇总 JSON](../eval_results/real_exam_single_agent_20261010T124107Z_5defb25a.summary.json)，当时的业务库副本及会话 checkpoint 在 `eval_results/real_exam_single_agent_20261010T124107Z_5defb25a.snapshot/`。快照 SHA-256 是 `fa8377877dd6ac39e4770fcb02937634a0c2d12e0b1b4c6ad0f1dc4bb80a3376`。

| 会话 | 轮次 | 实际路径 | 耗时 |
|---|---:|---|---:|
| S008 | 1 | 薄弱点分析、错题明细、两次课程资料检索 | 7.154 秒 |
| S008 | 2 | 按 chunk ID 读取四段原文 | 5.793 秒 |
| S008 | 3 | 准备计划、校验诊断、定稿计划 | 27.622 秒 |
| S007 | 1 | 薄弱点工具核查，返回 `no_recorded_wrong_questions` | 4.293 秒 |

四轮合计 44.862 秒。S008 的定稿工具返回 `success`，计划引用的题目 ID 都在该学生真实错题集合中；S007 没有编造薄弱知识点，也没有生成无证据计划。**发现一处需要后续修复的回答错误**：S007 的回答说“总作答次数：0”，但快照里实际有 3 次已评分且全部正确的作答。当前分析工具在零错题情况下给出的统计口径不足，Agent 把“可用于错题分析的作答数为零”写成了“总作答数为零”。因此本次记录是带已知缺陷的基线，不应宣称答案完全正确。

首次尝试在有错题检索时遇到 Chroma `default_tenant` 连接失败，失败原始记录也保留在 `eval_results/real_exam_single_agent_20261010T*.jsonl`。加入独立预检后用全新会话成功重跑；失败后的 checkpoint 不继续复用，避免不完整工具消息造成模型 400 错误。对比后续版本时，应保留同样的学生/课程/题目、提问顺序及评分口径，并同时检查结构化引用和人工阅读答案。`tool_trace.result_preview` 由现有 `agent_runner.py` 截断至 500 字符，完整结构化定稿另见逐轮记录中的 `review_plan`。
