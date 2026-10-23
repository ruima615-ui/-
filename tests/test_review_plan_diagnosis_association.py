import unittest

from app.services.review_plan_service import (
    associate_diagnoses_with_weak_topics,
    prepare_diagnosed_review_plan,
)


def make_diagnosis(
    question_id: str,
    topic: str,
) -> dict:
    return {
        "question_id": question_id,
        "topic": topic,
        "error_type": "concept_misunderstanding",
        "direct_evidence": ["学生答案与正确答案不同。"],
        "inference_reason": "该答案可能对应概念理解偏差。",
        "alternative_explanations": ["不能排除偶然选择错误。"],
        "confidence": "medium",
    }


class ReviewPlanDiagnosisAssociationTests(unittest.TestCase):
    def setUp(self):
        self.weak_topics = [
            {
                "topic": "Python列表",
                "priority_rank": 1,
            },
            {
                "topic": "函数返回值",
                "priority_rank": 2,
            },
        ]
        self.evidence = [
            {
                "question_id": "LIST_1",
                "topic": "Python列表",
            },
            {
                "question_id": "RETURN_1",
                "topic": "函数返回值",
            },
        ]

    def test_diagnoses_are_sorted_by_weak_topic_priority(self):
        diagnoses = [
            make_diagnosis("RETURN_1", "函数返回值"),
            make_diagnosis("LIST_1", "Python列表"),
        ]

        result = associate_diagnoses_with_weak_topics(
            weak_topics=self.weak_topics,
            wrong_question_evidence=self.evidence,
            diagnoses=diagnoses,
        )

        self.assertEqual(
            [item["question_id"] for item in result],
            ["LIST_1", "RETURN_1"],
        )

    def test_diagnosis_cannot_reference_unselected_question(self):
        diagnoses = [
            make_diagnosis("OTHER_1", "Python列表"),
            make_diagnosis("RETURN_1", "函数返回值"),
        ]

        with self.assertRaisesRegex(
            ValueError,
            "未选择的错题",
        ):
            associate_diagnoses_with_weak_topics(
                weak_topics=self.weak_topics,
                wrong_question_evidence=self.evidence,
                diagnoses=diagnoses,
            )

    def test_diagnosis_topic_must_match_evidence_topic(self):
        diagnoses = [
            make_diagnosis("LIST_1", "函数返回值"),
            make_diagnosis("RETURN_1", "函数返回值"),
        ]

        with self.assertRaisesRegex(
            ValueError,
            "知识点与错题证据不一致",
        ):
            associate_diagnoses_with_weak_topics(
                weak_topics=self.weak_topics,
                wrong_question_evidence=self.evidence,
                diagnoses=diagnoses,
            )

    def test_every_selected_question_requires_diagnosis(self):
        with self.assertRaisesRegex(
            ValueError,
            "每一道已选择的错题",
        ):
            associate_diagnoses_with_weak_topics(
                weak_topics=self.weak_topics,
                wrong_question_evidence=self.evidence,
                diagnoses=[
                    make_diagnosis("LIST_1", "Python列表")
                ],
            )

    def test_diagnosed_plan_preserves_trusted_foundation(self):
        foundation = {
            "status": "success",
            "scope": {
                "course_id": "PYTHON101",
                "top_k": 2,
            },
            "selected_topic_count": 2,
            "weak_topics": self.weak_topics,
            "wrong_question_evidence": self.evidence,
            "diagnosis_groups": [],
            "execution_trace": [
                "analyze_current_course_wrong_questions",
                "get_current_course_wrong_questions",
            ],
        }
        diagnoses = [
            make_diagnosis("RETURN_1", "函数返回值"),
            make_diagnosis("LIST_1", "Python列表"),
        ]

        from unittest.mock import patch

        with patch(
            "app.services.review_plan_service."
            "prepare_review_plan_foundation",
            return_value=foundation,
        ):
            result = prepare_diagnosed_review_plan(
                db=object(),
                student_id="S007",
                course_id="PYTHON101",
                diagnoses=diagnoses,
            )

        self.assertEqual(
            [
                item["question_id"]
                for item in result["diagnoses"]
            ],
            ["LIST_1", "RETURN_1"],
        )
        self.assertEqual(
            result["execution_trace"][-1],
            "associate_wrong_question_diagnoses",
        )


if __name__ == "__main__":
    unittest.main()
