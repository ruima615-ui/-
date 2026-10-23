import math
import unittest
from unittest.mock import MagicMock, patch

import chromadb
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

import rag_tools
from app.services.material_index_service import (
    build_course_vector_store,
)
from app.services.material_search_service import (
    resolve_indexed_topic,
    search_indexed_course_materials,
)


class KeywordEmbeddings(Embeddings):
    """离线测试向量：用固定语义维度验证排序，不访问 Ollama。"""

    KEYWORDS = (
        ("列表", "list", "索引"),
        ("函数", "return", "返回值"),
        ("追加", "append", "增加"),
        ("删除", "remove", "pop"),
        ("机密", "secret", "独有"),
    )

    @classmethod
    def _embed(cls, text: str) -> list[float]:
        lowered = text.casefold()
        vector = [
            float(sum(lowered.count(word) for word in words))
            for words in cls.KEYWORDS
        ]
        # 与项目现有离线索引测试保持 8 维；常量维度也避免零向量。
        vector.extend([0.1, 0.0, 0.0])
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


def make_document(
    *,
    content: str,
    course_id: str,
    topic: str,
    material_id: str,
    title: str,
    chunk_index: int = 0,
) -> Document:
    chunk_id = f"{material_id}:chunk:{chunk_index}"
    return Document(
        page_content=content,
        metadata={
            "chunk_id": chunk_id,
            "course_id": course_id,
            "topic": topic,
            "material_id": material_id,
            "material_title": title,
            "section": topic,
            "source_type": "teacher",
            "original_filename": f"{material_id}.md",
            "chunk_index": chunk_index,
        },
    )


class ChromaCourseRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.store = build_course_vector_store(
            embedding_function=KeywordEmbeddings(),
            chroma_client=chromadb.EphemeralClient(),
        )
        documents = [
            make_document(
                content="课程A：列表索引从 0 开始。",
                course_id="COURSE_A",
                topic="Python列表",
                material_id="A_LIST_1",
                title="课程A列表基础",
            ),
            make_document(
                content="课程A：append 可以向列表末尾追加元素。",
                course_id="COURSE_A",
                topic="Python列表",
                material_id="A_LIST_2",
                title="课程A列表操作",
            ),
            make_document(
                content="课程A：return 用于返回函数结果。",
                course_id="COURSE_A",
                topic="函数返回值",
                material_id="A_RETURN",
                title="课程A函数",
            ),
            make_document(
                content="课程B机密独有内容：列表索引和追加的详细说明。",
                course_id="COURSE_B",
                topic="Python列表",
                material_id="B_SECRET",
                title="课程B专属资料",
            ),
        ]
        self.store.add_documents(
            documents=documents,
            ids=[document.metadata["chunk_id"] for document in documents],
        )

    def test_course_filter_prevents_cross_course_retrieval(self):
        result = search_indexed_course_materials(
            course_id="COURSE_A",
            topic="Python列表",
            query="机密独有的列表索引追加内容",
            top_k=5,
            vector_store=self.store,
        )

        self.assertEqual(result["status"], "success")
        self.assertTrue(result["retrieved_chunks"])
        self.assertTrue(all(
            chunk["course_id"] == "COURSE_A"
            for chunk in result["retrieved_chunks"]
        ))
        self.assertNotIn(
            "B_SECRET",
            {chunk["material_id"] for chunk in result["retrieved_chunks"]},
        )

    def test_topic_filter_and_semantic_ranking(self):
        result = search_indexed_course_materials(
            course_id="COURSE_A",
            topic="Python列表索引",
            query="怎样 append 追加元素",
            top_k=2,
            vector_store=self.store,
        )

        self.assertEqual(result["topic"], "Python列表")
        self.assertTrue(all(
            chunk["topic"] == "Python列表"
            for chunk in result["retrieved_chunks"]
        ))
        self.assertEqual(
            result["retrieved_chunks"][0]["material_id"],
            "A_LIST_2",
        )
        self.assertNotIn(
            "A_RETURN",
            {chunk["material_id"] for chunk in result["retrieved_chunks"]},
        )

    def test_multiple_sources_return_traceable_evidence(self):
        result = search_indexed_course_materials(
            course_id="COURSE_A",
            topic="Python列表",
            query="列表索引和追加",
            top_k=5,
            vector_store=self.store,
        )

        self.assertEqual(result["source_count"], 2)
        self.assertEqual(len(result["retrieved_chunks"]), 2)
        required_fields = {
            "chunk_id",
            "content",
            "relevance_score",
            "course_id",
            "topic",
            "material_id",
            "material_title",
            "section",
            "source_type",
            "original_filename",
            "chunk_index",
        }
        self.assertTrue(all(
            required_fields <= set(chunk)
            for chunk in result["retrieved_chunks"]
        ))

    def test_missing_course_topic_and_invalid_top_k_are_explicit(self):
        no_course = search_indexed_course_materials(
            course_id="COURSE_C",
            topic="Python列表",
            query="列表",
            vector_store=self.store,
        )
        no_topic = search_indexed_course_materials(
            course_id="COURSE_A",
            topic="字典",
            query="字典",
            vector_store=self.store,
        )
        invalid_k = search_indexed_course_materials(
            course_id="COURSE_A",
            topic="Python列表",
            query="列表",
            top_k=0,
            vector_store=self.store,
        )

        self.assertEqual(
            no_course["status"],
            "course_materials_not_indexed",
        )
        self.assertEqual(
            no_topic["status"],
            "topic_materials_not_indexed",
        )
        self.assertEqual(invalid_k["status"], "invalid_top_k")

    def test_topic_resolution_is_deterministic(self):
        self.assertEqual(
            resolve_indexed_topic(
                requested_topic=" Python 列表索引 ",
                available_topics=["Python列表", "函数返回值"],
            ),
            "Python列表",
        )
        self.assertIsNone(resolve_indexed_topic(
            requested_topic="字典",
            available_topics=["Python列表", "函数返回值"],
        ))


class RagCompatibilityRoutingTests(unittest.TestCase):
    @patch.object(rag_tools, "search_course_materials_with_fallback")
    @patch.object(rag_tools, "has_indexed_course_materials")
    @patch.object(rag_tools, "SessionLocal")
    def test_indexed_course_uses_chroma_path(
        self,
        session_factory,
        has_indexed,
        chroma_search,
    ):
        session_factory.return_value = MagicMock()
        has_indexed.return_value = True
        chroma_search.return_value = {"status": "success"}

        result = rag_tools.searchlearningmaterial(
            course_id="COURSE_A",
            topic="Python列表",
            query="列表索引",
        )

        self.assertEqual(result["status"], "success")
        chroma_search.assert_called_once_with(
            course_id="COURSE_A",
            topic="Python列表",
            query="列表索引",
            top_k=3,
        )
        session_factory.return_value.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
