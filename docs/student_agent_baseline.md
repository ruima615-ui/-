# 学生助手单 Agent 基线评测

## 评测目标与边界

固定一组可重复的业务问题，记录学生助手的最终回答、工具调用顺序、完整 `tool_trace`、错误和耗时。评测覆盖错题查询、薄弱点分析、课程资料讲解、多工具调用、连续追问、跨课程请求、资料不可用、无错题和会话越权。

评测调用真实的 `deepseek-chat` 和学生助手业务入口 `run_agent_with_memory()`。学生、课程、试卷、作答和错题从版本化的[固定数据集](../evals/fixtures/student_agent_dataset_v1.json)写入**临时 SQLite**；资料检索返回同一数据集中的固定模拟片段。因此，它验证 Agent 编排、业务查询、会话追问和权限边界，**不衡量 Chroma 检索召回率或真实部署的网络可靠性**。评测不会修改项目的业务数据库。

固定数据集 ID 为 `student-agent-synthetic-v1`，SHA-256 为 `b5fea1149fde25d102c02b4c609d555eb3d15a42d0fd3a2d7eb2e6865e87c219`。它包含 3 名虚构学生、2 门课程、3 道题、2 张试卷、2 次已评分考试、3 条错误作答及对应错题、3 份模拟资料和 4 个片段。时间戳固定为 `2026-09-01T10:00:00`。`load_dataset()` 在运行前核对学生选课、试卷题目课程归属、作答与标准答案、错题与错误作答的一一对应，以及资料片段 ID/位置的唯一性；不一致时停止评测。每次新运行的汇总还记录数据集 ID 和文件哈希。若修改数据内容，应建立新版本，不能拿旧结果直接横向比较。

这组证据是**可复现的合成样本**，不是匿名化真实学生记录；其“可信”指引用关系、答案与错题事实可核验，不代表样本覆盖真实教学分布或检索质量。

## 固定用例和判定方式

用例存放在 [`evals/student_agent_baseline_cases.json`](../evals/student_agent_baseline_cases.json)，共 9 个案例、10 个提问轮次。追问案例在同一会话内先取得两个资料片段，再要求重新读取第二段的 `chunk_id`。跨课程案例含另一课程的秘密题目，用于检查是否泄漏其正文；会话越权案例使用不属于请求学生的会话。

[`evals/fixed_dataset.py`](../evals/fixed_dataset.py) 负责固定数据校验、临时 SQLite 装载和模拟资料读取；[`evals/student_agent_baseline.py`](../evals/student_agent_baseline.py) 负责运行 Agent、逐轮评分与保存结果。评分检查回答是否非空、要求的工具是否调用及顺序、禁止工具是否未调用、显式事实是否出现或泄漏、降级文案、预期异常，以及 `called_tools` 与 `tool_trace` 是否一致。规则通过率**不是**语义正确率；回答的解释是否充分、推断是否谨慎仍需人工检查。原始结果的 `manual_review` 保持 `pending`，避免把规则通过误写为人工验收通过。

运行方式（在 `agentproject` 目录、已配置 DeepSeek 环境变量的虚拟环境中）：

```powershell
..\.venv\Scripts\python.exe -m evals.student_agent_baseline --validate-cases
..\.venv\Scripts\python.exe -m evals.student_agent_baseline
```

每次运行在 `eval_results/` 写入逐轮 JSONL 和汇总 JSON。逐轮记录包含 `question`、`expected`、`answer`、`called_tools`、`tool_trace`、`checks`、`elapsed_s` 和异常类型，便于事后人工复核和版本间比较。运行时仍需保持用例、模型配置和评分规则一致；若变更其中任何一项，应作为新版本评测，不覆盖旧结果。

## 2026-10-08 首轮结果

运行编号 `20261008T095243Z_e7147d2e`。逐轮原始记录：[JSONL](../eval_results/student_agent_baseline_20261008T095243Z_e7147d2e.jsonl)；[汇总](../eval_results/student_agent_baseline_20261008T095243Z_e7147d2e.summary.json)。

| 指标 | 结果 |
|---|---:|
| 案例 / 提问轮次 | 9 / 10 |
| 自动规则通过 | 9 / 10（90%） |
| 工具调用总次数 | 10 |
| 平均 / 中位单轮耗时 | 2.42 / 2.39 秒 |
| 单轮耗时总和 | 24.17 秒 |

错题查询、薄弱点分析、资料讲解、多工具调用、两轮连续追问、跨课程请求、资料不可用和会话越权均通过预设规则。追问第二段时，Agent 调用 `get_current_course_material_chunk_by_id` 重新读取 `M_LIST:chunk:2`；跨课程请求未调用数据工具，未输出秘密题目正文；会话越权在进入 Agent 前被业务入口拒绝。

唯一未通过的是“无错题”案例：当时的预设规则要求调用 `get_current_course_wrong_questions`，实际只调用 `analyze_current_course_wrong_questions`。该工具返回零错题，回答也正确说明“无记录不能推断已掌握全部内容”。因此这是**工具路径不符合当时的预设**，目前没有观察到该轮事实错误。原始失败记录保留；修订后的产品契约见下一节。

## 零错题规则修订（基线 v2）

已明确产品契约：用户自称“没有错题”也必须由 Agent 调用当前课程工具核查。查询具体错题用明细工具；询问薄弱点用分析工具。如果分析工具已返回 `no_recorded_wrong_questions`，可以直接回答，不要求再调用明细工具。无错题回答只能表示当前没有**已记录**的错题，不能断言学生已掌握全部内容。

固定集新增“用户自称零错题”案例；原有“无错题”案例改为允许两种工具之一，但要求 `tool_trace` 出现 `no_recorded_wrong_questions`。这是**新版本规则**，不重算上方首轮的 9/10。2026-10-08 的一次 v2 联调记录为 [`20261008T110033Z_4488b07a.jsonl`](../eval_results/student_agent_baseline_20261008T110033Z_4488b07a.jsonl)：10 个需调用 DeepSeek 的轮次全部因 `OpenAIConnectionError` 中断，另 1 个会话越权案例按预期在调用模型前被拒绝。该次结果属于连接失败，不能用其中的自动通过率评价 Agent 行为；需在模型连接恢复后重新运行 v2 固定集。

人工阅读本轮回答还发现：薄弱点分析对每个知识点仅有一次作答的样本限制有说明；多工具回答引用了题目 ID 和资料片段 ID；资料不可用时没有编造来源。这些是本轮样本的观察，不代表所有开放式问题均安全或正确。

## 下一步

下一步用匿名化的真实课程材料替换模拟片段，另建检索质量集，测 `course_id` 隔离、Top-K 相关性和引用准确率。比较单 Agent 的后续版本时保留原始结果和评分变更记录。

连接故障已定位为当前环境的 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY` 指向本机代理，但代理拒绝连接。仅在评测进程中清除这些代理环境变量后，v2 于 2026-10-08 成功完成真实 DeepSeek 调用：[逐轮结果](../eval_results/student_agent_baseline_20261008T110434Z_7b87fee8.jsonl)、[汇总](../eval_results/student_agent_baseline_20261008T110434Z_7b87fee8.summary.json)。10 个案例、11 个轮次的自动规则全部通过。新增的“用户自称零错题”轮次实际调用了 `analyze_current_course_wrong_questions`，工具返回 `no_recorded_wrong_questions` 后才回答。此通过率仍限于固定用例和规则检查，不等于开放问题的语义准确率。
