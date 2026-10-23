import unittest
from unittest.mock import patch

from app.services.review_plan_service import (
    prepare_review_plan_foundation,
)


def make_topic(
    topic: str,
    score: float,
) -> dict:
    return {
        "topic": topic,
        "priority_level": "high",
        "priority_score": score,
        "wrong_attempts": 3,
        "total_attempts": 4,
        "error_rate": 0.75,
        "difficulty_distribution": {
            "easy": 1,
            "medium": 2,
            "hard": 0,
        },
        "analysis_basis": "exam_history",
    }


class ReviewPlanWorkflowTests(unittest.TestCase):
    def test_fixed_top_two_and_service_call_order(self):
        calls = []

        def fake_analyze(db, student_id, course_id):
            calls.append("analyze")
            return {
                "status": "success",
                "topic_analysis": [
                    make_topic("Python列表", 0.90),
                    make_topic("函数返回值", 0.80),
                    make_topic("循环", 0.70),
                ],
            }

        def fake_details(db, student_id, course_id):
            calls.append("details")
            return {
                "status": "success",
                "wrong_questions": [
                    {
                        "question_id": "LIST_1",
                        "topic": "Python列表",
                        "stem": "列表第一个索引是什么？",
                        "options": {
                            "A": "0",
                            "B": "1",
                        },
                        "student_answer": "B",
                        "correct_answer": "A",
                        "explanation": "列表索引从0开始。",
                    },
                    {
                        "question_id": "RETURN_1",
                        "topic": "函数返回值",
                        "stem": "没有return时返回什么？",
                        "options": {
                            "A": "None",
                            "B": "0",
                        },
                        "student_answer": "B",
                        "correct_answer": "A",
                        "explanation": "默认返回None。",
                    },
                    {
                        "question_id": "LIST_2",
                        "topic": "Python列表",
                        "stem": "长度为3的列表最大索引是什么？",
                        "options": {
                            "A": "2",
                            "B": "3",
                        },
                        "student_answer": "B",
                        "correct_answer": "A",
                        "explanation": "最大索引是长度减1。",
                    },
                    {
                        "question_id": "LIST_3",
                        "topic": "Python列表",
                        "stem": "第三个元素的索引是什么？",
                        "options": None,
                        "student_answer": "3",
                        "correct_answer": "2",
                        "explanation": "索引从0开始。",
                    },
                    {
                        "question_id": "LOOP_1",
                        "topic": "循环",
                        "stem": "循环题",
                        "options": None,
                        "student_answer": "错误答案",
                        "correct_answer": "正确答案",
                        "explanation": "循环解析",
                    },
                ],
            }

        with (
            patch(
                "app.services.review_plan_service."
                "analyze_course_wrong_questions",
                side_effect=fake_analyze,
            ),
            patch(
                "app.services.review_plan_service."
                "get_course_wrong_question_details",
                side_effect=fake_details,
            ),
        ):
            result = prepare_review_plan_foundation(
                db=object(),
                student_id="S007",
                course_id="PYTHON101",
            )

        self.assertEqual(calls, ["analyze", "details"])
        self.assertEqual(result["scope"]["top_k"], 2)
        self.assertEqual(
            [item["topic"] for item in result["weak_topics"]],
            ["Python列表", "函数返回值"],
        )
        self.assertEqual(
            [
                item["question_id"]
                for item in result["wrong_question_evidence"]
            ],
            ["LIST_1", "LIST_2", "RETURN_1"],
        )
        self.assertEqual(
            result["wrong_question_evidence"][0][
                "student_answer"
            ],
            "B: 1",
        )
        self.assertEqual(
            result["wrong_question_evidence"][0][
                "correct_answer"
            ],
            "A: 0",
        )
        self.assertEqual(
            [
                group["topic"]
                for group in result["diagnosis_groups"]
            ],
            ["Python列表", "函数返回值"],
        )
        self.assertEqual(
            len(result["diagnosis_groups"][0]["evidence"]),
            2,
        )
        self.assertEqual(
            result["execution_trace"],
            [
                "analyze_current_course_wrong_questions",
                "get_current_course_wrong_questions",
            ],
        )

    def test_no_wrong_questions_stops_before_detail_query(self):
        with (
            patch(
                "app.services.review_plan_service."
                "analyze_course_wrong_questions",
                return_value={
                    "status": "no_recorded_wrong_questions",
                    "topic_analysis": [],
                },
            ),
            patch(
                "app.services.review_plan_service."
                "get_course_wrong_question_details",
            ) as detail_mock,
        ):
            result = prepare_review_plan_foundation(
                db=object(),
                student_id="S007",
                course_id="PYTHON101",
            )

        detail_mock.assert_not_called()
        self.assertEqual(
            result["status"],
            "no_recorded_wrong_questions",
        )
        self.assertEqual(result["weak_topics"], [])
        self.assertEqual(
            result["wrong_question_evidence"],
            [],
        )
        self.assertEqual(
            result["execution_trace"],
            ["analyze_current_course_wrong_questions"],
        )

    def test_success_without_topic_analysis_is_rejected(self):
        with patch(
            "app.services.review_plan_service."
            "analyze_course_wrong_questions",
            return_value={
                "status": "success",
                "topic_analysis": [],
            },
        ):
            with self.assertRaisesRegex(
                ValueError,
                "没有知识点分析结果",
            ):
                prepare_review_plan_foundation(
                    db=object(),
                    student_id="S007",
                    course_id="PYTHON101",
                )


if __name__ == "__main__":
    unittest.main()
