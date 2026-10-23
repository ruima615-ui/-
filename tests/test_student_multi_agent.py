import unittest
import json
from unittest.mock import patch

from app.workflows.student_multi_agent import run_student_multi_agent_review


TOPIC = "Python列表"
EVIDENCE = {"question_id": "Q1", "topic": TOPIC, "stem": "第一项下标？",
            "student_answer": "B: 1", "correct_answer": "A: 0", "explanation": "从0开始"}
WEAK = {"topic": TOPIC, "priority_rank": 1, "priority_level": "high",
        "priority_score": 0.9, "wrong_attempts": 1, "total_attempts": 1,
        "error_rate": 1.0, "difficulty_distribution": {"easy": 1, "medium": 0, "hard": 0},
        "analysis_basis": "exam_history"}


class FakeModel:
    def __init__(self, output):
        self.output = output
        self.calls = []

    def with_structured_output(self, schema):
        return self

    def invoke(self, messages):
        self.calls.append(messages)
        return self.output


class SequenceModel(FakeModel):
    def __init__(self, outputs):
        super().__init__(None)
        self.outputs = iter(outputs)

    def invoke(self, messages):
        self.calls.append(messages)
        return next(self.outputs)


def foundation(status="success"):
    return {"status": status, "scope": {"course_id": "C1", "top_k": 2},
            "weak_topics": [WEAK] if status == "success" else [],
            "wrong_question_evidence": [EVIDENCE] if status == "success" else []}


def diagnosis(question_id="Q1"):
    return {"priority_topics": [TOPIC], "evidence_question_ids": [question_id],
            "reason": "该知识点有一道错题", "diagnoses": [{
                "question_id": "Q1", "topic": TOPIC,
                "error_type": "concept_misunderstanding",
                "direct_evidence": ["学生选1，正确答案0"],
                "inference_reason": "可能说明不理解索引从0开始",
                "alternative_explanations": ["也可能误选"], "confidence": "medium"}]}


def material(**kwargs):
    return {"status": "success", "course_id": kwargs["course_id"],
            "topic": TOPIC, "retrieved_chunks": [{
                "topic": TOPIC, "material_id": "M1", "material_title": "列表基础",
                "source_type": "teacher", "original_filename": "list.md",
                "chunk_id": "CH1", "content": "列表索引从0开始。",
            }]}


def task():
    return {"review_tasks": [{"task_id": "T1", "topic": TOPIC,
             "priority_rank": 1, "objective": "理解列表索引",
             "related_error_types": ["concept_misunderstanding"],
             "action_steps": ["阅读列表基础并练习索引"],
             "material_chunk_ids": ["CH1"],
             "self_check_questions": ["第一项下标是多少？"]}]}


