"""教师资料上传和双索引状态接口的授权与返回验证。"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.exam_dependencies import get_current_user, get_db
from app.core.database import Base
from app.main import app
from app.models.entities import Course, CourseMaterialEmbeddingIndex, CourseMaterialChunkTopic, TeacherCourseAssignment, User


class TeacherMaterialUiApiTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.db.add_all([
            User(id="A1", name="管理员", role="admin", status="active"),
            User(id="T1", name="授课教师", role="teacher", status="active"),
            User(id="T2", name="其他教师", role="teacher", status="active"),
            Course(id="C1", code="C1", name="课程", status="active"),
            TeacherCourseAssignment(teacher_id="T1", course_id="C1", assigned_by="A1"),
        ])
        self.db.commit()
        def session_override():
            yield self.db
        app.dependency_overrides[get_db] = session_override
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="T1", role="teacher")
        self.client = TestClient(app)
        self.temporary = tempfile.TemporaryDirectory()
        self.storage_patch = patch("app.services.course_material_service.COURSE_MATERIAL_DIR", Path(self.temporary.name))
        self.index_patch = patch("app.api.course_materials.index_course_material_in_background")
        self.storage_patch.start()
        self.index_patch.start()

    def tearDown(self):
        self.index_patch.stop()
        self.storage_patch.stop()
        self.client.close()
        app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()
        self.temporary.cleanup()

    def test_upload_and_index_status_are_course_scoped(self):
        url = "/api/teacher/course-materials/courses/C1"
        upload = self.client.post(url, files={"file": ("list.md", b"# Python list\nIndex starts at zero.", "text/markdown")},
                                  data={"title": "列表讲义", "topic": "Python列表"})
        self.assertEqual(upload.status_code, 201, upload.text)
        material_id = upload.json()["material_id"]
        response = self.client.get(f"{url}/index-status")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()[0]["indexes"], {})
        self.db.add(CourseMaterialEmbeddingIndex(
            material_id=material_id, backend="primary", course_id="C1",
            collection_name="course_material_chunks_primary", embedding_model="test", dimension=1024,
            content_checksum="a" * 64, chunk_size=500, chunk_overlap=50,
            chunk_count=1, status="indexed",
        ))
        self.db.commit()
        self.assertEqual(self.client.get(f"{url}/index-status").json()[0]["indexes"]["primary"]["chunk_count"], 1)
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="T2", role="teacher")
        self.assertEqual(self.client.get(f"{url}/index-status").status_code, 403)
        self.assertEqual(self.client.post(url, files={"file": ("x.md", b"text", "text/markdown")},
                                          data={"title": "X", "topic": "X"}).status_code, 403)

    def test_teacher_can_review_own_chunk_topics_and_other_teacher_cannot(self):
        upload = self.client.post(
            "/api/teacher/course-materials/courses/C1",
            files={"file": ("multi.md", "## 列表\n列表索引从0开始。\n\n## 函数\n函数使用return。".encode(), "text/markdown")},
            data={"title": "综合资料", "topic": "列表,函数"})
        self.assertEqual(upload.status_code, 201, upload.text)
        material_id = upload.json()["material_id"]
        with patch("app.api.course_materials.COURSE_MATERIAL_DIR", Path(self.temporary.name)):
            read = self.client.get(f"/api/teacher/course-materials/{material_id}/chunk-topics")
            self.assertEqual(read.status_code, 200, read.text)
            self.assertEqual(read.json()["total"], 1)
            changed = self.client.put(
                f"/api/teacher/course-materials/{material_id}/chunk-topics/0",
                json={"topics": ["列表", "函数"]})
            self.assertEqual(changed.status_code, 200, changed.text)
            self.assertEqual(self.db.get(CourseMaterialChunkTopic, (material_id, 0)).topics,
                             ["列表", "函数"])
            self.assertEqual(self.client.put(
                f"/api/teacher/course-materials/{material_id}/chunk-topics/99",
                json={"topics": ["列表"]}).status_code, 404)
            app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="T2", role="teacher")
            self.assertEqual(self.client.get(
                f"/api/teacher/course-materials/{material_id}/chunk-topics").status_code, 403)

    def test_blank_upload_suggests_headings_then_teacher_confirms(self):
        upload = self.client.post(
            "/api/teacher/course-materials/courses/C1",
            files={"file": ("course.md", "## 列表索引\n索引从0开始。".encode(), "text/markdown")},
            data={"title": "综合资料", "topic": ""})
        self.assertEqual(upload.status_code, 201, upload.text)
        material_id = upload.json()["material_id"]
        with patch("app.api.course_materials.COURSE_MATERIAL_DIR", Path(self.temporary.name)):
            read = self.client.get(f"/api/teacher/course-materials/{material_id}/chunk-topics")
            self.assertEqual(read.status_code, 200, read.text)
            self.assertIn("列表索引", read.json()["candidate_topics"])
            self.assertEqual(read.json()["chunks"][0]["topics"], ["列表索引"])
            self.assertFalse(read.json()["chunks"][0]["reviewed"])
            confirmed = self.client.put(
                f"/api/teacher/course-materials/{material_id}/chunk-topics/0",
                json={"topics": ["列表索引"]})
            self.assertEqual(confirmed.status_code, 200, confirmed.text)
            self.assertEqual(self.db.get(CourseMaterialChunkTopic, (material_id, 0)).topics,
                             ["列表索引"])

    def test_teacher_can_add_new_topic_after_reading_chunk(self):
        upload = self.client.post(
            "/api/teacher/course-materials/courses/C1",
            files={"file": ("course.md", "这段介绍列表切片。".encode(), "text/markdown")},
            data={"title": "切片讲义"})
        self.assertEqual(upload.status_code, 201, upload.text)
        material_id = upload.json()["material_id"]
        base = f"/api/teacher/course-materials/{material_id}/chunk-topics"
        with patch("app.api.course_materials.COURSE_MATERIAL_DIR", Path(self.temporary.name)):
            preview = self.client.get(base)
            self.assertEqual(preview.status_code, 200, preview.text)
            self.assertEqual(preview.json()["chunks"][0]["topics"], ["通用"])
            self.assertEqual(self.client.put(base + "/0", json={"topics": ["通用", "列表切片"]}).status_code, 422)
            self.assertEqual(self.client.put(base + "/0", json={"topics": ["无效,标签"]}).status_code, 422)
            changed = self.client.put(base + "/0", json={"topics": ["列表切片"]})
            self.assertEqual(changed.status_code, 200, changed.text)
            again = self.client.get(base)
            self.assertEqual(again.json()["chunks"][0]["topics"], ["列表切片"])
            self.assertTrue(again.json()["chunks"][0]["reviewed"])
            self.assertIn("列表切片", again.json()["available_topics"])
            app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="T2", role="teacher")
            self.assertEqual(self.client.put(base + "/0", json={"topics": ["其他课程"]}).status_code, 403)


if __name__ == "__main__":
    unittest.main()
