"""Expose the existing course material search service over MCP stdio."""

from mcp.server.fastmcp import FastMCP

from app.services.material_search_service import search_course_materials_with_fallback


mcp = FastMCP("course-material-search")


@mcp.tool()
def search_course_material(course_id: str, topic: str, query: str) -> dict:
    """Search indexed course material; return chunks, source metadata and status.

    The caller must supply a course_id obtained from an authorized session.
    This server has no student identity and exposes no wrong-question records.
    """
    return search_course_materials_with_fallback(
        course_id=course_id,
        topic=topic,
        query=query,
        top_k=3,
    )


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
