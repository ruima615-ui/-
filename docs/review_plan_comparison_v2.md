# 复习计划对照评测集 v2（30 例）

本版本沿用 v1 的业务数据结构，但新建独立的
[`student_agent_dataset_v2.json`](../evals/fixtures/student_agent_dataset_v2.json)
和 [`review_plan_comparison_cases_v2.json`](../evals/fixtures/review_plan_comparison_cases_v2.json)。
旧版文件与 2026-10-12 的三例评测结果保持不变。新数据由
[`build_review_plan_dataset_v2.py`](../evals/build_review_plan_dataset_v2.py)
从 v1 确定性生成；文件 SHA-256 为
`390da91564c1e748b7bcc412dbf51ade2c6f3692f4b9e698ad4bd32f5b6a073a`。

固定数据有 10 名虚构学生、2 门课程、12 道题（11 道单选、1 道判断）、
4 张试卷、15 次已评分考试、20 条按学生/课程/题目去重的错题、
7 份资料及 9 个片段。包含单知识点、多知识点、重复错误作答、
完全正确、未参加考试、同时选两门课程、缺少题目解析等不同证据状态。

30 个用例分布如下：

| 预期状态 | 用例数 | 主要检验 |
|---|---:|---|
| `success` | 16 | Top-2、证据上限、课程范围、资料引用、任务生成 |
| `no_recorded_wrong_questions` | 5 | 无考试、全对、自述零错题、拒绝编造 |
| `course_materials_not_configured` | 4 | 未索引资料、缺少该知识点资料 |
| `partial` | 2 | 一个知识点资料可用，另一个缺失 |
| `course_materials_insufficient` | 1 | 已索引但无相关片段 |
| `material_retrieval_failed` | 1 | 检索服务抛异常 |
| `PermissionError` | 1 | 学生无权使用他人的会话 |

用例包含 25 个细分类别。同一知识点有少量不同问题措辞，但主要扩充的是
**证据与失败条件**，不是简单复制同一条问题 30 次。所有问题都限定在
“基于错题制定复习计划”范围，才能对单 Agent 与当前只支持计划任务的
Multi-Agent 使用相同输入。
每个授权用例还冻结了 `expected_topics`、`expected_evidence_ids`、
`expected_task_topics` 和预期状态。运行前用真实业务服务核对这些预期，
避免业务数据变化后评测脚本悄悄采用新的答案。

评测入口仍为 [`review_plan_multi_comparison.py`](../evals/review_plan_multi_comparison.py)。
脚本会按相同数据和问题分别运行两种架构，保存逐例回答、计划、工具轨迹、
规则检查和耗时。资料片段由固定数据模拟检索返回；这不是 Chroma 召回率
或真实 MCP 传输测试。单 Agent 的降级结论可能仅写在文字中，因此评分将
业务行为和结构化 `review_plan.status` 分开记录。语义内容仍需人工复核。

已执行的离线验收：固定数据引用与 SHA 校验、30 例格式校验；
29 个授权用例分别用脚本化模型运行完整 Multi-Agent 图并核对预期状态，
第 30 个用例验证会话所有权拒绝。**此项离线验收没有请求 DeepSeek**。
以下记录了完整的真实模型 30 对实测结果；不能引用旧 v1 三例的通过率或耗时
作为 v2 成绩。

## 首次真实模型运行（2026-10-12）

已启动 30 例、两种架构各一轮，共 60 条评测记录。运行 ID 为
`20261012T074801Z_7fe57452`，逐例原始结果与
[汇总](../eval_results/review_plan_comparison_20261012T074801Z_7fe57452.summary.json)
已保存。单 Agent 前两例完成结构化计划；第三例遇到
`GraphRecursionError`；从第四例起 DeepSeek 返回 HTTP 402
`Insufficient Balance`。单 Agent 有 26 条 402；Multi-Agent 的 24 条
模型依赖用例将 API 异常降级为 `insufficient_evidence`；5 条零错题用例
无需模型，仍得到后端空结果。

**该轮不能计算可信的单/多 Agent 通过率或性能差异。**汇总已标记
`run_valid_for_architecture_comparison=false`。为避免后续额度故障被计作
Agent 错误，评测脚本在首次 402 时停止并保留已完成的逐例结果。
余额恢复后已用新运行 ID 重跑整套 v2；递归上限问题单独计入本轮 Agent 失败。

