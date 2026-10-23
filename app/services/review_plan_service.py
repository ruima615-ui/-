import json
import logging

from sqlalchemy.orm import Session

from app.schemas.review_plan import (
    CourseMaterialEvidence,
    ReviewPlanResponse,
    ReviewTask,
    WeakTopicSummary,
    WrongQuestionDiagnosis,
    WrongQuestionEvidence,
)
from app.services.material_search_service import (
    search_course_materials_with_fallback as search_indexed_course_materials,
)
from app.services.wrong_question_service import (
    analyze_course_wrong_questions,
    get_course_wrong_question_details,
)


LOGGER = logging.getLogger(__name__)


# 复习计划固定选择优先级最高的两个知识点。
REVIEW_PLAN_TOP_K = 2

# 每个知识点最多选择两道错题作为后续诊断证据。
MAX_EVIDENCE_QUESTIONS_PER_TOPIC = 2

# 每个薄弱知识点最多引用两个课程资料 Chunk，两个知识点合计不超过 Schema 的 4 条。
MATERIAL_CHUNKS_PER_TOPIC = 2


ERROR_TYPE_RETRIEVAL_TERMS = {
    "concept_misunderstanding": "概念 定义 基本规则 常见误解",
    "reasoning_error": "推理步骤 条件判断 计算过程",
    "knowledge_application_error": "知识应用 例题 迁移练习",
    "answer_format_error": "答题格式 规范表达",
    "insufficient_evidence": "核心概念 基础讲解",
}


def _select_top_weak_topics(
    topic_analysis: list[dict],
) -> list[dict]:
    """将薄弱分析结果转换成复习计划 Schema 所需的 Top-K 数据。"""

    selected_topics = []

    for rank, topic_data in enumerate(
        topic_analysis[:REVIEW_PLAN_TOP_K],
        start=1,
    ):
        weak_topic = WeakTopicSummary(
            topic=topic_data["topic"],
            priority_rank=rank,
            priority_level=topic_data["priority_level"],
            priority_score=topic_data["priority_score"],
            wrong_attempts=topic_data["wrong_attempts"],
            total_attempts=topic_data["total_attempts"],
            error_rate=topic_data["error_rate"],
            difficulty_distribution=(
                topic_data["difficulty_distribution"]
            ),
            analysis_basis=topic_data["analysis_basis"],
        )
        selected_topics.append(
            weak_topic.model_dump()
        )

    return selected_topics


def _select_evidence_questions(
    wrong_questions: list[dict],
    selected_topics: list[dict],
) -> list[dict]:
    """按 Top-K 顺序为每个知识点选择有限数量的错题证据。"""

    selected_questions = []

    for topic_data in selected_topics:
        topic = topic_data["topic"]
        topic_questions = [
            question
            for question in wrong_questions
            if question.get("topic") == topic
        ]
        selected_questions.extend(
            topic_questions[
                :MAX_EVIDENCE_QUESTIONS_PER_TOPIC
            ]
        )

    return selected_questions


def _render_answer(
    answer,
    options: dict | None,
) -> str | None:
    """将答案转换成包含选项正文的可读文本。"""

    if answer is None:
        return None

    if isinstance(answer, list):
        rendered_items = [
            _render_answer(item, options)
            for item in answer
        ]
        return ", ".join(
            item
            for item in rendered_items
            if item is not None
        )

    if isinstance(answer, bool):
        return str(answer)

    if isinstance(answer, dict):
        return json.dumps(
            answer,
            ensure_ascii=False,
            sort_keys=True,
        )

    answer_text = str(answer)

    if (
        isinstance(options, dict)
        and answer_text in options
    ):
        return (
            f"{answer_text}: "
            f"{options[answer_text]}"
        )

    return answer_text


