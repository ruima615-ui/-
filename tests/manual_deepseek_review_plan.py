"""使用完全合成数据验收 DeepSeek 的复习计划工具调用链。"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from dotenv import load_dotenv
from langchain_core.messages import AIMessage
from langchain_core.messages import ToolMessage

from app.schemas.review_plan import ReviewPlanResponse
from app.services.review_plan_service import (
    associate_diagnoses_with_weak_topics,
    validate_review_tasks,
)
from student_agent import StudentAgentContext
from student_agent import build_student_agent


load_dotenv()


WEAK_TOPICS = [
    {
        "topic": "合成列表知识点",
        "priority_rank": 1,
        "priority_level": "high",
        "priority_score": 0.9,
        "wrong_attempts": 2,
        "total_attempts": 2,
        "error_rate": 1.0,
        "difficulty_distribution": {
            "easy": 1,
            "medium": 1,
            "hard": 0,
        },
        "analysis_basis": "exam_history",
    },
    {
        "topic": "合成函数知识点",
        "priority_rank": 2,
        "priority_level": "high",
        "priority_score": 0.8,
        "wrong_attempts": 1,
        "total_attempts": 1,
        "error_rate": 1.0,
        "difficulty_distribution": {
            "easy": 0,
            "medium": 1,
            "hard": 0,
        },
        "analysis_basis": "exam_history",
    },
]

WRONG_EVIDENCE = [
    {
        "question_id": "SYNTH_LIST_1",
        "topic": "合成列表知识点",
        "stem": "合成题：列表首项索引是多少？",
        "student_answer": "1",
        "correct_answer": "0",
        "explanation": "合成解析：首项索引为0。",
    },
    {
        "question_id": "SYNTH_FUNCTION_1",
        "topic": "合成函数知识点",
        "stem": "合成题：函数无返回语句时返回什么？",
        "student_answer": "空字符串",
        "correct_answer": "None",
        "explanation": "合成解析：默认返回None。",
    },
]

MATERIAL_EVIDENCE = [
    {
        "topic": "合成列表知识点",
        "source_id": "SYNTH_MATERIAL_LIST",
        "source_title": "合成列表讲义",
        "source_type": "official",
        "original_filename": "synthetic_list.md",
        "chunk_id": "SYNTH_CHUNK_LIST",
        "section": "列表索引",
        "page_number": None,
        "content_excerpt": "合成资料：列表首项索引为0，末项正索引为长度减1。",
        "relevance_score": 0.95,
    },
    {
        "topic": "合成函数知识点",
        "source_id": "SYNTH_MATERIAL_FUNCTION",
        "source_title": "合成函数讲义",
        "source_type": "official",
        "original_filename": "synthetic_function.md",
        "chunk_id": "SYNTH_CHUNK_FUNCTION",
        "section": "默认返回值",
        "page_number": None,
        "content_excerpt": "合成资料：函数没有显式返回值时，Python默认返回None。",
        "relevance_score": 0.94,
    },
]


def foundation() -> dict:
    return {
        "status": "success",
        "scope": {
            "course_id": "SYNTHETIC_COURSE",
            "top_k": 2,
        },
        "selected_topic_count": 2,
        "weak_topics": WEAK_TOPICS,
        "wrong_question_evidence": WRONG_EVIDENCE,
        "diagnosis_groups": [
            {
                "topic": item["topic"],
                "priority_rank": item["priority_rank"],
                "evidence": [
                    evidence
                    for evidence in WRONG_EVIDENCE
                    if evidence["topic"] == item["topic"]
                ],
            }
            for item in WEAK_TOPICS
        ],
        "execution_trace": [
            "analyze_current_course_wrong_questions",
            "get_current_course_wrong_questions",
        ],
    }


def grounded(diagnoses: list[dict]) -> dict:
    validated = associate_diagnoses_with_weak_topics(
        weak_topics=WEAK_TOPICS,
        wrong_question_evidence=WRONG_EVIDENCE,
        diagnoses=diagnoses,
    )
    return {
        **foundation(),
        "diagnoses": validated,
        "material_evidence": MATERIAL_EVIDENCE,
        "material_groups": [
            {
                "topic": topic["topic"],
                "priority_rank": topic["priority_rank"],
                "status": "success",
                "query": f"{topic['topic']} 合成查询",
                "evidence": [
                    evidence
                    for evidence in MATERIAL_EVIDENCE
                    if evidence["topic"] == topic["topic"]
                ],
            }
            for topic in WEAK_TOPICS
        ],
        "limitations": [],
    }


def fake_prepare(**kwargs) -> dict:
    return foundation()


def fake_ground(*, diagnoses, **kwargs) -> dict:
    return grounded(diagnoses)


def fake_finalize(*, diagnoses, review_tasks, **kwargs) -> dict:
    plan = grounded(diagnoses)
    validated_tasks = validate_review_tasks(
        grounded_plan=plan,
        review_tasks=review_tasks,
    )
    return ReviewPlanResponse(
        status="success",
        scope=plan["scope"],
        weak_topics=plan["weak_topics"],
        wrong_question_evidence=plan["wrong_question_evidence"],
        diagnoses=plan["diagnoses"],
        material_evidence=plan["material_evidence"],
        review_tasks=validated_tasks,
        limitations=[],
    ).model_dump()


def main() -> None:
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise RuntimeError("DEEPSEEK_API_KEY 未配置")

    agent = build_student_agent(
        checkpointer=None,
    )
    with (
        patch(
            "student_agent.prepare_review_plan_foundation",
            side_effect=fake_prepare,
        ),
        patch(
            "student_agent.prepare_grounded_review_plan",
            side_effect=fake_ground,
        ),
        patch(
            "student_agent.finalize_grounded_review_plan",
            side_effect=fake_finalize,
        ),
    ):
        result = agent.invoke(
            {
                "messages": [{
                    "role": "user",
                    "content": "请根据合成错题生成完整结构化复习计划。",
                }],
            },
            config={"recursion_limit": 14},
            context=StudentAgentContext(
                db=object(),
                student_id="SYNTHETIC_STUDENT",
                course_id="SYNTHETIC_COURSE",
            ),
        )

    called_tools = []
    final_plan = None
    final_answer = None
    for message in result["messages"]:
        if isinstance(message, AIMessage):
            called_tools.extend(
                call["name"]
                for call in message.tool_calls
            )
            if not message.tool_calls:
                final_answer = message.text
        elif (
            isinstance(message, ToolMessage)
            and message.name
            == "finalize_current_course_review_plan"
            and message.status != "error"
        ):
            final_plan = json.loads(message.text)

    print(json.dumps(
        {
            "called_tools": called_tools,
            "review_plan_status": (
                final_plan.get("status")
                if final_plan
                else None
            ),
            "review_task_count": (
                len(final_plan["review_tasks"])
                if final_plan
                else 0
            ),
            "final_answer_present": bool(final_answer),
        },
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()
