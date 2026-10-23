#规定学生复习计划的格式
from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


ErrorType = Literal[
    "concept_misunderstanding",
    "reasoning_error",
    "knowledge_application_error",
    "answer_format_error",
    "insufficient_evidence",
]#错误类型

ConfidenceLevel = Literal[
    "high",
    "medium",
    "low",
]#错误诊断置信度
PriorityLevel = Literal[
    "high",
    "medium",
    "low",
    "insufficient_data",
]#薄弱优先级

ReviewPlanStatus = Literal[
    "success",
    "partial",
    "no_recorded_wrong_questions",
    "course_materials_not_configured",
    "course_materials_insufficient",
    "material_retrieval_failed",
    "insufficient_evidence",
    "foundation_failed",
    "diagnosis_failed",
    "plan_failed",
]#复习计划的状态
class StrictSchema(BaseModel):
    """复习计划相关 Schema 的公共父类。"""

    model_config = ConfigDict(
        extra="forbid",
    )


class DifficultyDistribution(StrictSchema):
    """某个知识点的错题难度分布。"""

    easy: int = Field(
        ge=0,
    )
    medium: int = Field(
        ge=0,
    )
    hard: int = Field(
        ge=0,
    )


class WeakTopicSummary(StrictSchema):
    """学生的一个薄弱知识点。"""

    topic: str = Field(
        min_length=1,
        max_length=100,
    )

    priority_rank: int = Field(
        ge=1,
        le=2,
    )

    priority_level: PriorityLevel

    priority_score: float | None = Field(
        default=None,
        ge=0,
        le=1,
    )

    wrong_attempts: int = Field(
        ge=0,
    )

    total_attempts: int | None = Field(
        default=None,
        ge=0,
    )

    error_rate: float | None = Field(
        default=None,
        ge=0,
        le=1,
    )

    difficulty_distribution: DifficultyDistribution

    analysis_basis: Literal[
        "exam_history",
        "wrong_records_only",
    ]


class WrongQuestionEvidence(StrictSchema):
    """诊断错误类型所使用的直接错题证据。"""

    question_id: str = Field(
        min_length=1,
        max_length=100,
    )

    topic: str = Field(
        min_length=1,
        max_length=100,
    )

    stem: str | None = Field(
        min_length=1,
    )

    student_answer: str | None = Field(
        min_length=1,
    )

    correct_answer: str | None = Field(
        min_length=1,
    )

    explanation: str | None = None


class WrongQuestionDiagnosis(StrictSchema):
    """根据错题证据得到的初步错误类型诊断。"""

    question_id: str = Field(
        min_length=1,
        max_length=100,
    )

    topic: str = Field(
        min_length=1,
        max_length=100,
    )

    error_type: ErrorType

    direct_evidence: list[str] = Field(
        min_length=1,
        max_length=6,
    )

    inference_reason: str = Field(
        min_length=1,
    )

    alternative_explanations: list[str] = Field(
        default_factory=list,
        max_length=3,
    )

    confidence: ConfidenceLevel


class CourseMaterialEvidence(StrictSchema):
    """课程 RAG 返回的一条资料证据。"""

    topic: str = Field(
        min_length=1,
        max_length=100,
    )

    source_id: str = Field(
        min_length=1,
        max_length=200,
    )

    source_title: str = Field(
        min_length=1,
        max_length=200,
    )

    source_type: Literal[
        "teacher",
        "official",
    ]

    original_filename: str = Field(
        min_length=1,
        max_length=255,
    )

    chunk_id: str = Field(
        min_length=1,
        max_length=200,
    )

    section: str | None = Field(
        default=None,
        max_length=200,
    )

    page_number: int | None = Field(
        default=None,
        ge=1,
    )

    content_excerpt: str = Field(
        min_length=1,
        max_length=1500,
    )

    relevance_score: float | None = Field(
        default=None,
        ge=0,
        le=1,
    )


class ReviewTask(StrictSchema):
    """针对一个薄弱知识点生成的一项复习任务。"""

    task_id: str = Field(
        min_length=1,
        max_length=100,
    )

    topic: str = Field(
        min_length=1,
        max_length=100,
    )

    priority_rank: int = Field(
        ge=1,
        le=2,
    )

    objective: str = Field(
        min_length=1,
        max_length=500,
    )

    related_error_types: list[ErrorType] = Field(
        min_length=1,
        max_length=3,
    )

    action_steps: list[str] = Field(
        min_length=1,
        max_length=5,
    )

    material_chunk_ids: list[str] = Field(
        default_factory=list,
        max_length=2,
    )

    self_check_questions: list[str] = Field(
        min_length=1,
        max_length=3,
    )


class ReviewPlanScope(StrictSchema):
    """复习计划所处的可信课程范围。"""

    course_id: str = Field(
        min_length=1,
        max_length=50,
    )

    top_k: int = Field(
        default=2,
        ge=1,
        le=2,
    )


class ReviewPlanResponse(StrictSchema):
    """学生 Agent 返回的完整结构化复习计划。"""

    status: ReviewPlanStatus

    scope: ReviewPlanScope

    weak_topics: list[WeakTopicSummary] = Field(
        default_factory=list,
        max_length=2,
    )

    wrong_question_evidence: list[
        WrongQuestionEvidence
    ] = Field(
        default_factory=list,
        max_length=4,
    )

    diagnoses: list[
        WrongQuestionDiagnosis
    ] = Field(
        default_factory=list,
        max_length=4,
    )

    material_evidence: list[
        CourseMaterialEvidence
    ] = Field(
        default_factory=list,
        max_length=4,
    )

    review_tasks: list[ReviewTask] = Field(
        default_factory=list,
        max_length=2,
    )

    limitations: list[str] = Field(
        default_factory=list,
        max_length=5,
    )
