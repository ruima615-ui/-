#教师录入题目的格式
from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


QuestionType = Literal[
    "single_choice",
    "multiple_choice",
    "true_false",
    "fill_blank",
    "short_answer",
]


class CreateQuestionRequest(BaseModel):
    """教师创建题目时提交的数据。"""

    model_config = ConfigDict(
        extra="forbid",
    )

    course_id: str = Field(
        min_length=1,
        max_length=50,
    )
    question_type: QuestionType
    topic: str = Field(
        min_length=1,
        max_length=100,
    )
    stem: str = Field(min_length=1)

    options: dict[str, str] | None = None
    answer_key: str | list[str] | bool
    explanation: str | None = None
    max_score: float = Field(
        default=1.0,
        gt=0,
    )

    knowledge_count_level: int = Field(
        default=0,
        ge=0,
        le=2,
    )
    reasoning_level: int = Field(
        default=0,
        ge=0,
        le=2,
    )
    transfer_level: int = Field(
        default=0,
        ge=0,
        le=2,
    )
    distractor_level: int = Field(
        default=0,
        ge=0,
        le=2,
    )


class QuestionResponse(BaseModel):
    """创建题目后返回的数据。"""

    question_id: str#问题id,后端随机生成
    course_id: str#该题属于哪门课程
    question_type: str#题目类型
    topic: str#题目知识点
    stem: str#题干
#四个难度维度
    knowledge_count_level: int#涉及知识点数量
    reasoning_level: int#需要多深的推理
    transfer_level: int#是否需要迁移知识点
    distractor_level: int#干扰强度

    difficulty_score: int#综合四个维度映射的题目难度
    difficulty: str
