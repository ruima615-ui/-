"""教师资料状态和持久试卷预览的 Streamlit 页面冒烟测试。"""

import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest


class TeacherWorkbenchStreamlitTest(unittest.TestCase):
    def test_old_default_backend_is_replaced_by_configured_backend(self):
        frontend = Path(__file__).resolve().parents[1] / "frontend"
        script = f'''
import os, sys
sys.path.insert(0, {str(frontend)!r})
os.environ["COURSEPILOT_API_URL"] = "http://127.0.0.1:8765"
import streamlit as st
import streamlit_app as ui
st.session_state["api_url"] = "http://127.0.0.1:8000"
ui.initialize_api_url()
st.write(st.session_state["api_url"])
'''
        app = AppTest.from_string(script).run(timeout=20)
        self.assertEqual(app.exception, [])
        self.assertEqual(app.markdown[0].value, "http://127.0.0.1:8765")

    def test_existing_material_and_draft_are_rendered(self):
        frontend = Path(__file__).resolve().parents[1] / "frontend"
        script = f'''
import sys
sys.path.insert(0, {str(frontend)!r})
import streamlit_app as ui

def fake_api(method, path, data=None, timeout=30):
    if path.endswith("/index-status"):
        return [{{"material_id": "M1", "title": "列表资料", "source_type": "teacher",
                 "topic": "列表", "filename": "list.md", "parse_status": "ready_for_indexing",
                 "parse_error": None, "indexes": {{"primary": {{"status": "indexed", "chunk_count": 2}}}}}}]
    if path.endswith("/questions"):
        return [{{"question_id": "Q1", "topic": "列表", "stem": "首个下标？",
                 "max_score": 1, "question_type": "fill_blank", "options": None,
                 "answer_key": "0", "explanation": "从零开始"}}]
    if path == "/api/exams/teacher?course_id=C1":
        return [{{"exam_id": "EX1", "course_id": "C1", "title": "列表测验",
                 "status": "draft", "duration_minutes": 30}}]
    if path == "/api/exams/teacher/EX1":
        return {{"exam_id": "EX1", "course_id": "C1", "title": "列表测验",
                "status": "draft", "duration_minutes": 30, "total_points": 1,
                "questions": [{{"question_id": "Q1", "position": 1, "points": 1,
                               "topic": "列表", "stem": "首个下标？",
                               "question_type": "fill_blank", "options": None,
                               "answer_key": "0", "explanation": "从零开始"}}]}}
    return []

ui.call_api = fake_api
courses = [{{"course_id": "C1", "code": "C1", "name": "课程"}}]
ui.show_teacher_materials(courses)
ui.show_exam_management(courses)
'''
        app = AppTest.from_string(script).run(timeout=20)
        self.assertEqual(app.exception, [])
        self.assertIn("课程资料", [item.value for item in app.subheader])
        self.assertIn("试卷管理与发布", [item.value for item in app.subheader])
        self.assertTrue(any("首个下标" in item.label for item in app.expander))

    def test_teacher_reviews_topics_after_upload_without_prefill(self):
        frontend = Path(__file__).resolve().parents[1] / "frontend"
        script = f'''
import sys
sys.path.insert(0, {str(frontend)!r})
import streamlit as st
import streamlit_app as ui
st.session_state["user_id"] = "T1"

def fake_api(method, path, data=None, timeout=30):
    if path.endswith("/index-status"):
        return [{{"material_id": "M1", "title": "综合资料", "source_type": "teacher",
                 "uploaded_by": "T1", "filename": "course.md", "parse_status": "ready_for_indexing",
                 "parse_error": None, "indexes": {{"primary": {{"status": "indexed", "chunk_count": 1}}}}}}]
    if "/chunk-topics" in path:
        return {{"candidate_topics": ["Python列表"], "available_topics": ["Python列表", "通用"],
                 "total": 1, "chunks": [{{"chunk_index": 0, "section": "列表索引",
                                      "content": "列表从0开始", "topics": ["Python列表"], "reviewed": False}}]}}
    return []

ui.call_api = fake_api
ui.show_teacher_materials([{{"course_id": "C1", "code": "C1", "name": "课程"}}])
'''
        app = AppTest.from_string(script).run(timeout=20)
        self.assertEqual(app.exception, [])
        self.assertFalse(any("候选知识点" in item.label for item in app.text_input))
        self.assertTrue(any(item.label == "片段知识点" for item in app.multiselect))


if __name__ == "__main__":
    unittest.main()
