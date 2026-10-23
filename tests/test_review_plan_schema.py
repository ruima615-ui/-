import unittest

from pydantic import ValidationError

from app.schemas.review_plan import ReviewPlanResponse


def build_valid_review_plan() -> dict:
    return {
        "status": "success",
        "scope": {
            "course_id": "PYTHON101",
            "top_k": 2,
        },
        "weak_topics": [
            {
                "topic": "Python列表",
                "priority_rank": 1,
                "priority_level": "high",
                "priority_score": 0.82,
                "wrong_attempts": 3,
                "total_attempts": 4,
                "error_rate": 0.75,
                "difficulty_distribution": {
                    "easy": 2,
                    "medium": 1,
                    "hard": 0,
                },
                "analysis_basis": "exam_history",
            }
        ],
        "wrong_question_evidence": [
            {
                "question_id": "PY_LIST_001",
                "topic": "Python列表",
                "stem": "Python列表中第一个元素的下标是多少？",
                "student_answer": "D：由列表长度决定",
                "correct_answer": "A：0",
                "explanation": "Python列表索引从0开始。",
            }
        ],
        "diagnoses": [
            {
                "question_id": "PY_LIST_001",
                "topic": "Python列表",
                "error_type": "concept_misunderstanding",
                "direct_evidence": [
                    "学生选择了由列表长度决定。",
                    "正确答案是索引0。",
                ],
                "inference_reason": "该选择可能说明对起始索引规则理解有误。",
                "alternative_explanations": [
                    "也可能是一次偶然选择错误。"
                ],
                "confidence": "medium",
            }
        ],
        "material_evidence": [
            {
                "topic": "Python列表",
                "source_id": "python_list_md",
                "source_type": "teacher",
                "original_filename": "python_list.md",
                "source_title": "Python列表课程资料",
                "chunk_id": "python_list_md_001",
                "section": "列表索引",
                "page_number": None,
                "content_excerpt": "Python列表的第一个元素使用索引0访问。",
                "relevance_score": 0.91,
            }
        ],
        "review_tasks": [
            {
                "task_id": "review_python_list_1",
                "topic": "Python列表",
                "priority_rank": 1,
                "objective": "理解列表索引的起始位置和合法范围。",
                "related_error_types": [
                    "concept_misunderstanding"
                ],
                "action_steps": [
                    "阅读列表索引课程资料。",
                    "重新完成对应错题。",
                ],
                "material_chunk_ids": [
                    "python_list_md_001"
                ],
                "self_check_questions": [
                    "长度为3的列表有哪些合法正索引？"
                ],
            }
        ],
        "limitations": [],
    }


class ReviewPlanSchemaTests(unittest.TestCase):
    def test_valid_review_plan_is_accepted(self):
        plan = ReviewPlanResponse.model_validate(
            build_valid_review_plan()
        )

        self.assertEqual(plan.status, "success")
        self.assertEqual(plan.scope.course_id, "PYTHON101")
        self.assertEqual(len(plan.review_tasks), 1)

    def test_third_weak_topic_is_rejected(self):
        payload = build_valid_review_plan()
        topic = payload["weak_topics"][0]
        payload["weak_topics"] = [
            {**topic, "topic": "知识点一", "priority_rank": 1},
            {**topic, "topic": "知识点二", "priority_rank": 2},
            {**topic, "topic": "知识点三", "priority_rank": 2},
        ]

        with self.assertRaises(ValidationError):
            ReviewPlanResponse.model_validate(payload)

    def test_invalid_error_type_is_rejected(self):
        payload = build_valid_review_plan()
        payload["diagnoses"][0]["error_type"] = "careless"

        with self.assertRaises(ValidationError):
            ReviewPlanResponse.model_validate(payload)

    def test_extra_field_is_rejected(self):
        payload = build_valid_review_plan()
        payload["student_id"] = "S007"

        with self.assertRaises(ValidationError):
            ReviewPlanResponse.model_validate(payload)

    def test_score_outside_unit_interval_is_rejected(self):
        payload = build_valid_review_plan()
        payload["weak_topics"][0]["priority_score"] = 1.01

        with self.assertRaises(ValidationError):
            ReviewPlanResponse.model_validate(payload)

    def test_missing_required_evidence_field_is_rejected(self):
        payload = build_valid_review_plan()
        del payload["wrong_question_evidence"][0]["student_answer"]

        with self.assertRaises(ValidationError):
            ReviewPlanResponse.model_validate(payload)

    def test_explicitly_missing_answer_can_be_recorded(self):
        payload = build_valid_review_plan()
        payload["wrong_question_evidence"][0][
            "student_answer"
        ] = None

        plan = ReviewPlanResponse.model_validate(payload)

        self.assertIsNone(
            plan.wrong_question_evidence[0].student_answer
        )


if __name__ == "__main__":
    unittest.main()