## 余额恢复后的完整运行（2026-10-12）

使用同一份 v2 固定数据和 30 个问题重新运行，运行 ID 为
`20261012T082346Z_cf888b38`。逐例记录保存在
[`single.jsonl`](../eval_results/review_plan_comparison_20261012T082346Z_cf888b38_single.jsonl)、
[`multi.jsonl`](../eval_results/review_plan_comparison_20261012T082346Z_cf888b38_multi.jsonl)，
规则检查及指标见[汇总](../eval_results/review_plan_comparison_20261012T082346Z_cf888b38.summary.json)。
本轮没有 HTTP 402，汇总标记 `run_valid_for_architecture_comparison=true`。

| 自动指标 | 单 Agent | Multi-Agent |
|---|---:|---:|
| 规则全部通过 | 22/30（73.3%） | 20/30（66.7%） |
| 平均耗时 | 10.471 秒 | 4.293 秒 |
| 中位耗时 | 11.542 秒 | 4.427 秒 |
| 平均轨迹事件数 | 4.20 | 4.83 |

单 Agent 的 8 个未通过用例中，5 个是 `GraphRecursionError`，另有
`ValueError`、模拟 MCP 连接异常各 1 个；剩下 1 个未满足预期的检索轨迹检查。
Multi-Agent 的 10 个未通过用例中，7 个没有形成预期状态的可信计划
（多为 `insufficient_evidence`），3 个没有满足资料不可用/检索尝试检查。
这说明现阶段不能声称 Multi-Agent 质量优于单 Agent；它在此样本上的速度
更快，但自动通过率略低。耗时包含各路径的工具调用与模型调用，因流程不同，
平均轨迹事件数也不是成本或质量的直接替代指标。

这些是一次运行、30 个固定用例的**规则检查**结果，不代表统计显著性，
也不能代替人工审查诊断理由、课程资料相关性和复习任务的教学质量。
检索片段由固定数据模拟，故本轮没有测量 Chroma 召回或真实 MCP 网络可靠性。
后续应优先修复递归上限与 Multi-Agent 的 `insufficient_evidence` 误降级，
再在相同数据、相同评分规则下重跑并保留新的运行 ID。

### Multi-Agent 七个计划失败用例定位

以下逐例定位依据是本轮 `multi.jsonl` 保存的 `tool_trace`、最终计划和冻结预期。
轨迹只保存异常**类型**，未保存具体异常消息或被拒绝的候选结构。因此可以确认
失败节点，不能从这份记录倒推出模型究竟填错了哪个字段。

| 用例 | 预期 | 已确认的最后成功步骤 | 失败节点及异常 | 本轮实际结果 |
|---|---|---|---|---|
| `main_rank_limit` | `success`，布尔判断和 Python 列表 | 基础证据读取，3 道题 | `diagnosis_agent`：`ValueError` | 未执行 MCP 检索；无诊断、无任务 |
| `main_repeat_error` | `success`，同上 | 基础证据读取，3 道题 | `diagnosis_agent`：`ValidationError` | 未执行 MCP 检索；无诊断、无任务 |
| `list_single_topic` | `success`，Python 列表 | 2 道诊断通过；MCP 返回 2 个列表片段 | `plan_agent`：`ValueError` | 保留诊断和资料证据，无任务 |
| `function_single_topic` | `success`，函数返回值 | 基础证据读取，2 道题 | `diagnosis_agent`：`ValidationError` | 未执行 MCP 检索；无诊断、无任务 |
| `function_two_rules` | `success`，函数返回值 | 2 道诊断通过；MCP 返回 1 个函数片段 | `plan_agent`：`ValueError` | 保留诊断和资料证据，无任务 |
| `main_short_request` | `success`，布尔判断和 Python 列表 | 基础证据读取，3 道题 | `diagnosis_agent`：`ValidationError` | 未执行 MCP 检索；无诊断、无任务 |
| `mixed_partial_material` | `partial`，仅 Python 字典任务 | 3 道诊断通过；字典片段可用，函数资料未索引 | `plan_agent`：`ValueError` | 保留诊断和字典片段，无任务 |

