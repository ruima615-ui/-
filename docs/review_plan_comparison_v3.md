# 复习计划对照评测集 v3（60 例）

本版本将固定资料返回的单 Agent / Multi-Agent 对照集从 30 例扩为 60 例。
它继续评估业务证据、计划状态、资料引用和失败分支；**不评估真实 Chroma
召回质量**。旧版 v2 数据和运行结果保持不变。

评测数据见 [`student_agent_dataset_v3.json`](../evals/fixtures/student_agent_dataset_v3.json)，
用例见 [`review_plan_comparison_cases_v3.json`](../evals/fixtures/review_plan_comparison_cases_v3.json)。
可用 [`build_review_plan_dataset_v3.py`](../evals/build_review_plan_dataset_v3.py) 从 v2
确定性重建。数据文件 SHA-256：
`6a501a6b574297dd65ba1af654ca4232db3cf24886ac1a73580cbaa2b5a5d252`；
用例文件 SHA-256：
`13a7411abc99d88bf53776a3416873ce761d293455ff1c66ba5b1fc702d623aa`。

v3 有 15 名虚构学生、2 门课程、16 道题、28 次已评分考试、38 条按
学生/课程/题目去重的错题、11 份固定资料和 13 个片段。新增 5 名学生有
循环、字典、列表切片、函数重复错误和四知识点混合等不同错题分布。
新增 30 条问题分别覆盖正常计划、Top-2、同主题多规则、部分资料、
全部资料未索引、无相关片段、MCP 故障、零错题和会话越权。
这些资料仍由评测脚本固定返回，不经过真实向量检索。

| 冻结预期 | 用例数 |
|---|---:|
| 完整计划 `success` | 30 |
| 零错题 `no_recorded_wrong_questions` | 7 |
| 资料未索引 `course_materials_not_configured` | 7 |
| 部分计划 `partial` | 7 |
| 无相关资料 `course_materials_insufficient` | 4 |
| 检索故障 `material_retrieval_failed` | 3 |
| 会话越权 `PermissionError` | 2 |

每条非越权用例保存预期知识点、错题证据 ID、计划任务知识点和状态。
生成 v3 时使用 `prepare_review_plan_foundation()` 计算并冻结预期；
运行前评测脚本再用业务服务核对，避免后续数据变化造成隐形评分漂移。
[`test_review_plan_comparison_v3.py`](../tests/test_review_plan_comparison_v3.py)
还对 60 条用例运行脚本化诊断和计划流程，检查所有预期状态与任务主题。

从项目目录执行：

```powershell
..\.venv\Scripts\python.exe -m evals.review_plan_multi_comparison --validate
..\.venv\Scripts\python.exe -m unittest tests.test_review_plan_comparison_v3 -v
# 调用 DeepSeek、两种架构各运行 60 条，并生成新的逐例 JSONL 和汇总：
..\.venv\Scripts\python.exe -m evals.review_plan_multi_comparison
```

评测入口默认使用 v3。要复跑旧版 v2，明确传入
`--cases evals/fixtures/review_plan_comparison_cases_v2.json`
和 `--dataset evals/fixtures/student_agent_dataset_v2.json`。
目前只完成了数据构建与离线验收，**尚无 v3 的 60 对真实 DeepSeek 运行结果**，
不能把 v2 的 30 例通过率沿用到 v3。

## Gold v1 草稿与独立核验

从 60 条用例中分层选出 20 条，形成
[`review_plan_gold_v1.json`](../evals/fixtures/review_plan_gold_v1.json)：
10 条完整计划、2 条零错题、2 条资料未索引、2 条部分计划、1 条无相关资料、
1 条 MCP 故障、2 条会话越权。对应的
[人工复核表](review_plan_gold_v1_review_sheet.md)展示提问、学生/课程、
原始错误作答次数、证据题干与学生/正确答案，便于逐项审核。

[`check_review_plan_gold_v1.py`](../evals/check_review_plan_gold_v1.py)
**直接读取固定考试作答与资料清单**，不调用复习计划业务服务，核对证据题目
是否真实答错、是否属于当前学生和课程、任务知识点是否有固定资料、零错题
与越权场景是否成立。这是独立的确定性检查，但还不能独立判定 Top-2 排序
是否教学上合理，更不能替代人工判断诊断理由或任务质量。

当前检查结果：20 个唯一用例，原始数据检查错误为 0，人工批准为 0，
`gold_ready=false`。`review` 字段全部保留 `pending_human`；只有审核人
填写并批准知识点优先级、证据选择、状态和可接受资料 ID 后，才能把
这一版称为通过人工复核的 Gold。重建脚本会覆盖草稿，**人工审核完成后
不得再运行重建脚本覆盖已批准标注**。

```powershell
..\.venv\Scripts\python.exe -m evals.check_review_plan_gold_v1
..\.venv\Scripts\python.exe -m unittest tests.test_review_plan_gold_v1 -v
```

这份 Gold 草稿仍使用固定资料返回。真实 RAG 的相关性标准答案需要另行
对实际索引片段标注，不能把本评测的固定片段返回当作召回质量证据。
