# 已校验诊断的跨轮交接

本改动只处理同一学生、同一课程、同一会话中的**结构化诊断**复用，不从助手历史回答文本中反解析薄弱点。

## 数据流

```text
本轮错题证据 → 模型提交 WrongQuestionDiagnosis 列表
    → 后端核对 Top-2 知识点、每道题 ID 与 topic、数量和 Schema
    → 保存到 student_session_diagnoses
下一轮准备计划 → 后端重新读取考试作答与 Top-2 错题证据
    → 核对 user_id + course_id + session_id、24 小时有效期、证据指纹
    → 合格则返回 diagnosis_handoff.status=reused 和 diagnoses
    → 不合格则返回失效原因和空 diagnoses，由模型依据本轮证据重新诊断
```

[`app/models/entities.py`](../app/models/entities.py) 新增 `StudentSessionDiagnosis`，联合主键为 `user_id + course_id + session_id`，保存结构化诊断 JSON、证据指纹和 UTC 校验时间。[迁移脚本](../app/migrate_session_diagnosis_handoff.py)已在当前 `education.db` 上执行；迁移前快照在 `data/education_before_diagnosis_handoff_20261011.db`。新表当前为空，只有后续真实会话通过诊断校验才会写入。

[`app/services/diagnosis_handoff_service.py`](../app/services/diagnosis_handoff_service.py) 负责保存和读取。证据指纹包含课程范围、Top-2 排序与统计、选中错题的题干/答案/解析，以及该学生本课程所有考试作答的状态和答案。因此即使 Top-2 题目暂未改变，新增或修改考试作答也会使缓存失效。读取时再次校验保存的诊断与当前题目集合一一对应；检索资料失败不会抹去已经校验的错题诊断。这里的“校验”保证结构和引用归属，不保证模型推断的错误类型在语义上必然正确。

[`student_agent.py`](../student_agent.py) 新增 `save_current_course_diagnoses` 工具，供独立错题诊断回合提交结构化结果。`prepare_current_course_review_plan` 返回 `diagnosis_handoff`；后续 `validate_current_course_diagnoses` 和 `finalize_current_course_review_plan` 可省略 `diagnoses` 参数，让后端读取并再次核验保存结果。失效时返回 `diagnoses_required`，模型必须根据本轮证据重新提交诊断。`agent_runner.py` 把经授权会话的 `session_id` 注入运行上下文；没有会话 ID 的调用不能写入跨轮诊断。

[`wrong_question_diagnosis/SKILL.md`](../app/skills/wrong_question_diagnosis/SKILL.md) 和 [`grounded_review_plan/SKILL.md`](../app/skills/grounded_review_plan/SKILL.md) 写明保存、读取与失效后的执行步骤。Skill 只指导调用顺序；能否复用由后端决定。

测试覆盖同会话复用、跨学生/课程拒绝、题目答案变化、其他考试作答变化、24 小时过期、未选中题目拒绝及资料不可用时保存诊断。该阶段不调用 DeepSeek；真实模型是否按 Skill 先保存、后复用，仍需后续用相邻两轮对话的 `tool_trace` 验收。
