import unittest
from copy import deepcopy
from unittest.mock import patch

from app.services.review_plan_service import (
    finalize_grounded_review_plan,
)


def make_weak_topic(topic: str, rank: int) -> dict:
    return {
        "topic": topic,
        "priority_rank": rank,
        "priority_level": "high",
        "priority_score": 0.8,
        "wrong_attempts": 2,
        "total_attempts": 3,
        "error_rate": 0.67,
        "difficulty_distribution": {
            "easy": 1,
            "medium": 1,
            "hard": 0,
        },
        "analysis_basis": "exam_history",
    }


def make_diagnosis(question_id: str, topic: str, error_type: str) -> dict:
    return {
        "question_id": question_id,
        "topic": topic,
        "error_type": error_type,
        "direct_evidence": ["学生答案与正确答案不同。"],
        "inference_reason": "该答案可能说明基本规则理解存在偏差。",
        "alternative_explanations": [],
        "confidence": "medium",
    }


def make_material(topic: str, material_id: str, chunk_id: str) -> dict:
    return {
        "topic": topic,
        "source_id": material_id,
        "source_title": f"{topic}讲义",
        "source_type": "teacher",
        "original_filename": f"{material_id}.md",
        "chunk_id": chunk_id,
        "section": topic,
        "page_number": None,
        "content_excerpt": f"{topic}核心知识和示例。",
        "relevance_score": 0.9,
    }


def make_task(
    topic: str,
    rank: int,
    error_type: str,
    chunk_id: str,
) -> dict:
    return {
        "task_id": f"review_task_{rank}",
        "topic": topic,
        "priority_rank": rank,
        "objective": f"掌握{topic}的核心规则并修正错误。",
        "related_error_types": [error_type],
        "action_steps": [
            f"阅读{topic}资料。",
            "重新完成对应错题并说明理由。",
        ],
        "material_chunk_ids": [chunk_id],
        "self_check_questions": [f"请解释{topic}的核心规则。"],
    }


class ReviewPlanFinalizationTests(unittest.TestCase):
    def setUp(self):
        self.diagnoses = [
            make_diagnosis(
                "LIST_1", "Python列表", "concept_misunderstanding"
            ),
            make_diagnosis(
                "RETURN_1", "函数返回值", "knowledge_application_error"
            ),
        ]
        self.materials = [
            make_material("Python列表", "M_LIST", "CHUNK_LIST"),
            make_material("函数返回值", "M_RETURN", "CHUNK_RETURN"),
        ]
        self.grounded_plan = {
            "status": "success",
            "scope": {"course_id": "PYTHON101", "top_k": 2},
            "weak_topics": [
                make_weak_topic("Python列表", 1),
                make_weak_topic("函数返回值", 2),
            ],
            "wrong_question_evidence": [
                {
                    "question_id": "LIST_1",
                    "topic": "Python列表",
                    "stem": "列表第一项索引是多少？",
                    "student_answer": "1",
                    "correct_answer": "0",
                    "explanation": "索引从0开始。",
                },
                {
                    "question_id": "RETURN_1",
                    "topic": "函数返回值",
                    "stem": "没有return时返回什么？",
                    "student_answer": "0",
                    "correct_answer": "None",
                    "explanation": "默认返回None。",
                },
            ],
            "diagnoses": self.diagnoses,
            "material_evidence": self.materials,
            "material_groups": [
                {
                    "topic": "Python列表",
                    "priority_rank": 1,
                    "status": "success",
                    "query": "列表",
                    "evidence": [self.materials[0]],
                },
                {
                    "topic": "函数返回值",
                    "priority_rank": 2,
                    "status": "success",
                    "query": "返回值",
                    "evidence": [self.materials[1]],
                },
            ],
            "limitations": [],
        }
        self.tasks = [
            make_task(
                "Python列表", 1, "concept_misunderstanding", "CHUNK_LIST"
            ),
            make_task(
                "函数返回值",
                2,
                "knowledge_application_error",
                "CHUNK_RETURN",
            ),
        ]

    def finalize(self, grounded_plan=None, tasks=None):
        with patch(
            "app.services.review_plan_service.prepare_grounded_review_plan",
            return_value=(grounded_plan or self.grounded_plan),
        ):
            return finalize_grounded_review_plan(
                db=object(),
                student_id="S007",
                course_id="PYTHON101",
                diagnoses=self.diagnoses,
                review_tasks=self.tasks if tasks is None else tasks,
            )

    def test_valid_tasks_become_strict_review_plan_response(self):
        result = self.finalize()

        self.assertEqual(result["status"], "success")
        self.assertEqual(
            [task["topic"] for task in result["review_tasks"]],
            ["Python列表", "函数返回值"],
        )
        self.assertEqual(len(result["material_evidence"]), 2)
        self.assertEqual(
            set(result),
            {
                "status",
                "scope",
                "weak_topics",
                "wrong_question_evidence",
                "diagnoses",
                "material_evidence",
                "review_tasks",
                "limitations",
            },
        )

    def test_foreign_or_cross_topic_chunk_is_rejected(self):
        tasks = deepcopy(self.tasks)
        tasks[0]["material_chunk_ids"] = ["CHUNK_RETURN"]

        with self.assertRaisesRegex(ValueError, "不属于当前知识点"):
            self.finalize(tasks=tasks)

    def test_unconfirmed_error_type_is_rejected(self):
        tasks = deepcopy(self.tasks)
        tasks[0]["related_error_types"] = ["reasoning_error"]

        with self.assertRaisesRegex(ValueError, "未经诊断确认"):
            self.finalize(tasks=tasks)

    def test_missing_topic_task_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "必须且只能生成一个"):
            self.finalize(tasks=self.tasks[:1])

    def test_duplicate_task_id_is_rejected(self):
        tasks = deepcopy(self.tasks)
        tasks[1]["task_id"] = tasks[0]["task_id"]

        with self.assertRaisesRegex(ValueError, "重复的 task_id"):
            self.finalize(tasks=tasks)

    def test_partial_plan_only_accepts_topic_with_materials(self):
        partial = deepcopy(self.grounded_plan)
        partial["status"] = "partial"
        partial["material_evidence"] = self.materials[:1]
        partial["material_groups"][1]["status"] = (
            "topic_materials_not_indexed"
        )
        partial["material_groups"][1]["evidence"] = []
        partial["limitations"] = ["函数返回值暂无课程资料"]

        result = self.finalize(
            grounded_plan=partial,
            tasks=self.tasks[:1],
        )

        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["review_tasks"]), 1)
        self.assertEqual(result["review_tasks"][0]["topic"], "Python列表")

    def test_no_materials_returns_empty_degraded_plan(self):
        unavailable = deepcopy(self.grounded_plan)
        unavailable["status"] = "course_materials_not_configured"
        unavailable["material_evidence"] = []
        for group in unavailable["material_groups"]:
            group["status"] = "course_materials_not_indexed"
            group["evidence"] = []
        unavailable["limitations"] = ["当前课程没有可用资料"]

        result = self.finalize(
            grounded_plan=unavailable,
            tasks=[],
        )

        self.assertEqual(
            result["status"],
            "course_materials_not_configured",
        )
        self.assertEqual(result["review_tasks"], [])


if __name__ == "__main__":
    unittest.main()
