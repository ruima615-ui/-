"""A bounded LangGraph collaboration for a course-scoped review plan.

The coordinator owns identity, database access and routing. The two model
workers receive only the selected evidence or the validated handoff.
"""

import json
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field, ValidationError

from app.mcp.material_client import search_material
from app.schemas.review_plan import ReviewPlanResponse, ReviewTask, WrongQuestionDiagnosis
from app.services.diagnosis_handoff_service import (
    load_validated_diagnoses,
    save_validated_diagnoses,
)
from app.services.review_plan_service import (
    MATERIAL_CHUNKS_PER_TOPIC,
    _build_topic_material_query,
    _convert_material_evidence,
    associate_diagnoses_with_weak_topics,
    prepare_review_plan_foundation,
    validate_review_tasks,
)


class DiagnosisHandoff(BaseModel):
    priority_topics: list[str] = Field(min_length=1, max_length=2)
    evidence_question_ids: list[str] = Field(min_length=1, max_length=4)
    reason: str = Field(min_length=1)
    diagnoses: list[WrongQuestionDiagnosis] = Field(min_length=1, max_length=4)


class PlanDraft(BaseModel):
    review_tasks: list[ReviewTask] = Field(default_factory=list, max_length=2)


class ReviewState(TypedDict, total=False):
    foundation: dict
    handoff: dict
    grounded: dict
    plan: dict
    status: str
    tool_trace: list[dict]
    failure_diagnostic: dict


def _trace(name: str, status: str, *, detail: str = "") -> dict:
    return {"tool_name": name, "status": status, "detail": detail}


def _candidate_fields(candidate: object, stage: str) -> dict | None:
    """Only retain identifiers needed to reproduce a rejected validation."""
    if candidate is None:
        return None
    data = candidate.model_dump() if isinstance(candidate, BaseModel) else candidate
    if not isinstance(data, dict):
        return {"output_type": type(data).__name__}

    def strings(value):
        return [item[:100] for item in value[:4] if isinstance(item, str)] if isinstance(value, list) else []

    if stage == "diagnosis":
        diagnoses = data.get("diagnoses")
        return {
            "priority_topics": strings(data.get("priority_topics")),
            "evidence_question_ids": strings(data.get("evidence_question_ids")),
            "diagnosis_count": len(diagnoses) if isinstance(diagnoses, list) else None,
            "diagnoses": [
                {key: item.get(key)[:100] if isinstance(item.get(key), str) else None
                 for key in ("question_id", "topic", "error_type")}
                for item in diagnoses[:4] if isinstance(item, dict)
            ] if isinstance(diagnoses, list) else [],
        }
    tasks = data.get("review_tasks")
    return {
        "task_count": len(tasks) if isinstance(tasks, list) else None,
        "review_tasks": [
            {"task_id": item.get("task_id")[:100] if isinstance(item.get("task_id"), str) else None,
             "topic": item.get("topic")[:100] if isinstance(item.get("topic"), str) else None,
             "priority_rank": item.get("priority_rank"),
             "related_error_types": strings(item.get("related_error_types")),
             "material_chunk_ids": strings(item.get("material_chunk_ids"))}
            for item in tasks[:2] if isinstance(item, dict)
        ] if isinstance(tasks, list) else [],
    }


def _failure(stage: str, exc: Exception, candidate: object) -> dict:
    if isinstance(exc, ValidationError):
        rule = [
            {"field": ".".join(map(str, error["loc"])), "type": error["type"],
             "message": error["msg"][:200]}
            for error in exc.errors(include_input=False, include_context=False, include_url=False)[:8]
        ]
    elif stage in {"evidence_validation", "task_validation"} and isinstance(exc, ValueError):
        # These messages are produced by our own validators, not a provider response.
        rule = str(exc)[:300]
    else:
        rule = "模型调用或输出解析失败；未取得可校验的规则消息"
    return {"stage": stage, "error_type": type(exc).__name__,
            "rule": rule, "candidate_fields": candidate}


