# 有证据的结构化复习计划

适用：学生要求完整复习计划、结构化计划或综合复习建议。必须按以下顺序执行，不能跳步：

1. 调用 `prepare_current_course_review_plan`。后端固定选 Top-2 薄弱知识点和每个知识点至多两道错题，并返回 `diagnosis_handoff`。不得自行更改 Top-K 或添加工具结果之外的知识点。如果无已记录错题，说明无法依据错题生成针对性计划，不编造薄弱点。
2. 如果 `diagnosis_handoff.status=reused`，调用 `validate_current_course_diagnoses` 时省略 `diagnoses` 参数，由后端读取并复核已保存的结构化诊断；否则按 `wrong_question_diagnosis` Skill 为每道证据题重新诊断，传入 `diagnoses`。不要从助手的历史自然语言回答中反解析。后端会校验题目及知识点、检索对应课程资料；只使用通过校验的诊断和资料证据。
3. 对 `material_groups` 中 `status=success` 的每个知识点生成且只生成一个 `ReviewTask`。`task_id` 唯一；`topic`、`priority_rank` 照抄工具；`related_error_types` 只能取已校验诊断；`material_chunk_ids` 只能取该知识点 `material_evidence` 的真实 ID。`objective` 结合薄弱点和错误类型，`action_steps` 基于课程资料，`self_check_questions` 用于完成后的自测。
4. 调用 `finalize_current_course_review_plan`。可省略 `diagnoses` 参数，让后端再次读取并核验本会话保存的诊断；传入 `review_tasks`。只有后端返回的 `ReviewPlanResponse` 是正式计划，不能直接把模型候选任务当成最终结果。

如果资料状态为 `course_materials_not_configured`，或 MCP/检索返回失败或无相关片段，明确说明资料不足，不生成没有来源依据的任务。回答应列明题目和资料片段来源，并说明样本量限制。
