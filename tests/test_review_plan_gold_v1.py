import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from evals.build_review_plan_gold_v1 import GOLD_PATH, build, build_review_sheet
from evals.check_review_plan_gold_v1 import check_gold


class ReviewPlanGoldV1Tests(unittest.TestCase):
    def test_selected_cases_have_independent_raw_data_checks_but_no_human_approval(self):
        self.assertEqual(json.loads(GOLD_PATH.read_text(encoding="utf-8")), build())
        result = check_gold()
        self.assertEqual(result["case_count"], 20)
        self.assertEqual(result["unique_ids"], 20)
        self.assertEqual(result["raw_data_errors"], [])
        self.assertEqual(result["human_approved"], 0)
        self.assertFalse(result["gold_ready"])
        self.assertEqual(build_review_sheet(build()).count("\n## "), 20)

    def test_checker_rejects_fabricated_evidence_id(self):
        draft = build()
        draft["cases"][0]["reference"]["evidence_question_ids"] = ["Q_NOT_REAL"]
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "tampered.json"
            path.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
            result = check_gold(path)
        self.assertTrue(result["raw_data_errors"])
        self.assertFalse(result["gold_ready"])


if __name__ == "__main__":
    unittest.main()