def build_student_review_graph(*, diagnosis_model, plan_model, material_search=search_material,
                               capture_failure_diagnostics=False):
    """Construct a graph; injected models/search make offline evaluation possible."""
    diagnosis_worker = diagnosis_model.with_structured_output(DiagnosisHandoff)
    plan_worker = plan_model.with_structured_output(PlanDraft)

    def coordinator_load(state: ReviewState, config) -> dict:
        scope = config["configurable"]
        try:
            foundation = prepare_review_plan_foundation(
                scope["db"], scope["student_id"], scope["course_id"]
            )
        except Exception as exc:
            return {
                "foundation": {"scope": {"course_id": scope["course_id"], "top_k": 2},
                               "weak_topics": [], "wrong_question_evidence": []},
                "status": "foundation_failed",
                "tool_trace": [_trace("prepare_review_plan_foundation", "error",
                                      detail=type(exc).__name__)],
            }
        loaded = {
            "foundation": foundation,
            "status": foundation["status"],
            "tool_trace": [_trace("prepare_review_plan_foundation", foundation["status"])],
        }
        session_id = scope.get("session_id")
        if foundation["status"] == "success" and session_id:
            cached = load_validated_diagnoses(
                scope["db"], user_id=scope["student_id"],
                course_id=scope["course_id"], session_id=session_id,
                foundation=foundation,
            )
            loaded["tool_trace"].append(_trace("load_validated_diagnoses", cached["status"]))
            if cached["status"] == "reused":
                loaded["handoff"] = {
                    "priority_topics": [x["topic"] for x in foundation["weak_topics"]],
                    "evidence_question_ids": [x["question_id"] for x in foundation["wrong_question_evidence"]],
                    "reason": "复用本会话已校验且未过期的诊断",
                    "diagnoses": cached["diagnoses"],
                }
        return loaded

    def after_load(state: ReviewState) -> str:
        if state["status"] != "success":
            return "finish"
        return "retrieve" if "handoff" in state else "diagnose"

    def diagnose(state: ReviewState, config) -> dict:
        foundation = state["foundation"]
        payload = {
            "priority_topics": [x["topic"] for x in foundation["weak_topics"]],
            "wrong_question_evidence": foundation["wrong_question_evidence"],
        }
        candidate, stage, retries = None, "model_output", 0
        try:
            messages = [
                ("system", "你是错题诊断 Agent。只依据给定证据，输出固定结构。"
                 "不能查询学生身份、重算薄弱点或编造题目。证据不足时用 insufficient_evidence。"),
                ("human", json.dumps(payload, ensure_ascii=False)),
            ]
            for attempt in range(2):
                candidate, stage = None, "model_output"
                try:
                    candidate = diagnosis_worker.invoke(messages)
                    stage = "schema_validation"
                    candidate = DiagnosisHandoff.model_validate(candidate)
                    stage = "evidence_validation"
                    expected_topics = payload["priority_topics"]
                    expected_ids = [x["question_id"] for x in foundation["wrong_question_evidence"]]
                    if candidate.priority_topics != expected_topics or candidate.evidence_question_ids != expected_ids:
                        raise ValueError("诊断 Agent 更改了后端选定的知识点或题目")
                    diagnoses = associate_diagnoses_with_weak_topics(
                        weak_topics=foundation["weak_topics"],
                        wrong_question_evidence=foundation["wrong_question_evidence"],
                        diagnoses=[x.model_dump() for x in candidate.diagnoses],
                    )
                    break
                except (ValidationError, ValueError) as exc:
                    if attempt or stage == "model_output":
                        raise
                    retries = 1
                    messages.append(("human", "前次结构或证据校验失败。请重新输出完整结构；"
                                     f"知识点必须为 {expected_topics if stage == 'evidence_validation' else payload['priority_topics']}，"
                                     f"题目 ID 必须为 {[x['question_id'] for x in foundation['wrong_question_evidence']]}。"
                                     "每道题恰好一条诊断，不得新增题目。"))
            handoff = {**candidate.model_dump(), "diagnoses": diagnoses}
            scope = config["configurable"]
            if scope.get("session_id"):
                stage = "snapshot_save"
                save_validated_diagnoses(
                    scope["db"], user_id=scope["student_id"],
                    course_id=scope["course_id"], session_id=scope["session_id"],
                    foundation=foundation, diagnoses=diagnoses,
                )
            return {"handoff": handoff, "tool_trace": [
                *state["tool_trace"], _trace("diagnosis_agent", "success", detail=f"retries={retries}")
            ]}
        except Exception as exc:
            failed = {"status": "diagnosis_failed", "tool_trace": [
                *state["tool_trace"], _trace("diagnosis_agent", "error", detail=type(exc).__name__)
            ]}
            if capture_failure_diagnostics:
                failed["failure_diagnostic"] = _failure(stage, exc, _candidate_fields(candidate, "diagnosis"))
            return failed

    def after_diagnose(state: ReviewState) -> str:
        return "retrieve" if state["status"] == "success" else "finish"

    def retrieve(state: ReviewState, config) -> dict:
        foundation, handoff = state["foundation"], state["handoff"]
        course_id = config["configurable"]["course_id"]
        groups, evidence, limitations = [], [], []
        trace = list(state["tool_trace"])
        for weak in foundation["weak_topics"]:
            topic = weak["topic"]
            query = _build_topic_material_query(topic=topic, diagnoses=handoff["diagnoses"])
            try:
                result = material_search(course_id=course_id, topic=topic, query=query)
                if not isinstance(result, dict) or not isinstance(result.get("status"), str):
                    raise ValueError("无效的 MCP 检索结果")
                chunks = (_convert_material_evidence(expected_topic=topic, search_result=result)
                          [:MATERIAL_CHUNKS_PER_TOPIC] if result["status"] == "success" else [])
                # The MCP result must belong to the authorized course, even if the
                # transport/server is replaced or misconfigured.
                if (result.get("course_id") != course_id
                        or (result["status"] == "success" and
                            (result.get("topic") != topic or not chunks))):
                    raise ValueError("MCP 课程范围或资料证据无效")
                status = result["status"]
            except Exception as exc:
                status, chunks = "material_retrieval_failed", []
                trace.append(_trace("mcp_search_course_material", "error", detail=type(exc).__name__))
            else:
                trace.append(_trace("mcp_search_course_material", status, detail=topic))
            groups.append({"topic": topic, "priority_rank": weak["priority_rank"],
                           "status": status, "query": query, "evidence": chunks})
            evidence.extend(chunks)
            if status != "success":
                limitations.append(f"知识点“{topic}”暂无可用课程资料（{status}）")
        ready = sum(group["status"] == "success" for group in groups)
        if ready == len(groups):
            status = "success"
        elif ready:
            status = "partial"
        elif all(group["status"] in {"course_materials_not_indexed", "topic_materials_not_indexed"}
                 for group in groups):
            status = "course_materials_not_configured"
        elif any(group["status"] == "no_relevant_content" for group in groups) and all(
                group["status"] in {"no_relevant_content", "course_materials_not_indexed",
                                    "topic_materials_not_indexed"} for group in groups):
            status = "course_materials_insufficient"
        else:
            status = "material_retrieval_failed"
        return {
            "status": status, "tool_trace": trace,
            "grounded": {**foundation, "status": status, "diagnoses": handoff["diagnoses"],
                         "material_groups": groups, "material_evidence": evidence,
                         "limitations": limitations},
        }

    def after_retrieve(state: ReviewState) -> str:
        return "plan" if state["status"] in {"success", "partial"} else "finish"

    def plan(state: ReviewState) -> dict:
        grounded = state["grounded"]
        eligible_groups = [
            {"topic": group["topic"], "priority_rank": group["priority_rank"],
             "allowed_chunk_ids": [item["chunk_id"] for item in group["evidence"]]}
            for group in grounded["material_groups"] if group["status"] == "success"
        ]
        payload = {"diagnosis_handoff": state["handoff"],
                   "weak_topics": grounded["weak_topics"],
                   "material_groups": grounded["material_groups"],
                   "required_task_count": len(eligible_groups),
                   "eligible_groups": eligible_groups}
        candidate, stage, retries = None, "model_output", 0
        try:
            messages = [
                ("system", "你是复习计划 Agent。只使用已校验的诊断交接和 MCP 资料片段。"
                 "只按 eligible_groups 生成任务：review_tasks 的数量必须严格等于 "
                 "required_task_count；每个 eligible_groups 条目恰好一项任务。"
                 "一个知识点即使有多道错题或多条规则，也只能生成一项综合任务。"
                 "topic、priority_rank 必须照抄对应条目，material_chunk_ids 只能从该条目的 "
                 "allowed_chunk_ids 中选。不要查询身份、重算错题或编造资料 ID。"),
                ("human", json.dumps(payload, ensure_ascii=False)),
            ]
            for attempt in range(2):
                candidate, stage = None, "model_output"
                try:
                    candidate = plan_worker.invoke(messages)
                    stage = "schema_validation"
                    candidate = PlanDraft.model_validate(candidate)
                    stage = "task_validation"
                    tasks = validate_review_tasks(
                        grounded_plan=grounded,
                        review_tasks=[x.model_dump() for x in candidate.review_tasks],
                    )
                    break
                except (ValidationError, ValueError):
                    if attempt or stage == "model_output":
                        raise
                    retries = 1
                    messages.append(("human", "前次任务未通过结构或引用校验。请重新生成，"
                                     f"严格生成 {len(eligible_groups)} 项任务；"
                                     "每个 eligible_groups 知识点恰好一项，照抄优先级，"
                                     "资料 ID 仅从对应 allowed_chunk_ids 中选择。"))
            return {"plan": {"review_tasks": tasks}, "tool_trace": [
                *state["tool_trace"], _trace("plan_agent", "success", detail=f"retries={retries}")
            ]}
        except Exception as exc:
            failed = {"status": "plan_failed", "tool_trace": [
                *state["tool_trace"], _trace("plan_agent", "error", detail=type(exc).__name__)
            ]}
            if capture_failure_diagnostics:
                failed["failure_diagnostic"] = _failure(stage, exc, _candidate_fields(candidate, "plan"))
            return failed

    def finish(state: ReviewState) -> dict:
        foundation = state["foundation"]
        grounded = state.get("grounded", {})
        status = state["status"]
        limitations = list(grounded.get("limitations", []))
        if status == "foundation_failed":
            limitations.append("错题基础数据暂时不可用，未生成复习计划")
        elif status == "diagnosis_failed":
            limitations.append("错题诊断未通过校验，暂时无法生成复习任务")
        elif status == "plan_failed":
            limitations.append("复习任务生成或校验失败，暂时无法提供完整计划")
        result = ReviewPlanResponse(
            status=status if status in {"success", "partial", "no_recorded_wrong_questions",
                                 "course_materials_not_configured", "course_materials_insufficient",
                                 "material_retrieval_failed", "insufficient_evidence",
                                 "foundation_failed", "diagnosis_failed", "plan_failed"}
            else "insufficient_evidence",
            scope=foundation["scope"], weak_topics=foundation["weak_topics"],
            wrong_question_evidence=foundation["wrong_question_evidence"],
            diagnoses=grounded.get("diagnoses", []),
            material_evidence=grounded.get("material_evidence", []),
            review_tasks=state.get("plan", {}).get("review_tasks", []),
            limitations=limitations,
        ).model_dump()
        return {"plan": result, "tool_trace": [
            *state["tool_trace"], _trace("coordinator_finish", result["status"])
        ]}

    graph = StateGraph(ReviewState)
    graph.add_node("coordinator_load", coordinator_load)
    graph.add_node("diagnose", diagnose)
    graph.add_node("retrieve", retrieve)
    graph.add_node("plan", plan)
    graph.add_node("finish", finish)
    graph.add_edge(START, "coordinator_load")
    graph.add_conditional_edges("coordinator_load", after_load)
    graph.add_conditional_edges("diagnose", after_diagnose)
    graph.add_conditional_edges("retrieve", after_retrieve)
    graph.add_edge("plan", "finish")
    graph.add_edge("finish", END)
    return graph.compile()


def run_student_multi_agent_review(*, db, student_id: str, course_id: str,
                                   diagnosis_model, plan_model, session_id: str | None = None,
                                   material_search=search_material,
                                   capture_failure_diagnostics=False) -> dict:
    """Run one authorized review request; scope never enters model-generated state."""
    graph = build_student_review_graph(
        diagnosis_model=diagnosis_model, plan_model=plan_model,
        material_search=material_search,
        capture_failure_diagnostics=capture_failure_diagnostics,
    )
    state = graph.invoke({}, config={"configurable": {
        "db": db, "student_id": student_id, "course_id": course_id,
        "session_id": session_id,
    }})
    return {"review_plan": state["plan"], "diagnosis_handoff": state.get("handoff"),
            "tool_trace": state["tool_trace"],
            "failure_diagnostic": state.get("failure_diagnostic") if capture_failure_diagnostics else None}
