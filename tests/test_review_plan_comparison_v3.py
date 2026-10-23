"""All 60 v3 cases must match backend evidence and the scripted workflow."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import agent_runner
from app.core.database import Base
from app.services.review_plan_service import prepare_review_plan_foundation
from app.workflows.student_multi_agent import run_student_multi_agent_review
from evals.build_review_plan_dataset_v3 import build_cases, build_dataset
from evals.fixed_dataset import load_dataset, seed_fixture
from evals.review_plan_multi_comparison import CASES_FILE, DATASET_FILE, _fixture_search, validate_cases
from tests.test_review_plan_comparison_v2 import ScriptedDiagnosis, ScriptedPlan


class ReviewPlanV3FixtureTests(unittest.TestCase):
    def test_sixty_cases_and_frozen_build(self):
        data, _ = load_dataset(DATASET_FILE)
        cases = json.loads(Path(CASES_FILE).read_text(encoding="utf-8"))
        self.assertEqual(validate_cases(cases, data)["case_count"], 60)
        self.assertEqual(data, build_dataset())
        self.assertEqual(cases, build_cases(data))
        self.assertEqual(len({case["id"] for case in cases}), 60)
        with TemporaryDirectory() as tmp:
            engine = create_engine(f"sqlite:///{Path(tmp) / 'eval.db'}")
            Base.metadata.create_all(engine)
            sessions = sessionmaker(bind=engine)
            seed_fixture(sessions, cases, data)
            try:
                with patch.object(agent_runner, "SessionLocal", sessions):
                    for case in cases:
                        if not case.get("expect_error"):
                            continue
                        with self.subTest(case=case["id"]), self.assertRaises(PermissionError):
                            agent_runner.run_agent_with_memory(
                                user_id=case["student_id"],
                                session_id=f"SESSION_EVAL_{case['id']}",
                                user_input=case["question"], workflow="multi_agent_review",
                            )
                for case in cases:
                    if case.get("expect_error"):
                        continue
                    with self.subTest(case=case["id"]), sessions() as db:
                        base = prepare_review_plan_foundation(db, case["student_id"], case["course_id"])
                        self.assertEqual([item["topic"] for item in base["weak_topics"]],
                                         case["expected_topics"])
                        self.assertEqual([item["question_id"] for item in base["wrong_question_evidence"]],
                                         case["expected_evidence_ids"])
                        result = run_student_multi_agent_review(
                            db=db, student_id=case["student_id"], course_id=case["course_id"],
                            diagnosis_model=ScriptedDiagnosis(), plan_model=ScriptedPlan(),
                            material_search=lambda **kwargs: _fixture_search(
                                data, case["material_mode"],
                                blocked_topics=case.get("blocked_topics", ()), **kwargs),
                        )
                        plan = result["review_plan"]
                        self.assertEqual(plan["status"], case["expected_status"])
                        self.assertEqual([task["topic"] for task in plan["review_tasks"]],
                                         case["expected_task_topics"])
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