四例在诊断阶段停止，三例在计划阶段停止。诊断阶段的 `ValueError` 可能由
知识点/题目 ID 与后端证据不一致或诊断数量、归属校验失败引起；
`ValidationError` 表明结构化输出或诊断 Schema 校验失败，但具体字段未知。
计划阶段的 `ValueError` 发生在候选计划生成或 `validate_review_tasks()`
校验过程中；可能涉及任务数量、知识点、优先级、错误类型或 Chunk 引用，
不能凭异常类型锁定其中一项。在这次历史运行时，工作流捕获异常后仅把类名
写入轨迹，`finish` 又将 `diagnosis_failed`/`plan_failed` 统一映射为
`insufficient_evidence`。后续已增加具体校验记录和独立失败状态，见下节。

现已增加评测专用的 `failure_diagnostic` 字段。下一次运行生成的逐例 JSONL
在失败时记录：`stage`（模型输出、Schema、后端证据/任务校验或评测规则）、
`error_type`、`rule` 和 `candidate_fields`。后者只包含知识点、题目 ID、
错误类型、任务数与 Chunk ID 等必要字段，不保存学生答案、诊断理由或资料正文。
若模型调用期间就失败，`candidate_fields` 为 `null`；若工作流返回但自动规则
未通过，则 `rule` 列出未通过的评测检查项。该字段仅在评测调用时开启，
默认学生会话的 `tool_trace` 和保存的消息不包含这些调试细节。
上述历史运行文件不会被追写，必须用新的运行 ID 才能获得具体校验原因。

### 失败状态区分与定向复测（2026-10-12）

该工作流现在保留 `foundation_failed`、`diagnosis_failed`、`plan_failed` 作为
`ReviewPlanResponse.status`；在该工作流中，`insufficient_evidence` 用于证据不足。
学生端分别收到“错题数据暂不可读”“诊断未通过校验”“计划生成或校验失败”
等提示，不再把模型或流程失败说成学生证据不足。详细原因仍只在评测文件中。

使用相同 v2 固定数据，先定向重跑原先的 7 个 Multi-Agent 计划失败用例：
[首轮结果](../eval_results/review_plan_comparison_20261012T114855Z_94854a12.summary.json)
为 6/7 通过。`function_two_rules` 的失败记录明确显示：模型对同一个
“函数返回值”知识点提交了 2 项任务，后端规则要求每个具备资料的知识点
恰好 1 项。其余 6 例本轮通过，说明原先的失败具有模型输出波动性，
不能将旧的异常类名当成稳定的字段级根因。

据此给计划 Agent 增加 `eligible_groups`、`required_task_count` 和允许引用的
Chunk ID，并明确“一知识点一任务、错题再多也合并”。对诊断/任务的结构或
业务校验失败，最多允许一次修正重试；模型连接错误不重试，后端证据校验
仍为最终边界。再次定向重跑同 7 例的[结果](../eval_results/review_plan_comparison_20261012T115241Z_b2dcba31.summary.json)
为 6/7 通过，`function_two_rules` 已通过；`main_short_request` 在诊断阶段
两次都没有得到可解析的结构化输出，记录为 `diagnosis_failed`，候选为 `null`。
因此当前改动改善了具体的重复任务问题，但尚未证明 7 例可稳定全过。
这些文件均标记为 `targeted_diagnostic_run=true`，不能用来替代完整的
30 对架构评测。修复结构化输出的稳定性后，应对同一 7 例做多次重复运行，
再重跑完整 30 例。

评测入口现默认指向 [v3 的 60 例](review_plan_comparison_v3.md)。复跑此处 v2
时需要显式指定两份 v2 文件：

```powershell
..\.venv\Scripts\python.exe -m evals.review_plan_multi_comparison --validate --cases evals/fixtures/review_plan_comparison_cases_v2.json --dataset evals/fixtures/student_agent_dataset_v2.json
..\.venv\Scripts\python.exe -m unittest tests.test_review_plan_comparison_v2 -v
# 需要运行 30 对真实模型请求时：
..\.venv\Scripts\python.exe -m evals.review_plan_multi_comparison --cases evals/fixtures/review_plan_comparison_cases_v2.json --dataset evals/fixtures/student_agent_dataset_v2.json
```
