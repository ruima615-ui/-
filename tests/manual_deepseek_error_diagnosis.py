"""使用合成错题进行一次真实 DeepSeek 错误诊断联调。

本脚本不会读取项目数据库，也不会发送真实学生数据。
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

import agent_runner
import student_agent as student_agent_module
from student_agent import build_student_agent


def synthetic_wrong_question_details(
    db,
    student_id,
    course_id,
):
    return {
        "status": "success",
        "student_id": student_id,
        "course_id": course_id,
        "total_wrong_questions": 1,
        "wrong_questions": [
            {
                "question_id": "SYNTHETIC_LIST_001",
                "topic": "Python列表",
                "question_type": "single_choice",
                "difficulty": "medium",
                "difficulty_score": 4,
                "stem": "长度为 3 的 Python 列表，最大合法索引是多少？",
                "options": {
                    "A": "1",
                    "B": "2",
                    "C": "3",
                    "D": "4",
                },
                "student_answer": "C",
                "correct_answer": "B",
                "explanation": (
                    "Python 列表索引从 0 开始，"
                    "长度为 3 时合法索引是 0、1、2。"
                ),
                "mistake": "学生选择了索引 3。",
                "recorded_at": "2026-10-05T12:00:00",
            }
        ],
    }


def synthetic_course_material(
    course_id,
    topic,
    query,
):
    return {
        "status": "success",
        "course_id": course_id,
        "topic": topic,
        "source": "synthetic_python_list.md",
        "retrieved_chunks": [
            {
                "content": (
                    "Python 列表长度为 n 时，"
                    "合法正向索引范围是 0 到 n-1。"
                )
            }
        ],
    }


def main():
    real_agent = build_student_agent()

    with (
        patch.object(
            agent_runner,
            "student_agent",
            real_agent,
        ),
        patch.object(
            student_agent_module,
            "get_course_wrong_question_details",
            synthetic_wrong_question_details,
        ),
        patch.object(
            student_agent_module,
            "search_course_material",
            synthetic_course_material,
        ),
    ):
        result = agent_runner.run_agent(
            messages=[
                {
                    "role": "user",
                    "content": (
                        "请诊断我为什么做错这道题。"
                        "请按题目编号、初步错误类型、直接证据、"
                        "推断理由、其他可能和置信度回答。"
                    ),
                }
            ],
            db=object(),
            student_id="SYNTHETIC_STUDENT",
            course_id="SYNTHETIC_COURSE",
            verbose=False,
        )

    print(json.dumps(
        result,
        ensure_ascii=False,
        indent=2,
        default=str,
    ))

    if (
        "get_current_course_wrong_questions"
        not in result["called_tools"]
    ):
        raise AssertionError(
            "DeepSeek 没有先读取具体错题证据"
        )

    allowed_error_types = {
        "concept_misunderstanding",
        "reasoning_error",
        "knowledge_application_error",
        "answer_format_error",
        "insufficient_evidence",
    }

    if not any(
        error_type in result["answer"]
        for error_type in allowed_error_types
    ):
        raise AssertionError(
            "DeepSeek 没有输出允许的错误类型"
        )

    for required_text in (
        "SYNTHETIC_LIST_001",
        "直接证据",
        "推断理由",
        "其他可能",
        "置信度",
        "medium",
    ):
        if required_text not in result["answer"]:
            raise AssertionError(
                f"诊断回答缺少字段：{required_text}"
            )


if __name__ == "__main__":
    main()
