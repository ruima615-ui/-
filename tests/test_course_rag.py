import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import rag_tools
from student_agent import (
    analyze_current_course_wrong_questions,
    get_current_course_wrong_questions,
    searchlearningmaterial,
)


def write_course_material(
    knowledge_root,
    course_id,
    file_name,
    content,
):
    """创建一门测试课程及其资料索引。"""

    course_dir = knowledge_root / course_id
    course_dir.mkdir()

    index_data = {
        "topics": {
            "共享知识点": file_name,
        }
    }
    (course_dir / "materials.json").write_text(
        json.dumps(
            index_data,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (course_dir / file_name).write_text(
        content,
        encoding="utf-8",
    )


def fake_retrieve_chunks(chunks, query, top_k=3):
    """避免测试依赖本地 Ollama 服务。"""

    return [
        {
            "chunk_id": index,
            "score": 1.0,
            "content": chunk,
        }
        for index, chunk in enumerate(
            chunks[:top_k],
            start=1,
        )
    ]


class CourseRagIsolationTests(unittest.TestCase):
    def test_course_a_cannot_retrieve_course_b_material(
        self,
    ):
        """相同知识点也必须按照 course_id 隔离资料。"""

        with tempfile.TemporaryDirectory() as directory:
            knowledge_root = Path(directory)

            write_course_material(
                knowledge_root=knowledge_root,
                course_id="COURSE_A",
                file_name="course_a.md",
                content="课程 A 专属内容：Python 列表。",
            )
            write_course_material(
                knowledge_root=knowledge_root,
                course_id="COURSE_B",
                file_name="course_b.md",
                content="课程 B 专属内容：Java 数组。",
            )

            with (
                patch.object(
                    rag_tools,
                    "KNOWLEDGE_DIR",
                    knowledge_root,
                ),
                patch.object(
                    rag_tools,
                    "retrieve_chunks_by_embedding",
                    fake_retrieve_chunks,
                ),
            ):
                course_a_result = (
                    rag_tools.searchlearningmaterial(
                        course_id="COURSE_A",
                        topic="共享知识点",
                        query="解释这个知识点",
                    )
                )
                course_b_result = (
                    rag_tools.searchlearningmaterial(
                        course_id="COURSE_B",
                        topic="共享知识点",
                        query="解释这个知识点",
                    )
                )

        self.assertEqual(
            course_a_result["status"],
            "success",
        )
        self.assertEqual(
            course_a_result["course_id"],
            "COURSE_A",
        )
        self.assertEqual(
            course_a_result["source"],
            "course_a.md",
        )

        course_a_content = json.dumps(
            course_a_result["retrieved_chunks"],
            ensure_ascii=False,
        )
        self.assertIn(
            "课程 A 专属内容",
            course_a_content,
        )
        self.assertNotIn(
            "课程 B 专属内容",
            course_a_content,
        )

        self.assertEqual(
            course_b_result["status"],
            "success",
        )
        self.assertEqual(
            course_b_result["course_id"],
            "COURSE_B",
        )
        self.assertEqual(
            course_b_result["source"],
            "course_b.md",
        )

        course_b_content = json.dumps(
            course_b_result["retrieved_chunks"],
            ensure_ascii=False,
        )
        self.assertIn(
            "课程 B 专属内容",
            course_b_content,
        )
        self.assertNotIn(
            "课程 A 专属内容",
            course_b_content,
        )

    def test_course_id_cannot_escape_knowledge_directory(
        self,
    ):
        """拒绝使用路径穿越方式访问其他目录。"""

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(
                rag_tools,
                "KNOWLEDGE_DIR",
                Path(directory),
            ):
                result = (
                    rag_tools.searchlearningmaterial(
                        course_id="../COURSE_B",
                        topic="共享知识点",
                        query="尝试越界读取",
                    )
                )

        self.assertEqual(
            result["status"],
            "invalid_course_id",
        )

    def test_rag_tool_schema_hides_course_context(self):
        """模型只能填写 topic 和 query。"""

        rag_schema = (
            searchlearningmaterial
            .tool_call_schema
            .model_json_schema()
        )
        properties = rag_schema["properties"]

        self.assertEqual(
            set(properties),
            {
                "topic",
                "query",
            },
        )
        self.assertNotIn(
            "enum",
            properties["topic"],
        )

        analyze_schema = (
            analyze_current_course_wrong_questions
            .tool_call_schema
            .model_json_schema()
        )
        details_schema = (
            get_current_course_wrong_questions
            .tool_call_schema
            .model_json_schema()
        )

        self.assertEqual(
            analyze_schema["properties"],
            {},
        )
        self.assertEqual(
            details_schema["properties"],
            {},
        )


if __name__ == "__main__":
    unittest.main()