def _build_wrong_question_evidence(
    selected_questions: list[dict],
) -> list[dict]:
    """把数据库错题详情转换为错误诊断所需的直接证据。"""

    evidence_items = []

    for question in selected_questions:
        options = question.get("options")
        evidence = WrongQuestionEvidence(
            question_id=question["question_id"],
            topic=question["topic"],
            stem=question.get("stem"),
            student_answer=_render_answer(
                question.get("student_answer"),
                options,
            ),
            correct_answer=_render_answer(
                question.get("correct_answer"),
                options,
            ),
            explanation=question.get("explanation"),
        )
        evidence_items.append(
            evidence.model_dump()
        )

    return evidence_items


def _build_diagnosis_groups(
    selected_topics: list[dict],
    evidence_items: list[dict],
) -> list[dict]:
    """按照薄弱知识点把待诊断错题证据分组。"""

    return [
        {
            "topic": topic_data["topic"],
            "priority_rank": topic_data[
                "priority_rank"
            ],
            "evidence": [
                item
                for item in evidence_items
                if item["topic"] == topic_data["topic"]
            ],
        }
        for topic_data in selected_topics
    ]


def associate_diagnoses_with_weak_topics(
    *,
    weak_topics: list[dict],
    wrong_question_evidence: list[dict],
    diagnoses: list[dict],
) -> list[dict]:
    """
    校验诊断只能引用已选中的知识点和错题证据，并按优先级排序。

    本函数不判断模型的诊断内容是否正确，只负责阻止诊断引用
    未选中的知识点、其他题目或不匹配的题目与知识点关系。
    """

    topic_rank = {
        item["topic"]: item["priority_rank"]
        for item in weak_topics
    }
    evidence_by_question_id = {
        item["question_id"]: item
        for item in wrong_question_evidence
    }

    if len(evidence_by_question_id) != len(
        wrong_question_evidence
    ):
        raise ValueError("错题证据中存在重复的 question_id")

    if len(diagnoses) != len(wrong_question_evidence):
        raise ValueError(
            "每一道已选择的错题都必须生成一条诊断"
        )

    validated_diagnoses = []
    diagnosed_question_ids = set()

    for diagnosis_data in diagnoses:
        diagnosis = WrongQuestionDiagnosis.model_validate(
            diagnosis_data
        )

        if diagnosis.question_id in diagnosed_question_ids:
            raise ValueError(
                "同一道错题不能重复生成诊断："
                f"{diagnosis.question_id}"
            )

        evidence = evidence_by_question_id.get(
            diagnosis.question_id
        )

        if evidence is None:
            raise ValueError(
                "诊断引用了未选择的错题："
                f"{diagnosis.question_id}"
            )

        if diagnosis.topic != evidence["topic"]:
            raise ValueError(
                "诊断知识点与错题证据不一致："
                f"{diagnosis.question_id}"
            )

        if diagnosis.topic not in topic_rank:
            raise ValueError(
                "诊断引用了非 Top-K 知识点："
                f"{diagnosis.topic}"
            )

        diagnosed_question_ids.add(
            diagnosis.question_id
        )
        validated_diagnoses.append(
            diagnosis.model_dump()
        )

    evidence_order = {
        item["question_id"]: index
        for index, item in enumerate(
            wrong_question_evidence
        )
    }
    validated_diagnoses.sort(
        key=lambda item: (
            topic_rank[item["topic"]],
            evidence_order[item["question_id"]],
        )
    )

    return validated_diagnoses


def prepare_diagnosed_review_plan(
    *,
    db: Session,
    student_id: str,
    course_id: str,
    diagnoses: list[dict],
) -> dict:
    """重新读取可信基础数据，并把模型诊断关联到对应 Top-K 错题。"""

    foundation = prepare_review_plan_foundation(
        db=db,
        student_id=student_id,
        course_id=course_id,
    )

    if foundation["status"] != "success":
        return {
            **foundation,
            "diagnoses": [],
        }

    validated_diagnoses = (
        associate_diagnoses_with_weak_topics(
            weak_topics=foundation["weak_topics"],
            wrong_question_evidence=foundation[
                "wrong_question_evidence"
            ],
            diagnoses=diagnoses,
        )
    )

    return {
        **foundation,
        "diagnoses": validated_diagnoses,
        "execution_trace": [
            *foundation["execution_trace"],
            "associate_wrong_question_diagnoses",
        ],
    }


