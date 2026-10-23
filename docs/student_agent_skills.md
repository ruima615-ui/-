# 学生 Agent Skills 复用（第一版）

本项目的 Skill 是**可复用的任务说明文件**，不是新的数据查询接口。MCP 负责把课程资料检索服务暴露为工具；Skill 负责告诉 Agent 某类任务何时调用哪些工具、如何使用证据。数据权限仍由业务会话和工具控制，复习计划的合法性仍由后端服务校验。

当前有两个 Skill：

| ID | 文件 | 内容 |
|---|---|---|
| `wrong_question_diagnosis` | [`app/skills/wrong_question_diagnosis/SKILL.md`](../app/skills/wrong_question_diagnosis/SKILL.md) | 错误类型、证据边界、置信度和诊断输出 |
| `grounded_review_plan` | [`app/skills/grounded_review_plan/SKILL.md`](../app/skills/grounded_review_plan/SKILL.md) | Top-2 分析→诊断校验→资料检索→任务定稿 |

[`app/skills/registry.py`](../app/skills/registry.py) 是读取入口，只接受固定的 Skill ID；不接受用户提供的文件路径。其他 Agent 如需复用，可调用同一个 `read_student_skill(skill_id)`，或把此注册表作为自己的读取工具数据源。Skill 不包含学生个人资料，返回的是固定说明文本。

[`student_agent.py`](../student_agent.py) 的系统提示词现在保留任务路由、零错题核查、来源和权限底线。需要诊断或完整计划时，Agent 应先调用 `load_student_skill` 读取相应说明，再使用现有错题、MCP 资料检索和计划校验工具。这样详细规则只在相关任务中进入会话上下文。此前长提示词中的诊断细则和复习任务细则已迁入上述文件。

单元测试覆盖 Skill 白名单、规则内容和 Agent 工具循环中的实际加载调用。它们不证明真实 DeepSeek 每次都会按提示先加载 Skill；后续应在已有单 Agent 基线上增加包含诊断和计划的工具顺序评测，并与迁移前的回答、`tool_trace` 比较。如果需要**强制**先加载 Skill，须在后端工作流增加门控，不能只依赖提示词。

运行：

```powershell
..\.venv\Scripts\python.exe -m unittest tests.test_student_skills -q
..\.venv\Scripts\python.exe -m unittest discover -s tests -q
```