class StudentMultiAgentTests(unittest.TestCase):
    def run_graph(self, diagnosis_output=None, plan_output=None,
                  base=None, search=material):
        dm = FakeModel(diagnosis_output or diagnosis())
        pm = FakeModel(plan_output or task())
        with patch("app.workflows.student_multi_agent.prepare_review_plan_foundation",
                   return_value=base or foundation()) as prepared:
            result = run_student_multi_agent_review(
                db=object(), student_id="S1", course_id="C1",
                diagnosis_model=dm, plan_model=pm, material_search=search,
            )
        return result, prepared, dm, pm

    def test_validated_handoff_and_mcp_plan(self):
        result, prepared, dm, pm = self.run_graph()
        self.assertEqual(prepared.call_count, 1)
        self.assertEqual(result["review_plan"]["status"], "success")
        self.assertEqual(result["review_plan"]["review_tasks"][0]["material_chunk_ids"], ["CH1"])
        self.assertEqual(result["diagnosis_handoff"]["evidence_question_ids"], ["Q1"])
        self.assertEqual([x["tool_name"] for x in result["tool_trace"]], [
            "prepare_review_plan_foundation", "diagnosis_agent",
            "mcp_search_course_material", "plan_agent", "coordinator_finish"])
        self.assertNotIn("student_id", str(dm.calls) + str(pm.calls))
        plan_input = json.loads(pm.calls[0][-1][1])
        self.assertEqual(plan_input["required_task_count"], 1)
        self.assertEqual(plan_input["eligible_groups"], [
            {"topic": TOPIC, "priority_rank": 1, "allowed_chunk_ids": ["CH1"]}
        ])

    def test_zero_wrong_skips_both_workers(self):
        result, prepared, dm, pm = self.run_graph(
            base=foundation("no_recorded_wrong_questions"))
        self.assertEqual(prepared.call_count, 1)
        self.assertEqual(result["review_plan"]["status"], "no_recorded_wrong_questions")
        self.assertEqual(result["review_plan"]["review_tasks"], [])
        self.assertFalse(dm.calls or pm.calls)

    def test_mcp_failure_skips_plan(self):
        def failure(**kwargs):
            raise ConnectionError("offline")
        result, _, dm, pm = self.run_graph(search=failure)
        self.assertEqual(result["review_plan"]["status"], "material_retrieval_failed")
        self.assertEqual(result["review_plan"]["review_tasks"], [])
        self.assertFalse(pm.calls)

    def test_mcp_other_course_result_is_rejected(self):
        def wrong_course(**kwargs):
            return {**material(**kwargs), "course_id": "C2"}
        result, _, _, pm = self.run_graph(search=wrong_course)
        self.assertEqual(result["review_plan"]["status"], "material_retrieval_failed")
        self.assertFalse(pm.calls)

    def test_missing_material_is_distinct_from_retrieval_failure(self):
        def missing(**kwargs):
            return {"status": "topic_materials_not_indexed", "course_id": kwargs["course_id"],
                    "topic": kwargs["topic"]}
        result, _, _, pm = self.run_graph(search=missing)
        self.assertEqual(result["review_plan"]["status"], "course_materials_not_configured")
        self.assertFalse(pm.calls)

    def test_reuses_validated_diagnosis_in_same_session(self):
        dm, pm = FakeModel(diagnosis()), FakeModel(task())
        with (patch("app.workflows.student_multi_agent.prepare_review_plan_foundation",
                    return_value=foundation()) as prepared,
              patch("app.workflows.student_multi_agent.load_validated_diagnoses",
                    return_value={"status": "reused", "diagnoses": diagnosis()["diagnoses"]}) as loaded):
            result = run_student_multi_agent_review(
                db=object(), student_id="S1", course_id="C1", session_id="SESSION1",
                diagnosis_model=dm, plan_model=pm, material_search=material,
            )
        self.assertEqual(prepared.call_count, 1)
        self.assertEqual(loaded.call_count, 1)
        self.assertFalse(dm.calls)
        self.assertEqual(result["review_plan"]["status"], "success")
        self.assertTrue(pm.calls)

    def test_expired_handoff_runs_diagnosis_and_saves_new_snapshot(self):
        dm, pm = FakeModel(diagnosis()), FakeModel(task())
        with (patch("app.workflows.student_multi_agent.prepare_review_plan_foundation",
                    return_value=foundation()) as prepared,
              patch("app.workflows.student_multi_agent.load_validated_diagnoses",
                    return_value={"status": "expired", "diagnoses": []}),
              patch("app.workflows.student_multi_agent.save_validated_diagnoses",
                    return_value={"status": "success"}) as saved):
            result = run_student_multi_agent_review(
                db=object(), student_id="S1", course_id="C1", session_id="SESSION1",
                diagnosis_model=dm, plan_model=pm, material_search=material,
            )
        self.assertEqual(prepared.call_count, 1)
        self.assertEqual(saved.call_count, 1)
        self.assertEqual(len(dm.calls), 1)
        self.assertEqual(result["review_plan"]["status"], "success")

    def test_diagnosis_cannot_replace_evidence_id(self):
        result, _, _, pm = self.run_graph(diagnosis_output=diagnosis("FOREIGN"))
        self.assertEqual(result["review_plan"]["status"], "diagnosis_failed")
        self.assertEqual(result["review_plan"]["review_tasks"], [])
        self.assertFalse(pm.calls)

    def test_evaluation_records_rejected_diagnosis_identifiers_and_rule(self):
        dm, pm = FakeModel(diagnosis("FOREIGN")), FakeModel(task())
        with patch("app.workflows.student_multi_agent.prepare_review_plan_foundation",
                   return_value=foundation()):
            result = run_student_multi_agent_review(
                db=object(), student_id="S1", course_id="C1",
                diagnosis_model=dm, plan_model=pm, material_search=material,
                capture_failure_diagnostics=True,
            )
        failure = result["failure_diagnostic"]
        self.assertEqual(failure["stage"], "evidence_validation")
        self.assertEqual(failure["error_type"], "ValueError")
        self.assertIn("题目", failure["rule"])
        self.assertEqual(failure["candidate_fields"]["evidence_question_ids"], ["FOREIGN"])
        self.assertNotIn("学生选1", str(failure))

    def test_evaluation_records_rejected_plan_identifiers_and_rule(self):
        invalid = task()
        invalid["review_tasks"][0]["material_chunk_ids"] = ["FOREIGN_CHUNK"]
        dm, pm = FakeModel(diagnosis()), FakeModel(invalid)
        with patch("app.workflows.student_multi_agent.prepare_review_plan_foundation",
                   return_value=foundation()):
            result = run_student_multi_agent_review(
                db=object(), student_id="S1", course_id="C1",
                diagnosis_model=dm, plan_model=pm, material_search=material,
                capture_failure_diagnostics=True,
            )
        failure = result["failure_diagnostic"]
        self.assertEqual(failure["stage"], "task_validation")
        self.assertEqual(result["review_plan"]["status"], "plan_failed")
        self.assertIn("Chunk", failure["rule"])
        self.assertEqual(failure["candidate_fields"]["review_tasks"][0]["material_chunk_ids"],
                         ["FOREIGN_CHUNK"])
        self.assertNotIn("阅读列表基础", str(failure))

    def test_invalid_diagnosis_gets_one_corrective_retry(self):
        dm, pm = SequenceModel([None, diagnosis()]), FakeModel(task())
        with patch("app.workflows.student_multi_agent.prepare_review_plan_foundation",
                   return_value=foundation()):
            result = run_student_multi_agent_review(
                db=object(), student_id="S1", course_id="C1",
                diagnosis_model=dm, plan_model=pm, material_search=material,
            )
        self.assertEqual(result["review_plan"]["status"], "success")
        self.assertEqual(len(dm.calls), 2)
        self.assertEqual(result["tool_trace"][1]["detail"], "retries=1")

    def test_duplicate_topic_tasks_get_one_corrective_retry(self):
        invalid = task()
        invalid["review_tasks"].append({**invalid["review_tasks"][0], "task_id": "T2"})
        dm, pm = FakeModel(diagnosis()), SequenceModel([invalid, task()])
        with patch("app.workflows.student_multi_agent.prepare_review_plan_foundation",
                   return_value=foundation()):
            result = run_student_multi_agent_review(
                db=object(), student_id="S1", course_id="C1",
                diagnosis_model=dm, plan_model=pm, material_search=material,
            )
        self.assertEqual(result["review_plan"]["status"], "success")
        self.assertEqual(len(pm.calls), 2)
        self.assertEqual(result["tool_trace"][-2]["detail"], "retries=1")

    def test_production_does_not_return_failure_details(self):
        result, _, _, _ = self.run_graph(diagnosis_output=diagnosis("FOREIGN"))
        self.assertIsNone(result["failure_diagnostic"])

    def test_foundation_failure_skips_models(self):
        dm, pm = FakeModel(diagnosis()), FakeModel(task())
        with patch("app.workflows.student_multi_agent.prepare_review_plan_foundation",
                   side_effect=RuntimeError("database unavailable")):
            result = run_student_multi_agent_review(
                db=object(), student_id="S1", course_id="C1",
                diagnosis_model=dm, plan_model=pm, material_search=material,
            )
        self.assertEqual(result["review_plan"]["status"], "foundation_failed")
        self.assertFalse(dm.calls or pm.calls)


if __name__ == "__main__":
    unittest.main()
