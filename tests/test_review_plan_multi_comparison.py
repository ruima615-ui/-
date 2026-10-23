import unittest

from evals.review_plan_multi_comparison import _failure_diagnostic, _score


class ComparisonScoringTests(unittest.TestCase):
    def test_zero_wrong_text_and_verified_tool_count_as_behavior_pass(self):
        case = {"id": "zero_wrong_plan"}
        result = {
            "answer": "当前没有已记录的错题，无法依据错题制定计划。",
            "review_plan": None,
            "called_tools": ["analyze_current_course_wrong_questions"],
            "tool_trace": [{"tool_name": "analyze_current_course_wrong_questions",
                            "result_preview": '{"status":"no_recorded_wrong_questions"}'}],
        }
        self.assertTrue(all(_score(case, result, None).values()))

    def test_missing_source_must_be_confirmed(self):
        case = {"id": "material_unavailable_plan"}
        result = {
            "answer": "没有资料依据，无法生成计划。", "review_plan": None,
            "called_tools": ["validate_current_course_diagnoses"],
            "tool_trace": [{"tool_name": "validate_current_course_diagnoses",
                            "result_preview": '{"status":"success"}'}],
        }
        self.assertFalse(_score(case, result, None)["material_unavailable_confirmed"])

    def test_failed_rule_records_only_plan_identifiers(self):
        result = {"review_plan": {"status": "success",
                                  "weak_topics": [{"topic": "Python列表"}],
                                  "diagnoses": [{"question_id": "Q1", "direct_evidence": ["private"]}],
                                  "material_evidence": [{"chunk_id": "CH1", "content_excerpt": "private"}],
                                  "review_tasks": [{"topic": "Python列表",
                                                    "material_chunk_ids": ["CH2"],
                                                    "action_steps": ["private"]}]}}
        failure = _failure_diagnostic(result, None, {"tasks_grounded": False})
        self.assertEqual(failure["stage"], "evaluation_checks")
        self.assertEqual(failure["rule"], ["tasks_grounded"])
        self.assertEqual(failure["candidate_fields"]["task_chunk_ids"], [["CH2"]])
        self.assertNotIn("private", str(failure))


if __name__ == "__main__":
    unittest.main()