def _build_topic_material_query(
    *,
    topic: str,
    diagnoses: list[dict],
) -> str:
    """根据已校验诊断构造稳定的课程资料检索问题。"""

    error_types = []
    reasons = []

    for diagnosis in diagnoses:
        if diagnosis["topic"] != topic:
            continue

        error_type = diagnosis["error_type"]
        retrieval_terms = ERROR_TYPE_RETRIEVAL_TERMS[
            error_type
        ]
        if retrieval_terms not in error_types:
            error_types.append(retrieval_terms)

        reason = diagnosis["inference_reason"].strip()
        if reason and reason not in reasons:
            reasons.append(reason)

    query_parts = [
        topic,
        "核心知识 讲解 示例 常见错误",
        *error_types,
        *reasons,
    ]
    return " ".join(query_parts)


def _convert_material_evidence(
    *,
    expected_topic: str,
    search_result: dict,
) -> list[dict]:
    """把 Chroma Chunk 转换成复习计划的可信资料证据。"""

    evidence_items = []

    for chunk in search_result.get(
        "retrieved_chunks",
        [],
    ):
        if chunk.get("topic") != search_result.get("topic"):
            raise ValueError("课程资料 Chunk 与检索知识点不一致")

        relevance_score = chunk.get("relevance_score")
        if (
            relevance_score is not None
            and not 0 <= relevance_score <= 1
        ):
            relevance_score = None

        evidence = CourseMaterialEvidence(
            topic=expected_topic,
            source_id=chunk["material_id"],
            source_title=(
                chunk.get("material_title")
                or chunk["original_filename"]
            ),
            source_type=chunk["source_type"],
            original_filename=chunk["original_filename"],
            chunk_id=chunk["chunk_id"],
            section=chunk.get("section"),
            page_number=None,
            content_excerpt=chunk["content"][:1500],
            relevance_score=relevance_score,
        )
        evidence_items.append(evidence.model_dump())

    return evidence_items


def prepare_grounded_review_plan(
    *,
    db: Session,
    student_id: str,
    course_id: str,
    diagnoses: list[dict],
) -> dict:
    """
    校验 Top-K 错题诊断后，为每个薄弱知识点检索当前课程资料。

    本函数只准备生成复习任务所需的可信上下文，不调用大模型生成任务。
    """

    diagnosed_plan = prepare_diagnosed_review_plan(
        db=db,
        student_id=student_id,
        course_id=course_id,
        diagnoses=diagnoses,
    )

    if diagnosed_plan["status"] != "success":
        return {
            **diagnosed_plan,
            "material_evidence": [],
            "material_groups": [],
            "limitations": [],
        }

    material_evidence = []
    material_groups = []
    limitations = []
    successful_topic_count = 0

    for weak_topic in diagnosed_plan["weak_topics"]:
        topic = weak_topic["topic"]
        query = _build_topic_material_query(
            topic=topic,
            diagnoses=diagnosed_plan["diagnoses"],
        )
        try:
            search_result = search_indexed_course_materials(
                course_id=course_id,
                topic=topic,
                query=query,
                top_k=MATERIAL_CHUNKS_PER_TOPIC,
            )
            if (
                not isinstance(search_result, dict)
                or not isinstance(
                    search_result.get("status"),
                    str,
                )
            ):
                raise ValueError("课程资料检索返回格式无效")
        except Exception:
            # 单个知识点的向量服务故障不能抹掉其他已取得的可信结果。
            # 不向模型暴露底层连接信息、路径或异常堆栈。
            LOGGER.exception(
                "课程资料检索失败：course_id=%s topic=%s",
                course_id,
                topic,
            )
            search_result = {
                "status": "material_retrieval_failed",
                "course_id": course_id,
                "topic": topic,
                "message": "课程资料检索暂时不可用",
            }

        topic_evidence = []
        if search_result["status"] == "success":
            topic_evidence = _convert_material_evidence(
                expected_topic=topic,
                search_result=search_result,
            )
            material_evidence.extend(topic_evidence)
            successful_topic_count += 1
        else:
            limitations.append(
                f"知识点“{topic}”暂无可用课程资料："
                f"{search_result.get('message', search_result['status'])}"
            )

        material_groups.append({
            "topic": topic,
            "priority_rank": weak_topic["priority_rank"],
            "status": search_result["status"],
            "query": query,
            "evidence": topic_evidence,
        })

    topic_count = len(diagnosed_plan["weak_topics"])
    if successful_topic_count == topic_count:
        status = "success"
    elif successful_topic_count == 0:
        status = "course_materials_not_configured"
    else:
        status = "partial"

    return {
        **diagnosed_plan,
        "status": status,
        "material_evidence": material_evidence,
        "material_groups": material_groups,
        "limitations": limitations,
        "execution_trace": [
            *diagnosed_plan["execution_trace"],
            "retrieve_top_k_course_materials",
        ],
    }


