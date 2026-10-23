import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch

import agent_runner
from app.core.database import Base
from app.services.review_plan_service import prepare_review_plan_foundation
from app.workflows.student_multi_agent import run_student_multi_agent_review
from evals.fixed_dataset import load_dataset, seed_fixture
from evals.review_plan_multi_comparison import (
    _fixture_search, validate_cases,
)

CASES_FILE = Path(__file__).resolve().parents[1] / "evals/fixtures/review_plan_comparison_cases_v2.json"
DATASET_FILE = Path(__file__).resolve().parents[1] / "evals/fixtures/student_agent_dataset_v2.json"


class ScriptedDiagnosis:
    def with_structured_output(self, schema):
        return self

    def invoke(self, messages):
        request = json.loads(messages[-1][1])
        evidence = request["wrong_question_evidence"]
        return {
            "priority_topics": request["priority_topics"],
            "evidence_question_ids": [x["question_id"] for x in evidence],
            "reason": "固定证据中的错误作答",
            "diagnoses": [{
                "question_id": x["question_id"], "topic": x["topic"],
                "error_type": "concept_misunderstanding" if x["explanation"] else "insufficient_evidence",
                "direct_evidence": [f"学生答{x['student_answer']}，正确为{x['correct_answer']}"],
                "inference_reason": "可能说明没有掌握题目规则" if x["explanation"] else "缺少解析，无法判断原因",
                "alternative_explanations": ["可能误选"],
                "confidence": "low",
            } for x in evidence],
        }


class ScriptedPlan:
    def with_structured_output(self, schema):
        return self

    def invoke(self, messages):
        request = json.loads(messages[-1][1])
        diagnosed = request["diagnosis_handoff"]["diagnoses"]
        return {"review_tasks": [{
            "task_id": f"TASK_{group['priority_rank']}",
            "topic": group["topic"], "priority_rank": group["priority_rank"],
            "objective": "复习相关规则", "action_steps": ["阅读引用片段并练习"],
            "related_error_types": sorted({x["error_type"] for x in diagnosed
                                           if x["topic"] == group["topic"]}),
            "material_chunk_ids": [group["evidence"][0]["chunk_id"]],
            "self_check_questions": ["请说明规则并举例。"],
        } for group in request["material_groups"] if group["status"] == "success"]}


class ReviewPlanV2FixtureTests(unittest.TestCase):
    def test_thirty_cases_trigger_their_expected_paths(self):
        data, _ = load_dataset(DATASET_FILE)
        cases = json.loads(Path(CASES_FILE).read_text(encoding="utf-8"))
        self.assertEqual(validate_cases(cases, data)["case_count"], 30)
        with TemporaryDirectory() as tmp:
            engine = create_engine(f"sqlite:///{Path(tmp) / 'eval.db'}")
            Base.metadata.create_all(engine)
            sessions = sessionmaker(bind=engine)
            seed_fixture(sessions, cases, data)
            try:
                unauthorized = next(case for case in cases if case.get("expect_error"))
                with patch.object(agent_runner, "SessionLocal", sessions):
                    with self.assertRaises(PermissionError):
                        agent_runner.run_agent_with_memory(
                            user_id=unauthorized["student_id"],
                            session_id=f"SESSION_EVAL_{unauthorized['id']}",
                            user_input=unauthorized["question"],
                            workflow="multi_agent_review",
                        )
                for case in cases:
                    if case.get("expect_error"):
                        continue  # The HTTP/runner session-ownership gate is tested separately.
                    with self.subTest(case=case["id"]), sessions() as db:
                        course_id = case["course_id"]
                        foundation = prepare_review_plan_foundation(db, case["student_id"], course_id)
                        self.assertEqual([x["topic"] for x in foundation["weak_topics"]],
                                         case["expected_topics"])
                        self.assertEqual([x["question_id"] for x in foundation["wrong_question_evidence"]],
                                         case["expected_evidence_ids"])
                        if case["expected_status"] == "no_recorded_wrong_questions":
                            self.assertEqual(foundation["status"], "no_recorded_wrong_questions")
                        else:
                            self.assertEqual(foundation["status"], "success")
                        result = run_student_multi_agent_review(
                            db=db, student_id=case["student_id"], course_id=course_id,
                            diagnosis_model=ScriptedDiagnosis(), plan_model=ScriptedPlan(),
                            material_search=lambda **kwargs: _fixture_search(
                                data, case["material_mode"],
                                blocked_topics=case.get("blocked_topics", ()), **kwargs),
                        )
                        plan = result["review_plan"]
                        self.assertEqual(plan["status"], case["expected_status"])
                        if plan["status"] in {"success", "partial"}:
                            self.assertTrue(plan["review_tasks"])
                            self.assertLessEqual(len(plan["review_tasks"]), 2)
                        else:
                            self.assertFalse(plan["review_tasks"])
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
