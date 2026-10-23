# CoursePilot：课程学习与复习计划助手

CoursePilot 是一个面向教师和学生的教学原型。教师可以管理课程题库、批量导入题目、组卷发布、上传课程资料并批改简答题；学生可以参加考试、查看成绩与错题，再让学习助手依据错题和课程资料生成复习建议或结构化计划。

这是以 **Vibe Coding 辅助开发** 完成的个人项目：使用 AI 辅助需求拆解、编码和调试，关键业务规则、权限边界、证据校验和评测结论仍以代码与测试结果为准。

## 产品演示

推荐按 [演示脚本](docs/product_demo.md) 展示“教师准备题目和资料 → 发布考试 → 学生作答 → 教师批改 → 学生查看错题 → Agent 生成复习计划”。演示需要本地服务、模型密钥和测试账号；这个仓库不包含真实账号、密钥、上传文件、数据库或向量索引。可用截图或录屏展示已准备好的演示环境。

## 技术结构

```text
独立 Web 前端（/web/）→ FastAPI API → Service / Repository → SQLite
                                        ├→ Chroma（课程资料向量索引）
                                        ├→ MCP（资料检索工具）
                                        └→ LangChain / LangGraph（学生助手）
Redis：短期会话缓存；SQLite：业务数据及 Agent checkpoint
```

- 教师题库支持单选、多选、判断、单空填空、简答；客观题及单空填空自动判分，简答由教师批改。
- 资料上传后解析、切分并建立课程范围内的 Chroma 索引；主 embedding 使用百炼，备用 embedding 使用本地 Ollama。检索结果保留来源与片段 ID。
- 学生助手先读取当前学生、当前课程的错题证据；后端校验诊断和计划中的题目、知识点与资料引用。单 Agent 与最小 Multi-Agent 流程可对照。
- 长会话使用摘要、近期完整消息和题目/资料索引卡；追问时按 ID 重新读取原始证据。

## 本地启动（Windows PowerShell）

在 `agentproject` 目录执行。需要 Python 环境、Redis；若要建立备用向量索引，还需本地 Ollama 和 `bge-m3`。模型服务与 Redis 的实际可用性取决于本机配置。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
# 编辑 .env，设置独立的 JWT_SECRET_KEY、DeepSeek 和百炼密钥
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

独立 Web 前端由同一个 FastAPI 进程提供，打开 `http://127.0.0.1:8000/web/`，无需启动 Node 或 Streamlit。根地址会跳转到前端；健康检查在 `/health`，接口文档在 `/docs`。原 Streamlit 页面暂留在 `frontend/` 作为迁移期回退，可单独运行，但 `localhost:8501` 不是新版前端。新环境中管理员可从页面建课、审核教师并授权；参考[三角色业务流程](docs/role_business_flows.md)和[演示脚本](docs/product_demo.md)。不要将本机 `data/` 当成公开演示数据上传。

## 验证与评测边界

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
node web/smoke.test.mjs
.\.venv\Scripts\python.exe -m evals.review_plan_multi_comparison --validate
```

项目有 60 条固定业务回归用例，覆盖完整计划、零错题、资料缺失、部分结果、MCP 故障和会话越权。它们使用固定资料返回，**不代表真实 Chroma 检索质量**。Gold v1 的 20 条独立事实检查仍待人工批准；v3 尚无可引用的 60 对真实模型对照成绩。历史 v2 的 30 例结果见[评测说明](docs/review_plan_comparison_v2.md)，不可冒充 v3 成绩。

更完整的实现说明见[长会话上下文](docs/long_conversation_context.md)、[MCP 资料检索](docs/mcp_course_material.md)、[双 embedding 索引](docs/dual_embedding_index.md)和[多知识点资料](docs/multi_topic_materials.md)。

运行时和评测共用的可复用执行边界见 [Harness 与系统架构](docs/harness_architecture.md)。

