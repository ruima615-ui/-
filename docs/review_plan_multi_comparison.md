# 单 Agent 与 Multi-Agent：固定复习计划用例对照

原单 Agent 基线集 `student_agent_baseline_cases.json` 有 10 个案例、11 个轮次，
涉及错题查询、资料讲解、追问与权限，但没有完整复习计划题。Multi-Agent
目前只实现“基于错题制定复习计划”，不能把原集的 11 轮整体通过率直接
拿来比较。因此，这里复用**同一版本化固定数据**
`student-agent-synthetic-v1`，新增三个两条路径均可处理的复习计划问题：
正常计划、零错题、课程资料不可用。两条路径各运行一遍，每例使用独立会话。

评测集：[数据](../evals/fixtures/student_agent_dataset_v1.json)、
[问题](../evals/fixtures/review_plan_comparison_cases_v1.json)、
[运行与评分脚本](../evals/review_plan_multi_comparison.py)。固定数据 SHA-256：
`b5fea1149fde25d102c02b4c609d555eb3d15a42d0fd3a2d7eb2e6865e87c219`。
DeepSeek 使用 `deepseek-chat`。业务 SQLite 为每条路径单独创建，资料片段
由固定数据适配到检索接口；**这里模拟了 MCP 返回值，没有测真实 MCP
进程、Chroma 召回或生产网络可靠性**。

2026-10-12 的运行 ID：`20261012T065946Z_82eebc6e`。
[重评分汇总](../eval_results/review_plan_comparison_20261012T065946Z_82eebc6e.rescored.summary.json)、
[单 Agent 逐例结果](../eval_results/review_plan_comparison_20261012T065946Z_82eebc6e_single.rescored.jsonl)、
[Multi-Agent 逐例结果](../eval_results/review_plan_comparison_20261012T065946Z_82eebc6e_multi.rescored.jsonl)。
原始结果和原始评分也保留。重评分仅修正判定规则，未重新请求模型。

| 指标 | 单 Agent | Multi-Agent |
|---|---:|---:|
| 业务行为规则通过 | 3/3 | 3/3 |
| 正常题完成有资料引用的结构化计划 | 1/1 | 1/1 |
| 零错题核查、无编造任务 | 1/1 | 1/1 |
| 资料不可用、无编造任务 | 1/1 | 1/1 |
| 三例均返回结构化状态 | 1/3 | 3/3 |
| 平均耗时 | 9.987 秒 | 3.243 秒 |
| 中位耗时 | 12.726 秒 | 3.080 秒 |

规则通过检查非空回答、真实工具轨迹、课程隔离、正常题的题目/资料 ID
引用、零错题和无资料时不编造任务。单 Agent 遇到零错题和无资料时，
用文字正确说明并停止，不返回 `review_plan`；这两例计为**业务行为通过**，
但不计为“返回结构化状态”。最初评分误把缺少结构化状态当成业务失败，
原始汇总中的 1/3 因而不是事实正确率；`behavior-v2` 重评分为 3/3。

耗时只是一轮、三个样本的观测值，不能推断稳定的性能优势。
原始 trace 事件数为单 Agent 17、Multi-Agent 15，但 Multi-Agent trace
包含 Coordinator 内部节点，计数口径不同，**不用于工具效率结论**。
两种输出形式也不同：单 Agent 提供较长文字计划，Multi-Agent 的正式任务
在 `review_plan` JSON 中，`answer` 仅是状态说明。语义质量仍标为
`manual_review=pending`。当前未记录两条路径可比的输入/输出 Token、费用、
真实 MCP 延迟或多次运行的方差。

运行：`python -m evals.review_plan_multi_comparison`。仅重新评分已保存结果：
`python -m evals.review_plan_multi_comparison --rescore 20261012T065946Z_82eebc6e`。
