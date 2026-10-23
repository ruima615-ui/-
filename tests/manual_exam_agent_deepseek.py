"""用临时合成考试数据联调真实 DeepSeek；不会写入正式业务数据库。"""

import json

import agent_runner
import app.api.chat as chat_api
from langgraph.checkpoint.memory import InMemorySaver

from student_agent import build_student_agent
from tests.test_exam_to_student_agent_flow import ExamToStudentAgentFlowTests


def require_success(response, step):
    if response.status_code != 200:
        raise RuntimeError(f"{step} 失败：HTTP {response.status_code}：{response.text}")
    return response.json()


def main():
    fixture = ExamToStudentAgentFlowTests(methodName="test_teacher_exam_submission_wrong_record_and_agent_advice")
    fixture.setUp()
    original_run_agent = chat_api.run_agent_with_memory
    def report_agent_error(*args, **kwargs):
        try:
            return original_run_agent(*args, **kwargs)
        except Exception as error:
            print("AGENT_ERROR", type(error).__name__, str(error)[:300])
            raise
    chat_api.run_agent_with_memory = report_agent_error
    try:
        agent_runner.student_agent = build_student_agent(checkpointer=InMemorySaver())
        draft = require_success(fixture.client.post(
            "/api/exams/drafts",
            json={
                "course_id": "COURSE_AGENT_FLOW", "title": "合成列表测验",
                "duration_minutes": 30,
                "items": [{"question_id": "Q_AGENT_FLOW", "points": 5}],
            },
            headers=fixture.headers("T_AGENT_FLOW"),
        ), "教师创建草稿")
        exam_id = draft["exam_id"]
        require_success(fixture.client.post(
            f"/api/exams/{exam_id}/publish",
            headers=fixture.headers("T_AGENT_FLOW"),
        ), "教师发布考试")
        attempt = require_success(fixture.client.post(
            f"/api/exams/{exam_id}/attempts",
            headers=fixture.headers("S_AGENT_FLOW"),
        ), "学生开始考试")
        result = require_success(fixture.client.post(
            f"/api/exams/attempts/{attempt['attempt_id']}/submit",
            json={"answers": [{"question_id": "Q_AGENT_FLOW", "answer": "B"}]},
            headers=fixture.headers("S_AGENT_FLOW"),
        ), "学生提交并判分")
        chat = require_success(fixture.client.post(
            "/api/chat",
            json={
                "session_id": "SESSION_AGENT_FLOW",
                "message": "请查询我当前课程的错题并分析薄弱知识点，根据真实错题给我复习建议。",
            },
            headers=fixture.headers("S_AGENT_FLOW"),
        ), "DeepSeek Agent 回答")
        print(json.dumps({
            "exam_status": "published",
            "attempt_status": result["status"],
            "score": result["total_score"],
            "wrong_question_count": sum(not row["is_correct"] for row in result["answers"]),
            "agent_tools": chat["called_tools"],
            "agent_steps": chat["steps"],
            "agent_answer": chat["answer"],
        }, ensure_ascii=True))
    finally:
        chat_api.run_agent_with_memory = original_run_agent
        fixture.tearDown()


if __name__ == "__main__":
    main()
