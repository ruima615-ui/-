from datetime import datetime
from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


CourseMaterialStatus = Literal[
    "processing",
    "ready_for_indexing",
    "parse_failed",
]

CourseMaterialSourceType = Literal[
    "teacher",
    "official",
]


class CourseMaterialTitleUpdate(BaseModel):
    """资料所有者可修改的字段。"""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(
        min_length=1,
        max_length=200,
    )


class CourseMaterialResponse(BaseModel):
    """教师上传课程资料后的返回数据。"""

    model_config = ConfigDict(
        from_attributes=True,
        extra="forbid",
    )

    material_id: str
    course_id: str
    uploaded_by: str
    source_type: CourseMaterialSourceType
    topic: str
    title: str
    original_filename: str
    file_extension: str
    mime_type: str | None
    size_bytes: int
    checksum_sha256: str
    extracted_text_length: int
    status: CourseMaterialStatus
    parse_error: str | None
    created_at: datetime
