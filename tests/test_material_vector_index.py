import hashlib
import tempfile
import unittest
from unittest.mock import MagicMock
from pathlib import Path

import chromadb
from langchain_core.embeddings import Embeddings
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.entities import Course
from app.models.entities import CourseMaterialIndex
from app.models.entities import CourseMaterialEmbeddingIndex
from app.models.entities import CourseMaterialChunkTopic
from app.models.entities import TeacherCourseAssignment
from app.models.entities import User
from app.services.course_material_service import (
    create_teacher_course_material,
    delete_owned_course_material,
)
from app.services.material_index_service import (
    COURSE_VECTOR_COLLECTION_BACKUP,
    COURSE_VECTOR_COLLECTION_PRIMARY,
    build_course_vector_store,
    build_material_chunk_documents,
    clean_material_text,
    get_material_topic_assignments,
    index_course_material,
    index_ready_course_materials,
    index_course_material_dual,
    remove_course_material_from_index,
)
from app.services.material_search_service import (
    get_course_material_chunk_with_fallback, search_course_materials_with_fallback,
)
from app.services.embedding_service import EmbeddingUnavailable


class DeterministicEmbeddings(Embeddings):
    """测试专用 Embedding，不调用 Ollama 或网络。"""

    @staticmethod
    def _embed(text: str) -> list[float]:
        digest = hashlib.sha256(
            text.encode("utf-8")
        ).digest()
        return [
            byte / 255.0
            for byte in digest[:8]
        ]

    def embed_documents(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class UnavailableQueryEmbeddings(DeterministicEmbeddings):
    def embed_query(self, text: str) -> list[float]:
        raise EmbeddingUnavailable("模拟主服务断连")


class MaterialVectorIndexTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.temp_storage = tempfile.TemporaryDirectory()
        self.storage_root = Path(self.temp_storage.name)
        self.embeddings = DeterministicEmbeddings()
        self.chroma_client = chromadb.EphemeralClient()

        teacher = User(
            id="TEACHER_INDEX",
            name="索引教师",
            role="teacher",
            status="active",
        )
        course = Course(
            id="COURSE_INDEX",
            code="COURSE_INDEX",
            name="索引测试课程",
            status="active",
        )
        admin = User(
            id="ADMIN_INDEX",
            name="索引管理员",
            role="admin",
            status="active",
        )
        self.db.add_all([teacher, course, admin])
        self.db.flush()
        self.db.add(TeacherCourseAssignment(
            teacher_id="TEACHER_INDEX",
            course_id="COURSE_INDEX",
            assigned_by="ADMIN_INDEX",
        ))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.temp_storage.cleanup()

    def create_material(
        self,
        filename: str,
        title: str,
        topic: str,
        content: str,
    ):
        return create_teacher_course_material(
            db=self.db,
            teacher_id="TEACHER_INDEX",
            course_id="COURSE_INDEX",
            filename=filename,
            mime_type="text/markdown",
            data=content.encode("utf-8"),
            title=title,
            topic=topic,
            storage_root=self.storage_root,
        )

    def make_store(self):
        return build_course_vector_store(
            embedding_function=self.embeddings,
            chroma_client=self.chroma_client,
        )

    def test_multi_topic_material_indexes_each_chunk_by_its_own_topic(self):
        material = self.create_material(
            "whole_course.md", "综合讲义", "Python列表,函数返回值",
            "## Python列表\nPython列表的首个索引是0。\n\n"
            "## 函数返回值\n函数返回值由 return 语句产生。")
        stores = {backend: build_course_vector_store(
            backend=backend, embedding_function=self.embeddings,
            chroma_client=self.chroma_client)
            for backend in ("primary", "backup")}
        indexed = index_course_material_dual(
            db=self.db, material_id=material.id, vector_stores=stores,
            storage_root=self.storage_root, chunk_size=42, chunk_overlap=0)
        self.assertEqual(indexed["backends"], {"primary": "indexed", "backup": "indexed"})
        pending = search_course_materials_with_fallback(
            course_id="COURSE_INDEX", topic="Python列表", query="列表索引",
            db=self.db, vector_stores=stores)
        self.assertEqual(pending["status"], "topic_candidates_need_review")
        pending_id = pending["candidates"][0]["chunk_id"]
        self.assertEqual(get_course_material_chunk_with_fallback(
            course_id="COURSE_INDEX", chunk_id=pending_id,
            db=self.db, vector_stores=stores)["status"], "chunk_not_found")
        docs, _ = build_material_chunk_documents(
            material=material,
            text="## Python列表\nPython列表的首个索引是0。\n\n## 函数返回值\n函数返回值由 return 语句产生。",
            chunk_size=42, chunk_overlap=0)
        by_index = {}
        for doc in docs:
            index = doc.metadata["chunk_index"]
            by_index.setdefault(index, {"content": doc.page_content, "topics": []})["topics"].append(doc.metadata["topic"])
        for index, item in by_index.items():
            self.db.add(CourseMaterialChunkTopic(
                material_id=material.id, chunk_index=index,
                content_hash=hashlib.sha256(item["content"].encode()).hexdigest()[:16],
                topics=item["topics"]))
        self.db.commit()
        index_course_material_dual(db=self.db, material_id=material.id,
                                   vector_stores=stores, storage_root=self.storage_root,
                                   chunk_size=42, chunk_overlap=0)
        for topic in ("Python列表", "函数返回值"):
            found = search_course_materials_with_fallback(
                course_id="COURSE_INDEX", topic=topic, query=topic,
                db=self.db, vector_stores=stores)
            self.assertEqual(found["status"], "success")
            self.assertTrue(all(row["topic"] == topic for row in found["retrieved_chunks"]))
        documents, _ = build_material_chunk_documents(
            material=material, text="Python列表与函数返回值都在这一段中。")
        self.assertEqual({item.metadata["topic"] for item in documents},
                         {"Python列表", "函数返回值"})

    def test_blank_topic_uses_document_headings_as_reviewable_suggestions(self):
        content = "## 列表索引\n索引从0开始。\n\n## 函数返回值\nreturn 返回结果。"
        material = self.create_material("headings.md", "综合讲义", "", content)
        candidates, overrides = get_material_topic_assignments(self.db, material, content)
        self.assertEqual(candidates, ["列表索引", "函数返回值"])
        documents, _ = build_material_chunk_documents(
            material=material, text=content, candidate_topics=candidates,
            topic_overrides=overrides, chunk_size=24, chunk_overlap=0)
        self.assertIn("列表索引", {doc.metadata["topic"] for doc in documents})
        self.assertIn("函数返回值", {doc.metadata["topic"] for doc in documents})
        self.assertTrue(all(doc.metadata["topic_review_required"] for doc in documents))
        self.assertTrue(all(not doc.metadata["topic_reviewed"] for doc in documents))

    def test_section_heading_can_suggest_related_course_topic(self):
        material = self.create_material(
            "related.md", "综合讲义", "", "## 列表索引\n第一个位置从0开始。")
        documents, _ = build_material_chunk_documents(
            material=material, text="## 列表索引\n第一个位置从0开始。",
            candidate_topics=["Python列表"], chunk_size=80, chunk_overlap=0)
        self.assertEqual(documents[0].metadata["topic"], "Python列表")
        self.assertTrue(documents[0].metadata["topic_review_required"])

    def test_reviewed_topic_reindexes_and_old_content_override_is_ignored(self):
        material = self.create_material("review.md", "待复核", "Python列表,函数返回值",
                                        "这段介绍 return 的用途。")
        stores = {backend: build_course_vector_store(
            backend=backend, embedding_function=self.embeddings,
            chroma_client=self.chroma_client)
            for backend in ("primary", "backup")}
        index_course_material_dual(db=self.db, material_id=material.id,
                                   vector_stores=stores, storage_root=self.storage_root)
        self.assertEqual(stores["primary"].get(where={"material_id": material.id})["metadatas"][0]["topic"], "通用")
        unreviewed = search_course_materials_with_fallback(
            course_id="COURSE_INDEX", topic="循环控制", query="return 的用途",
            db=self.db, vector_stores=stores)
        self.assertEqual(unreviewed["status"], "topic_candidates_need_review")
        self.assertTrue(any(row["material_id"] == material.id for row in unreviewed["candidates"]))
        digest = hashlib.sha256("这段介绍 return 的用途。".encode()).hexdigest()[:16]
        self.db.add(CourseMaterialChunkTopic(material_id=material.id, chunk_index=0,
                                             content_hash=digest, topics=["函数返回值"]))
        self.db.commit()
        rebuilt = index_course_material_dual(db=self.db, material_id=material.id,
                                             vector_stores=stores, storage_root=self.storage_root)
        self.assertEqual(rebuilt["backends"], {"primary": "indexed", "backup": "indexed"})
        self.assertEqual(stores["primary"].get(where={"material_id": material.id})["metadatas"][0]["topic"], "函数返回值")
        assignment = self.db.get(CourseMaterialChunkTopic, (material.id, 0))
        assignment.content_hash = "0" * 16
        self.db.commit()
        rebuilt = index_course_material_dual(db=self.db, material_id=material.id,
                                             vector_stores=stores, storage_root=self.storage_root)
        self.assertEqual(rebuilt["backends"], {"primary": "indexed", "backup": "indexed"})
        self.assertEqual(stores["primary"].get(where={"material_id": material.id})["metadatas"][0]["topic"], "通用")

    def test_primary_and_backup_collections_are_separate(self):
        primary = build_course_vector_store(
            backend="primary",
            embedding_function=self.embeddings,
            chroma_client=self.chroma_client,
        )
        backup = build_course_vector_store(
            backend="backup",
            embedding_function=self.embeddings,
            chroma_client=self.chroma_client,
        )
        self.assertEqual(primary._collection.name, COURSE_VECTOR_COLLECTION_PRIMARY)
        self.assertEqual(backup._collection.name, COURSE_VECTOR_COLLECTION_BACKUP)
        primary.add_texts(["仅在主索引中的资料"], ids=["primary-only"])
        self.assertEqual(primary.get(ids=["primary-only"])["ids"], ["primary-only"])
        self.assertEqual(backup.get(ids=["primary-only"])["ids"], [])

    def test_dual_backend_requires_matching_embedding_function(self):
        with self.assertRaisesRegex(ValueError, "显式提供"):
            build_course_vector_store(backend="primary", chroma_client=self.chroma_client)
        with self.assertRaisesRegex(ValueError, "未知的向量后端"):
            build_course_vector_store(backend="other", chroma_client=self.chroma_client)

    def test_dual_index_and_query_failover_and_cleanup(self):
        material = self.create_material("dual.md", "双后端资料", "Python列表",
                                        "# Python列表\n\n索引从0开始，长度为3时最大索引是2。")
        stores = {backend: build_course_vector_store(
            backend=backend, embedding_function=self.embeddings,
            chroma_client=self.chroma_client)
            for backend in ("primary", "backup")}
        result = index_course_material_dual(
            db=self.db, material_id=material.id, vector_stores=stores,
            storage_root=self.storage_root)
        self.assertEqual(result["backends"], {"primary": "indexed", "backup": "indexed"})
        for backend in stores:
            record = self.db.get(CourseMaterialEmbeddingIndex, (material.id, backend))
            self.assertEqual(record.status, "indexed")
            self.assertEqual(len(stores[backend].get()["ids"]), record.chunk_count)
        self.assertEqual(index_course_material_dual(
            db=self.db, material_id=material.id, vector_stores=stores,
            storage_root=self.storage_root)["backends"],
            {"primary": "already_indexed", "backup": "already_indexed"})

        primary_failing = build_course_vector_store(
            backend="primary", embedding_function=UnavailableQueryEmbeddings(),
            chroma_client=self.chroma_client)
        found = search_course_materials_with_fallback(
            course_id="COURSE_INDEX", topic="Python列表", query="最大索引",
            db=self.db, vector_stores={"primary": primary_failing, "backup": stores["backup"]})
        self.assertEqual(found["status"], "success")
        self.assertEqual(found["embedding_backend"], "backup")
        self.assertEqual(found["retrieved_chunks"][0]["material_id"], material.id)
        denied = get_course_material_chunk_with_fallback(
            course_id="OTHER_COURSE", chunk_id=found["retrieved_chunks"][0]["chunk_id"],
            db=self.db, vector_stores={"legacy": stores["primary"]})
        self.assertEqual(denied["status"], "chunk_not_found")

        backup_record = self.db.get(CourseMaterialEmbeddingIndex, (material.id, "backup"))
        backup_record.status = "failed"
        self.db.commit()
        unavailable = search_course_materials_with_fallback(
            course_id="COURSE_INDEX", topic="Python列表", query="最大索引",
            db=self.db, vector_stores={"primary": primary_failing, "backup": stores["backup"]})
        self.assertEqual(unavailable["status"], "embedding_unavailable")
        backup_record.status = "indexed"
        self.db.commit()

        self.assertTrue(remove_course_material_from_index(
            db=self.db, material_id=material.id, vector_stores=stores))
        self.assertIsNone(self.db.get(CourseMaterialEmbeddingIndex, (material.id, "primary")))
        self.assertIsNone(self.db.get(CourseMaterialEmbeddingIndex, (material.id, "backup")))
        self.assertEqual(stores["primary"].get()["ids"], [])
        self.assertEqual(stores["backup"].get()["ids"], [])

    def test_primary_index_failure_does_not_block_backup(self):
        material = self.create_material("fallback.md", "降级资料", "Python列表",
                                        "列表索引从0开始。")
        primary = MagicMock()
        primary.get.return_value = {"ids": []}
        primary.add_documents.side_effect = EmbeddingUnavailable("模拟主服务断连")
        backup = build_course_vector_store(
            backend="backup", embedding_function=self.embeddings,
            chroma_client=self.chroma_client)
        result = index_course_material_dual(
            db=self.db, material_id=material.id,
            vector_stores={"primary": primary, "backup": backup},
            storage_root=self.storage_root)
        self.assertEqual(result["backends"], {"primary": "failed", "backup": "indexed"})
        self.assertEqual(self.db.get(CourseMaterialEmbeddingIndex,
                                     (material.id, "primary")).status, "failed")
        self.assertEqual(self.db.get(CourseMaterialEmbeddingIndex,
                                     (material.id, "backup")).status, "indexed")
        self.assertTrue(backup.get()["ids"])

    def test_text_cleaning_and_chunk_metadata(self):
        material = self.create_material(
            "list.md",
            "列表讲义",
            "Python列表",
            "# Python列表\r\n\r\n\r\n索引从0开始。\x00",
        )
        cleaned = clean_material_text(
            "第一段\r\n\r\n\r\n第二段\x00"
        )
        documents, chunk_ids = build_material_chunk_documents(
            material=material,
            text=(
                "# Python列表\n\n"
                "索引从0开始。列表支持增加和删除元素。"
            ),
            chunk_size=30,
            chunk_overlap=5,
        )

        self.assertEqual(cleaned, "第一段\n\n第二段")
        self.assertGreaterEqual(len(documents), 2)
        self.assertEqual(len(documents), len(chunk_ids))
        self.assertEqual(
            documents[0].metadata["course_id"],
            "COURSE_INDEX",
        )
        self.assertEqual(
            documents[0].metadata["topic"],
            "Python列表",
        )
        self.assertEqual(
            documents[0].metadata["source_type"],
            "teacher",
        )
        self.assertEqual(
            documents[0].metadata["chunk_id"],
            chunk_ids[0],
        )

    def test_material_is_persisted_in_chroma_with_metadata(self):
        material = self.create_material(
            "return.md",
            "函数返回值讲义",
            "函数返回值",
            (
                "# 函数返回值\n\n"
                "return 用于返回函数结果。\n\n"
                "没有显式 return 时返回 None。"
            ),
        )
        store = self.make_store()

        result = index_course_material(
            db=self.db,
            material_id=material.id,
            vector_store=store,
            storage_root=self.storage_root,
            chunk_size=35,
            chunk_overlap=5,
            embedding_model_name="test-embedding",
        )
        stored = store.get(
            where={"material_id": material.id},
            include=["metadatas", "documents"],
        )
        index_record = self.db.get(
            CourseMaterialIndex,
            material.id,
        )

        self.assertEqual(result["status"], "indexed")
        self.assertGreater(result["chunk_count"], 1)
        self.assertEqual(
            len(stored["ids"]),
            result["chunk_count"],
        )
        self.assertTrue(all(
            metadata["course_id"] == "COURSE_INDEX"
            for metadata in stored["metadatas"]
        ))
        self.assertTrue(all(
            metadata["topic"] == "函数返回值"
            for metadata in stored["metadatas"]
        ))
        self.assertEqual(index_record.status, "indexed")
        self.assertEqual(
            index_record.chunk_count,
            result["chunk_count"],
        )

    def test_reindexing_unchanged_material_is_idempotent(self):
        material = self.create_material(
            "idempotent.md",
            "幂等资料",
            "Python列表",
            "列表索引从0开始。",
        )
        store = self.make_store()
        first = index_course_material(
            db=self.db,
            material_id=material.id,
            vector_store=store,
            storage_root=self.storage_root,
            embedding_model_name="test-embedding",
        )
        second = index_course_material(
            db=self.db,
            material_id=material.id,
            vector_store=store,
            storage_root=self.storage_root,
            embedding_model_name="test-embedding",
        )
        stored = store.get(
            where={"material_id": material.id},
            include=[],
        )

        self.assertEqual(first["status"], "indexed")
        self.assertEqual(second["status"], "already_indexed")
        self.assertEqual(len(stored["ids"]), first["chunk_count"])

    def test_multiple_materials_share_collection_without_overwrite(self):
        first = self.create_material(
            "list.md",
            "列表资料",
            "Python列表",
            "列表索引从0开始。",
        )
        second = self.create_material(
            "return.md",
            "函数资料",
            "函数返回值",
            "函数没有显式return时返回None。",
        )
        store = self.make_store()

        results = index_ready_course_materials(
            db=self.db,
            course_id="COURSE_INDEX",
            vector_store=store,
            storage_root=self.storage_root,
        )
        first_chunks = store.get(
            where={"material_id": first.id},
            include=[],
        )["ids"]
        second_chunks = store.get(
            where={"material_id": second.id},
            include=[],
        )["ids"]

        self.assertEqual(len(results), 2)
        self.assertTrue(first_chunks)
        self.assertTrue(second_chunks)
        self.assertTrue(
            set(first_chunks).isdisjoint(second_chunks)
        )

    def test_deleting_material_removes_chunks_and_index_record(self):
        material = self.create_material(
            "delete.md",
            "待删除资料",
            "Python列表",
            "列表索引从0开始。",
        )
        material_id = material.id
        store = self.make_store()
        index_course_material(
            db=self.db,
            material_id=material_id,
            vector_store=store,
            storage_root=self.storage_root,
            embedding_model_name="test-embedding",
        )

        delete_owned_course_material(
            db=self.db,
            user_id="TEACHER_INDEX",
            material_id=material_id,
            expected_source_type="teacher",
            storage_root=self.storage_root,
            vector_store=store,
        )

        self.assertEqual(
            store.get(
                where={"material_id": material_id},
                include=[],
            )["ids"],
            [],
        )
        self.assertIsNone(
            self.db.get(CourseMaterialIndex, material_id)
        )


if __name__ == "__main__":
    unittest.main()
