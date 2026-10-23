"""角色导航和新平台布局的 Streamlit 冒烟验证。"""

import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest


FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


class FrontendPlatformUiTests(unittest.TestCase):
    def test_login_page_renders_without_backend(self):
        app = AppTest.from_file(FRONTEND / "streamlit_app.py").run(timeout=20)
        self.assertEqual(app.exception, [])
        self.assertIn("进入工作台", [item.value for item in app.subheader])

    def test_teacher_navigation_separates_overview_and_materials(self):
        script = f'''
import sys
sys.path.insert(0, {str(FRONTEND)!r})
import streamlit as st
import streamlit_app as ui
st.session_state.update({{"token": "test", "user_id": "T1", "role": "teacher",
                         "_api_url_initialized": True, "api_url": "http://testserver"}})
def fake_api(method, path, data=None, timeout=30):
    if path == "/api/teachers/me/courses":
        return [{{"course_id": "C1", "code": "C1", "name": "Python 入门"}}]
    if path.endswith("/index-status"):
        return []
    return []
ui.call_api = fake_api
ui.main()
'''
        app = AppTest.from_string(script).run(timeout=20)
        self.assertEqual(app.exception, [])
        self.assertIn("我的课程", [item.value for item in app.subheader])
        nav = next(item for item in app.radio if item.label == "教师工作区")
        nav.set_value("课程资料").run(timeout=20)
        self.assertEqual(app.exception, [])
        self.assertIn("课程资料", [item.value for item in app.subheader])
        self.assertNotIn("试卷管理与发布", [item.value for item in app.subheader])

    def test_student_course_center_renders_metrics(self):
        script = f'''
import sys
sys.path.insert(0, {str(FRONTEND)!r})
import streamlit_app as ui
import streamlit as st
st.session_state.update({{"token": "test", "user_id": "S1", "role": "student",
                         "_api_url_initialized": True, "api_url": "http://testserver"}})
def fake_api(method, path, data=None, timeout=30):
    course = {{"course_id": "C1", "code": "C1", "name": "Python 入门",
              "description": "Python 基础课程"}}
    if path == "/api/courses": return [course]
    if path == "/api/courses/mine": return [course]
    return []
ui.call_api = fake_api
ui.main()
'''
        app = AppTest.from_string(script).run(timeout=20)
        self.assertEqual(app.exception, [])
        self.assertEqual([metric.label for metric in app.metric], ["已选课程", "可选课程"])
        self.assertIn("我的课程", [item.value for item in app.subheader])


if __name__ == "__main__":
    unittest.main()
