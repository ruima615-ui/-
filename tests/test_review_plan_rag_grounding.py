import unittest
from unittest.mock import patch

from app.services.review_plan_service import (
    prepare_grounded_review_plan,
)


def make_diagnosis(question_id: str, topic: str, error_type: str) -> dict:
    return {
        "question_id": question_id,
        "topic": topic,
        "error_type": error_type,
        "direct_evidence": ["学生答案与正确答案不一致。"],
        "inference_reason": f"学生可能没有掌握{topic}的基本规则。",
        "alternative_explanations": [],
        "confidence": "medium",
    }


def make_chunk(topic: str, material_id: str) -> dict:
    return {
        "chunk_id": f"{material_id}:chunk:0",
        "content": f"{topic}的课程讲解与例题。",
        "relevance_score": 0.91,
        "course_id": "PYTHON101",
        "topic": topic,
        "material_id": material_id,
        "material_title": f"{topic}讲义",
        "section": topic,
        "source_type": "teacher",
        "original_filename": f"{material_id}.md",
        "chunk_index": 0,
    }


class ReviewPlanRagGroundingTests(unittest.TestCase):
    def setUp(self):
        self.foundation = {
            "status": "success",
            "scope": {"course_id": "PYTHON101", "top_k": 2},
            "selected_topic_count": 2,
            "weak_topics": [
                {"topic": "Python列表", "priority_rank": 1},
                {"topic": "函数返回值", "priority_rank": 2},
            ],
            "wrong_question_evidence": [
                {"question_id": "LIST_1", "topic": "Python列表"},
                {"question_id": "RETURN_1", "topic": "函数返回值"},
            ],
            "diagnosis_groups": [],
            "execution_trace": [
                "analyze_current_course_wrong_questions",
                "get_current_course_wrong_questions",
            ],
        }
        self.diagnoses = [
            make_diagnosis(
                "LIST_1",
                "Python列表",
                "concept_misunderstanding",
            ),
            make_diagnosis(
                "RETURN_1",
                "函数返回值",
                "knowledge_application_error",
            ),
        ]

    def run_plan(self, search_side_effect):
        with (
            patch(
                "app.services.review_plan_service."
                "prepare_review_plan_foundation",
                return_value=self.foundation,
            ),
            patch(
                "app.services.review_plan_service."
                "search_indexed_course_materials",
                side_effect=search_side_effect,
            ) as search_mock,
        ):
            result = prepare_grounded_review_plan(
                db=object(),
                student_id="S007",
                course_id="PYTHON101",
                diagnoses=self.diagnoses,
            )
        return result, search_mock

    def test_each_top_topic_retrieves_current_course_materials(self):
        def fake_search(course_id, topic, query, top_k):
            return {
                "status": "success",
                "course_id": course_id,
                "topic": topic,
                "retrieved_chunks": [
                    make_chunk(topic, f"MATERIAL_{topic}"),
                ],
            }

        result, search_mock = self.run_plan(fake_search)

        self.assertEqual(result["status"], "success")
        self.assertEqual(search_mock.call_count, 2)
        self.assertEqual(
            [call.kwargs["course_id"] for call in search_mock.call_args_list],
            ["PYTHON101", "PYTHON101"],
        )
        self.assertEqual(
            [call.kwargs["topic"] for call in search_mock.call_args_list],
            ["Python列表", "函数返回值"],
        )
        self.assertTrue(all(
            call.kwargs["top_k"] == 2
            for call in search_mock.call_args_list
        ))
        self.assertIn(
            "概念 定义 基本规则",
            search_mock.call_args_list[0].kwargs["query"],
        )
        self.assertIn(
            "知识应用 例题 迁移练习",
            search_mock.call_args_list[1].kwargs["query"],
        )
        self.assertEqual(len(result["material_evidence"]), 2)
        self.assertEqual(
            result["material_evidence"][0]["source_type"],
            "teacher",
        )
        self.assertEqual(
            result["execution_trace"][-1],
            "retrieve_top_k_course_materials",
        )

    def test_one_missing_topic_returns_partial_without_losing_success(self):
        def fake_search(course_id, topic, query, top_k):
            if topic == "Python列表":
                return {
                    "status": "success",
                    "course_id": course_id,
                    "topic": topic,
                    "retrieved_chunks": [make_chunk(topic, "LIST_MATERIAL")],
                }
            return {
                "status": "topic_materials_not_indexed",
                "course_id": course_id,
                "topic": topic,
                "message": "当前知识点没有资料",
            }

        result, _ = self.run_plan(fake_search)

        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["material_evidence"]), 1)
        self.assertEqual(
            result["material_evidence"][0]["topic"],
            "Python列表",
        )
        self.assertEqual(len(result["limitations"]), 1)
        self.assertEqual(
            result["material_groups"][1]["status"],
            "topic_materials_not_indexed",
        )

    def test_all_missing_topics_returns_materials_not_configured(self):
        result, _ = self.run_plan(lambda **kwargs: {
            "status": "course_materials_not_indexed",
            "message": "当前课程没有向量资料",
        })

        self.assertEqual(
            result["status"],
            "course_materials_not_configured",
        )
        self.assertEqual(result["material_evidence"], [])
        self.assertEqual(len(result["limitations"]), 2)

    def test_evidence_topic_mismatch_is_rejected(self):
        def fake_search(course_id, topic, query, top_k):
            chunk = make_chunk("函数返回值", "WRONG_TOPIC")
            return {
                "status": "success",
                "course_id": course_id,
                "topic": topic,
                "retrieved_chunks": [chunk],
            }

        with self.assertRaisesRegex(
            ValueError,
            "Chunk 与检索知识点不一致",
        ):
            self.run_plan(fake_search)

    def test_one_retrieval_exception_does_not_erase_other_topic(self):
        def fake_search(course_id, topic, query, top_k):
            if topic == "Python列表":
                raise ConnectionError("Ollama unavailable")
            return {
                "status": "success",
                "course_id": course_id,
                "topic": topic,
                "retrieved_chunks": [
                    make_chunk(topic, "RETURN_MATERIAL"),
                ],
            }

        with self.assertLogs(
            "app.services.review_plan_service",
            level="ERROR",
        ) as captured_logs:
            result, _ = self.run_plan(fake_search)

        self.assertEqual(result["status"], "partial")
        self.assertEqual(
            result["material_groups"][0]["status"],
            "material_retrieval_failed",
        )
        self.assertEqual(
            result["material_evidence"][0]["topic"],
            "函数返回值",
        )
        self.assertNotIn(
            "Ollama unavailable",
            result["limitations"][0],
        )
        self.assertIn(
            "course_id=PYTHON101",
            captured_logs.output[0],
        )


if __name__ == "__main__":
    unittest.main()
