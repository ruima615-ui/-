import json
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest


class StreamlitReviewPlanTests(unittest.TestCase):
    def test_structured_review_plan_renders(self):
        project_dir = Path(__file__).resolve().parents[1]
        frontend_dir = project_dir / "frontend"
        plan = {
            "status": "success",
            "scope": {
                "course_id": "SYNTHETIC_COURSE",
                "top_k": 2,
            },
            "material_evidence": [{
                "topic": "合成列表知识点",
                "source_id": "MATERIAL_1",
                "source_title": "合成列表讲义",
                "source_type": "official",
                "original_filename": "synthetic_list.md",
                "chunk_id": "CHUNK_1",
                "section": "索引",
                "page_number": None,
                "content_excerpt": "列表首项索引为0。",
                "relevance_score": 0.9,
            }],
            "review_tasks": [{
                "task_id": "TASK_1",
                "topic": "合成列表知识点",
                "priority_rank": 1,
                "objective": "掌握列表索引规则。",
                "related_error_types": [
                    "concept_misunderstanding"
                ],
                "action_steps": [
                    "阅读列表索引资料。",
                    "重新完成对应错题。",
                ],
                "material_chunk_ids": ["CHUNK_1"],
                "self_check_questions": [
                    "列表首项索引是什么？"
                ],
            }],
            "limitations": [],
        }
        script = (
            "import sys\n"
            f"sys.path.insert(0, {str(frontend_dir)!r})\n"
            "from streamlit_app import render_review_plan\n"
            f"plan = {json.dumps(plan, ensure_ascii=False)!r}\n"
            "import json\n"
            "render_review_plan(json.loads(plan))\n"
        )

        app = AppTest.from_string(script)
        app.run(timeout=10)

        self.assertEqual(app.exception, [])
        self.assertIn(
            "结构化复习计划",
            [item.value for item in app.subheader],
        )
        markdown_values = [
            item.value
            for item in app.markdown
        ]
        self.assertTrue(any(
            "合成列表知识点" in value
            for value in markdown_values
        ))
        self.assertTrue(any(
            "执行步骤" in value
            for value in markdown_values
        ))


if __name__ == "__main__":
    unittest.main()