def validate_review_tasks(
    *,
    grounded_plan: dict,
    review_tasks: list[dict],
) -> list[dict]:
    """校验模型生成的任务只能引用已验证诊断和当前知识点资料。"""

    eligible_groups = {
        group["topic"]: group
        for group in grounded_plan["material_groups"]
        if group["status"] == "success"
    }
    eligible_topics = set(eligible_groups)

    if len(review_tasks) != len(eligible_topics):
        raise ValueError(
            "每个具备课程资料的 Top-K 知识点必须且只能生成一个复习任务"
        )

    validated_tasks = [
        ReviewTask.model_validate(task)
        for task in review_tasks
    ]
    task_ids = [task.task_id for task in validated_tasks]
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("复习任务中存在重复的 task_id")

    task_topics = [task.topic for task in validated_tasks]
    if len(task_topics) != len(set(task_topics)):
        raise ValueError("同一知识点不能生成多个复习任务")
    if set(task_topics) != eligible_topics:
        raise ValueError(
            "复习任务知识点必须与具备资料证据的 Top-K 知识点完全一致"
        )

    topic_rank = {
        topic["topic"]: topic["priority_rank"]
        for topic in grounded_plan["weak_topics"]
    }
    diagnosis_types = {}
    for diagnosis in grounded_plan["diagnoses"]:
        diagnosis_types.setdefault(
            diagnosis["topic"],
            set(),
        ).add(diagnosis["error_type"])

    validated_result = []
    for task in validated_tasks:
        if task.priority_rank != topic_rank[task.topic]:
            raise ValueError(
                f"复习任务优先级与薄弱知识点不一致：{task.topic}"
            )

        trusted_error_types = diagnosis_types.get(
            task.topic,
            set(),
        )
        if not set(task.related_error_types).issubset(
            trusted_error_types
        ):
            raise ValueError(
                f"复习任务引用了未经诊断确认的错误类型：{task.topic}"
            )

        trusted_chunk_ids = {
            item["chunk_id"]
            for item in eligible_groups[task.topic]["evidence"]
        }
        submitted_chunk_ids = task.material_chunk_ids
        if not submitted_chunk_ids:
            raise ValueError(
                f"复习任务必须引用当前知识点的资料 Chunk：{task.topic}"
            )
        if len(submitted_chunk_ids) != len(
            set(submitted_chunk_ids)
        ):
            raise ValueError(
                f"复习任务包含重复的资料 Chunk：{task.topic}"
            )
        if not set(submitted_chunk_ids).issubset(
            trusted_chunk_ids
        ):
            raise ValueError(
                f"复习任务引用了不属于当前知识点的资料 Chunk：{task.topic}"
            )

        validated_result.append(task.model_dump())

    validated_result.sort(
        key=lambda task: task["priority_rank"]
    )
    return validated_result


