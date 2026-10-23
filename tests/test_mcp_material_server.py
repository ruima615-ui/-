import unittest
from unittest.mock import patch

from app.mcp.material_server import search_course_material


class MaterialMcpServerTests(unittest.TestCase):
    def test_server_delegates_to_existing_course_search_service(self):
        expected = {"status": "success", "retrieved_chunks": [{
            "chunk_id": "MAT_1:chunk:0", "original_filename": "lesson.md",
        }]}
        with patch(
            "app.mcp.material_server.search_course_materials_with_fallback",
            return_value=expected,
        ) as service:
            result = search_course_material(
                course_id="PYTHON101", topic="Python列表", query="索引从哪里开始",
            )
        self.assertEqual(result, expected)
        service.assert_called_once_with(
            course_id="PYTHON101", topic="Python列表",
            query="索引从哪里开始", top_k=3,
        )


if __name__ == "__main__":
    unittest.main()
