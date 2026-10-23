# 考试到学生助手业务链路验收（2026-10-08）

## 范围与结果

在当前运行的本机 FastAPI（127.0.0.1:8000）与 Streamlit（127.0.0.1:8501）上，
使用唯一 `LIVE_ACCEPT_` 前缀的临时课程、管理员、教师、学生和三道题执行验收：

1. 后端和前端健康接口均返回 HTTP 200。
2. 教师自助注册、管理员审核并分配课程，教师经 Streamlit 登录。
3. 教师在 Streamlit 中以题目 ID 组卷并发布试卷。
4. 学生经课程 API 选修、再经 Streamlit 登录并看到试卷；试卷接口不泄露标准答案。
5. 学生提交单选、多选、判断题，判分结果为错、对、错，得分 1/3，生成两条错题。
6. 学生在该课程创建会话并经实际 `/api/chat` 请求调用 DeepSeek；Agent 调用了
   `analyze_current_course_wrong_questions`、`get_current_course_wrong_questions`、
   `searchlearningmaterial`，回答包含两道错题 ID。

运行命令：

```powershell
E:\heima\.venv\Scripts\python.exe -m tests.manual_live_exam_acceptance
```

脚本在 `finally` 中按临时 ID 清理其创建的业务数据和对应 checkpoint；结束后核查
临时用户、课程、题目均为 0。自动化运行的 Streamlit 界面使用 `AppTest` 操作，
可证明组件和 HTTP 交互，不代表人工浏览器的视觉验收。

验收期间发现混合答案（字符串、列表、布尔值）在成绩表同列显示时触发 Arrow 转换告警。
前端现将展示用答案统一格式化为 JSON 字符串；针对该展示运行 AppTest 后无异常或
Arrow 转换告警。

## 本次历史验收后的扩展

历史验收时正式组卷/自动判分只支持单选、多选、判断。后续已补充单空填空的
自动判分与简答题教师人工批改；新流程及测试见
[`teacher_question_bank.md`](teacher_question_bank.md) 和
[`test_fill_blank_short_answer_grading.py`](../tests/test_fill_blank_short_answer_grading.py)。

历史验收时教师后台通过输入已有题目 ID 组卷。此后已增加 CSV 批量录题、
按知识点筛选题库并勾选组卷；智能自动组卷仍未实现。以上新功能不计入本次
历史验收结论，以新功能各自的回归测试为准。