def finalize_grounded_review_plan(
    *,
    db: Session,
    student_id: str,
    course_id: str,
    diagnoses: list[dict],
    review_tasks: list[dict],
) -> dict:
    """重新构造可信上下文，校验任务并返回最终 ReviewPlanResponse。"""

    grounded_plan = prepare_grounded_review_plan(
        db=db,
        student_id=student_id,
        course_id=course_id,
        diagnoses=diagnoses,
    )

    if grounded_plan["status"] not in {
        "success",
        "partial",
    }:
        if review_tasks:
            raise ValueError(
                "当前没有可引用的课程资料，不能提交复习任务"
            )
        validated_tasks = []
    else:
        validated_tasks = validate_review_tasks(
            grounded_plan=grounded_plan,
            review_tasks=review_tasks,
        )

    response = ReviewPlanResponse(
        status=grounded_plan["status"],
        scope=grounded_plan["scope"],
        weak_topics=grounded_plan["weak_topics"],
        wrong_question_evidence=grounded_plan[
            "wrong_question_evidence"
        ],
        diagnoses=grounded_plan.get("diagnoses", []),
        material_evidence=grounded_plan.get(
            "material_evidence",
            [],
        ),
        review_tasks=validated_tasks,
        limitations=grounded_plan.get("limitations", []),
    )
    return response.model_dump()


def prepare_review_plan_foundation(
    db: Session,
    student_id: str,
    course_id: str,
) -> dict:
    """
    按固定顺序准备结构化复习计划所需的基础数据。

    当前阶段的执行顺序：
    1. 分析当前课程薄弱知识点；
    2. 固定选择优先级最高的 Top-2；
    3. 读取当前课程错题；
    4. 为每个知识点选择最多两道诊断证据题。

    错误类型诊断和课程 RAG 会在后续阶段继续接入此流程。
    """

    execution_trace = []

    analysis = analyze_course_wrong_questions(
        db=db,
        student_id=student_id,
        course_id=course_id,
    )
    execution_trace.append(
        "analyze_current_course_wrong_questions"
    )

    if analysis["status"] != "success":
        return {
            "status": analysis["status"],
            "scope": {
                "course_id": course_id,
                "top_k": REVIEW_PLAN_TOP_K,
            },
            "selected_topic_count": 0,
            "weak_topics": [],
            "wrong_question_evidence": [],
            "diagnosis_groups": [],
            "execution_trace": execution_trace,
        }

    topic_analysis = analysis.get(
        "topic_analysis",
        [],
    )

    if not topic_analysis:
        raise ValueError(
            "薄弱分析状态为 success，但没有知识点分析结果"
        )

    selected_topics = _select_top_weak_topics(
        topic_analysis
    )

    question_details = get_course_wrong_question_details(
        db=db,
        student_id=student_id,
        course_id=course_id,
    )
    execution_trace.append(
        "get_current_course_wrong_questions"
    )

    selected_questions = _select_evidence_questions(
        wrong_questions=question_details.get(
            "wrong_questions",
            [],
        ),
        selected_topics=selected_topics,
    )
    evidence_items = _build_wrong_question_evidence(
        selected_questions
    )
    diagnosis_groups = _build_diagnosis_groups(
        selected_topics=selected_topics,
        evidence_items=evidence_items,
    )

    return {
        "status": "success",
        "scope": {
            "course_id": course_id,
            "top_k": REVIEW_PLAN_TOP_K,
        },
        "selected_topic_count": len(
            selected_topics
        ),
        "weak_topics": selected_topics,
        "wrong_question_evidence": evidence_items,
        "diagnosis_groups": diagnosis_groups,
        "execution_trace": execution_trace,
    }
