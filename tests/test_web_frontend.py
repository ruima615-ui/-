"""独立 Web 前端经 FastAPI 同源提供，API 路由保持可用。"""

import unittest

from fastapi.testclient import TestClient

from app.main import app


class WebFrontendTests(unittest.TestCase):
    def test_web_entry_and_assets(self):
        client = TestClient(app)
        home = client.get("/", follow_redirects=False)
        self.assertEqual(home.status_code, 307)
        self.assertEqual(home.headers["location"], "/web/")
        page = client.get("/web/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("CoursePilot", page.text)
        self.assertEqual(client.get("/web/styles.css").status_code, 200)
        self.assertEqual(client.get("/web/app.js").status_code, 200)
        self.assertEqual(client.get("/health").json()["status"], "ok")
        client.close()


if __name__ == "__main__":
    unittest.main()
