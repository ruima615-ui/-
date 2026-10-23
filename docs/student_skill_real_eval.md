# 学生 Agent Skills 四例真实模型评测

运行脚本：[`evals/real_student_skill_calls.py`](../evals/real_student_skill_calls.py)。每个问题使用全新会话；`S008` 有 1 次已评分考试、3 次错误作答，`S007` 有 1 次已评分考试、3 次正确作答、0 次错误作答。脚本先复制业务 SQLite，评测消息和 LangGraph checkpoint 只写入运行目录，不修改原始考试数据。

| 用例 | 提问 | 重点核对 |
|---|---|---|
| `weak_topics` | 分析我这门课的薄弱知识点 | 查错题/分析工具；记录是否读取诊断 Skill；不得生成完整计划 |
| `review_plan` | 根据我的错题制定复习计划 | 读取两个 Skill，按准备→诊断校验→定稿顺序调用工具 |
| `list_index` | 这门课程的列表索引是什么意思？ | 调资料检索工具；不读无关的错题诊断 Skill |
| `zero_wrong_plan` | 我没有错题，请根据我的错题制定复习计划 | 核查当前课程错题；不编造薄弱点或无依据计划 |

运行会为每例保存 `question`、`answer`、`called_tools`、`tool_trace`、结构化计划、耗时和规则检查，路径为 `eval_results/real_student_skill_calls_<run_id>/<case_id>.json`。汇总在同目录的 `summary.json`。`tool_trace.result_preview` 遵循现有 `agent_runner.py` 的 500 字符截断，不能当成完整工具结果；结构化计划另存于 `review_plan` 字段。

**状态：尚未完成真实 DeepSeek 运行，因此四例没有新的真实 `tool_trace`。** 自动审批拒绝了把 `S007/S008` 的考试错题与课程资料上下文发送到外部 DeepSeek。脚本已通过语法检查，样本先决条件已核对，规则判定函数已做本地验证。只有取得该具体数据出站授权后，才应运行脚本并据实际轨迹记录通过或失败；不能用离线假模型轨迹冒充真实模型结果。

解释口径：单问“薄弱知识点”应优先查 `analyze_current_course_wrong_questions`。错误**类型诊断** Skill 服务于“为什么做错”，不应仅因提到“薄弱知识点”就强制加载。复习计划则需使用诊断 Skill，并通过后端重新读取错题证据。当前计划工作流没有可靠地复用上一轮独立诊断的结构化结果，这应作为评测观察点，不能因为会话历史里有文字诊断就宣称数据交接已实现。
