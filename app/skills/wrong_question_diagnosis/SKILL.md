# 错题错误类型诊断

适用：学生询问错题为什么做错、错误原因或错误类型。先调用 `get_current_course_wrong_questions` 取得当前学生和课程的题干、选项、学生答案、正确答案及解析，再依据本 Skill 诊断。若涉及课程知识解释，读取错题后还要调用 `searchlearningmaterial` 核查资料来源。

## 错误类型

- `concept_misunderstanding`：概念、定义或基本规则理解错误。
- `reasoning_error`：已接触概念，但推理、计算步骤或条件判断出错。
- `knowledge_application_error`：知道概念，但在当前题目或新场景中应用不当。
- `answer_format_error`：内容可能正确，但数据类型、选项形式或提交格式错误。
- `insufficient_evidence`：题干、答案、选项或解析不足，无法可靠判断。

## 证据与置信度

直接证据只能来自工具返回的题干、选项、学生答案、正确答案和解析。推断理由是对这些事实的可能解释，必须使用“可能说明”“与该错误模式一致”或“初步判断”。不得把粗心、态度或心理状态写成事实。题目难度只能用于薄弱程度分析，不能证明具体错误原因。

选择题须用 `options` 把字母还原为选项内容，如“学生选择 D「由列表长度决定」，正确答案为 A「0」”。仅一次错误作答不能确定稳定的认知问题，应说明其他可能。

`confidence` 仅取 `high`、`medium`、`low`：多次独立作答呈现相同模式或有明确错误推理时可用 high；一次作答且错误选项明确对应典型误解时用 medium；一次作答且无法辨明原因时用 low。缺少题干、学生答案、正确答案、选择题选项或必要解析时，使用 `insufficient_evidence` 和 `low`，列出缺失证据，不编造原因。

## 每道题的输出

必须包含 `question_id`、`topic`、`error_type`、`direct_evidence`、`inference_reason`、`alternative_explanations`、`confidence`。在直接证据中列出题干、学生答案、正确答案、解析；推断理由解释证据与初步类型的联系；其他可能说明证据无法排除的解释。只引用当前学生、当前课程工具返回的题目。提交给后端的字段名必须与 `WrongQuestionDiagnosis` Schema 完全一致。

若学生在一段持久会话中要求诊断，并希望后续计划复用：调用 `prepare_current_course_review_plan` 确认当前 Top-2 的完整证据题集合，再把这些题目的结构化诊断提交给 `save_current_course_diagnoses`。只有后端校验并保存成功的诊断可复用；不要保存或反解析最终自然语言回答。此步骤不生成完整计划。
