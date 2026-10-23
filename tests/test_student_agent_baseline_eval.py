"""基线评测器应识别漏工具、轨迹缺失和越权错误。"""

import tempfile
import unittest
import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.services.wrong_question_service import (
    analyze_course_wrong_questions, get_course_wrong_question_details,
)
from evals.student_agent_baseline import grade_turn, load_cases
from evals.fixed_dataset import load_dataset, material_chunk, material_search, seed_fixture


class StudentAgentBaselineEvalTests(unittest.TestCase):
    def test_fixed_dataset_has_reproducible_identity_and_course_scoped_materials(self):
        dataset, digest = load_dataset()
        self.assertEqual(dataset["dataset_id"], "student-agent-synthetic-v1")
        self.assertEqual(digest, load_dataset()[1])
        self.assertEqual(len(digest), 64)
        main = material_search(course_id="C_EVAL_MAIN", topic="Python列表", query="索引",
                               dataset=dataset)
        self.assertEqual([row["chunk_id"] for row in main["retrieved_chunks"]],
                         ["M_LIST:chunk:1", "M_LIST:chunk:2"])
        self.assertEqual(material_search(course_id="C_EVAL_MAIN", topic="Python 列表索引",
                                         query="索引", dataset=dataset)["status"], "success")
        self.assertEqual(material_chunk(course_id="C_EVAL_OTHER", chunk_id="M_LIST:chunk:2",
                                        dataset=dataset)["status"], "chunk_not_found")
        self.assertEqual(material_chunk(course_id="C_EVAL_MAIN", chunk_id="M_SECRET:chunk:1",
                                        dataset=dataset)["status"], "chunk_not_found")

    def test_fixed_dataset_rejects_inconsistent_answer(self):
        dataset, _ = load_dataset()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "invalid.json"
            dataset["attempts"][0]["answers"][0]["is_correct"] = True
            path.write_text(json.dumps(dataset, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "作答对错"):
                load_dataset(path)

    def test_cases_have_isolated_wrong_question_evidence(self):
        cases = load_cases()
        with tempfile.TemporaryDirectory() as temp_dir:
            engine = create_engine(f"sqlite:///{(Path(temp_dir) / 'eval.db').as_posix()}")
            Base.metadata.create_all(engine)
            factory = sessionmaker(bind=engine)
            try:
                seed_fixture(factory, cases, load_dataset()[0])
                with factory() as db:
                    main = get_course_wrong_question_details(db, "S_EVAL_MAIN", "C_EVAL_MAIN")
                    other = get_course_wrong_question_details(db, "S_EVAL_OTHER", "C_EVAL_OTHER")
                    empty = get_course_wrong_question_details(db, "S_EVAL_EMPTY", "C_EVAL_MAIN")
                    analysis = analyze_course_wrong_questions(db, "S_EVAL_MAIN", "C_EVAL_MAIN")
                self.assertEqual({row["question_id"] for row in main["wrong_questions"]},
                                 {"Q_LIST_01", "Q_FUNC_01"})
                self.assertEqual(other["wrong_questions"][0]["question_id"], "Q_SECRET_01")
                self.assertEqual(empty["wrong_questions"], [])
                self.assertEqual(analysis["total_wrong_questions"], 2)
            finally:
                engine.dispose()

    def test_grader_rejects_missing_trace_and_leaked_fact(self):
        case = {"id": "scope"}
        turn = {"required_tools": ["searchlearningmaterial"],
                "answer_excludes": ["秘密正确答案是 Z"]}
        result = {"answer": "秘密正确答案是 Z", "called_tools": ["searchlearningmaterial"],
                  "tool_trace": []}
        checks = grade_turn(case, turn, result)
        self.assertFalse(checks["tool_trace_complete"])
        self.assertFalse(checks["forbidden_facts"])

    def test_grader_requires_actual_permission_error(self):
        case = {"expect_error": "PermissionError"}
        self.assertTrue(grade_turn(case, {}, error=PermissionError())["expected_error"])
        self.assertFalse(grade_turn(case, {}, error=ValueError())["expected_error"])

    def test_zero_wrong_evidence_accepts_either_tool_but_requires_query_result(self):
        turn = next(case["turns"][0] for case in load_cases()
                    if case["id"] == "no_wrong_questions")
        result = {
            "answer": "当前没有已记录的错题，不能判断已经掌握全部内容。",
            "called_tools": ["analyze_current_course_wrong_questions"],
            "tool_trace": [{"tool_name": "analyze_current_course_wrong_questions",
                            "result_preview": '{"status": "no_recorded_wrong_questions"}'}],
        }
        checks = grade_turn({}, turn, result)
        self.assertTrue(all(checks.values()))
        no_query = {**result, "called_tools": [], "tool_trace": []}
        checks = grade_turn({}, turn, no_query)
        self.assertFalse(checks["any_required_tools"])
        self.assertFalse(checks["trace_status"])


if __name__ == "__main__":
    unittest.main()
