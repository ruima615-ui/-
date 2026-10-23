import copy
import json
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.entities import (
    ChatSession, Exam, ExamAnswer, ExamAttempt, StudentSessionDiagnosis,
)
from app.services.diagnosis_handoff_service import (
    DIAGNOSIS_MAX_AGE,
    load_validated_diagnoses,
    save_validated_diagnoses,
)
from student_agent import (
    StudentAgentContext, prepare_current_course_review_plan,
    validate_current_course_diagnoses,
)


def foundation():
    return {
        "status": "success",
        "scope": {"course_id": "PYTHON101", "top_k": 2},
        "weak_topics": [{"topic": "Python列表", "priority_rank": 1}],
        "wrong_question_evidence": [{
            "question_id": "Q1", "topic": "Python列表",
            "stem": "第一个元素的索引？", "student_answer": "B: 1",
            "correct_answer": "A: 0", "explanation": "索引从0开始",
        }],
    }


def diagnosis():
    return [{
        "question_id": "Q1", "topic": "Python列表",
        "error_type": "concept_misunderstanding",
        "direct_evidence": ["学生答案 B: 1；正确答案 A: 0"],
        "inference_reason": "可能没有掌握索引从0开始",
        "alternative_explanations": ["可能误读题目"],
        "confidence": "medium",
    }]


class DiagnosisHandoffTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.db.add(ChatSession(
            id="SESSION_A", user_id="S008", course_id="PYTHON101", status="active"))
        self.db.commit()
        self.scope = {"user_id": "S008", "course_id": "PYTHON101", "session_id": "SESSION_A"}

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_save_and_reuse_validated_structured_diagnosis(self):
        saved = save_validated_diagnoses(
            self.db, **self.scope, diagnoses=diagnosis(), foundation=foundation())
        loaded = load_validated_diagnoses(self.db, **self.scope, foundation=foundation())
        self.assertEqual(saved["status"], "success")
        self.assertEqual(loaded["status"], "reused")
        self.assertEqual(loaded["diagnoses"], saved["diagnoses"])
        record = self.db.scalar(select(StudentSessionDiagnosis))
        self.assertEqual(json.loads(record.diagnoses_json), diagnosis())

    def test_changed_answer_or_topic_evidence_forces_rediagnosis(self):
        save_validated_diagnoses(self.db, **self.scope, diagnoses=diagnosis(), foundation=foundation())
        changed = copy.deepcopy(foundation())
        changed["wrong_question_evidence"][0]["student_answer"] = "C: 2"
        loaded = load_validated_diagnoses(self.db, **self.scope, foundation=changed)
        self.assertEqual(loaded, {"status": "evidence_changed", "diagnoses": []})

    def test_old_record_and_other_scope_cannot_be_reused(self):
        save_validated_diagnoses(self.db, **self.scope, diagnoses=diagnosis(), foundation=foundation())
        record = self.db.get(StudentSessionDiagnosis, ("S008", "PYTHON101", "SESSION_A"))
        expired_at = record.validated_at + DIAGNOSIS_MAX_AGE + timedelta(seconds=1)
        self.assertEqual(load_validated_diagnoses(
            self.db, **self.scope, foundation=foundation(), now=expired_at)["status"], "expired")
        self.assertEqual(load_validated_diagnoses(
            self.db, user_id="S007", course_id="PYTHON101", session_id="SESSION_A",
            foundation=foundation())["status"], "scope_mismatch")
        self.assertEqual(load_validated_diagnoses(
            self.db, user_id="S008", course_id="OTHER", session_id="SESSION_A",
            foundation=foundation())["status"], "scope_mismatch")

    def test_invalid_question_is_not_saved(self):
        bad = diagnosis()
        bad[0]["question_id"] = "OTHER_QUESTION"
        with self.assertRaisesRegex(ValueError, "未选择的错题"):
            save_validated_diagnoses(self.db, **self.scope,
                                     diagnoses=bad, foundation=foundation())
        self.assertIsNone(self.db.get(StudentSessionDiagnosis,
                                      ("S008", "PYTHON101", "SESSION_A")))

    def test_valid_diagnosis_survives_material_retrieval_failure(self):
        grounded = foundation()
        grounded["status"] = "course_materials_not_configured"
        saved = save_validated_diagnoses(
            self.db, **self.scope, diagnoses=diagnosis(), foundation=grounded)
        self.assertEqual(saved["status"], "success")
        self.assertEqual(load_validated_diagnoses(
            self.db, **self.scope, foundation=foundation())["status"], "reused")

    def test_new_exam_answer_invalidates_even_if_top_two_evidence_is_unchanged(self):
        self.db.add(Exam(id="EXAM_A", course_id="PYTHON101", title="测验",
                         duration_minutes=30, status="published"))
        self.db.add(ExamAttempt(id=1, exam_id="EXAM_A", student_id="S008",
                                status="graded"))
        self.db.add(ExamAnswer(id=1, exam_attempt_id=1, question_id="Q1",
                               answer="B", grading_status="graded", is_correct=False))
        self.db.commit()
        save_validated_diagnoses(self.db, **self.scope,
                                 diagnoses=diagnosis(), foundation=foundation())
        self.db.add(ExamAnswer(id=2, exam_attempt_id=1, question_id="Q2",
                               answer="A", grading_status="graded", is_correct=True))
        self.db.commit()
        self.assertEqual(load_validated_diagnoses(
            self.db, **self.scope, foundation=foundation())["status"], "evidence_changed")

    def test_next_turn_plan_tools_reuse_saved_diagnoses_without_model_resubmission(self):
        save_validated_diagnoses(self.db, **self.scope,
                                 diagnoses=diagnosis(), foundation=foundation())
        runtime = SimpleNamespace(context=StudentAgentContext(
            db=self.db, student_id="S008", course_id="PYTHON101", session_id="SESSION_A"))
        with patch("student_agent.prepare_review_plan_foundation", return_value=foundation()):
            prepared = prepare_current_course_review_plan.func(runtime=runtime)
        self.assertEqual(prepared["diagnosis_handoff"]["status"], "reused")
        with patch("app.services.diagnosis_handoff_service.prepare_review_plan_foundation",
                   return_value=foundation()), patch(
                   "student_agent.prepare_grounded_review_plan",
                   return_value={"status": "course_materials_not_configured",
                                 "diagnoses": diagnosis(), "material_evidence": []}):
            validated = validate_current_course_diagnoses.func(runtime=runtime)
        self.assertEqual(validated["diagnosis_handoff"], "reused")
        self.assertEqual(validated["diagnoses"], diagnosis())


if __name__ == "__main__":
    unittest.main()
