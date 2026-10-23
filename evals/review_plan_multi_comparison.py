"""Compare single and multi-Agent review planning on the same synthetic fixture."""

import json
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from unittest.mock import patch
from uuid import uuid4
from langchain_core.callbacks import get_usage_metadata_callback

from langgraph.checkpoint.sqlite import SqliteSaver
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import agent_runner
from app.core.database import Base
from app.harness.evaluation import EvaluationHarness
from app.services import memory_service
from evals.fixed_dataset import load_dataset, material_search, seed_fixture
from student_agent import build_student_agent


ROOT = Path(__file__).resolve().parents[1]
CASES_FILE = ROOT / "evals/fixtures/review_plan_comparison_cases_v3.json"
DATASET_FILE = ROOT / "evals/fixtures/student_agent_dataset_v3.json"


def _fixture_search(dataset, mode, *, course_id, topic, query, blocked_topics=()):
    if mode == "unavailable":
        return {"status": "course_materials_not_indexed", "course_id": course_id,
                "topic": topic, "message": "固定资料不可用用例"}
    if mode == "partial" and topic in blocked_topics:
        return {"status": "topic_materials_not_indexed", "course_id": course_id,
                "topic": topic, "message": "此知识点的固定资料不可用"}
    if mode == "no_relevant":
        return {"status": "no_relevant_content", "course_id": course_id,
                "topic": topic, "message": "没有相关片段"}
    if mode == "mcp_failure":
        raise ConnectionError("synthetic MCP failure")
    result = material_search(course_id=course_id, topic=topic, query=query, dataset=dataset)
    if result["status"] == "topic_not_found":
        return {**result, "status": "topic_materials_not_indexed"}
    if result["status"] == "success":
        result["retrieved_chunks"] = [
            {**chunk, "source_type": "teacher", "material_title": chunk["original_filename"]}
            for chunk in result["retrieved_chunks"]
        ]
    return result


def _score(case, result, error):
    if "expected_status" not in case:
        legacy = {
            "plan_from_wrong_questions": {
                "expected_status": "success", "expected_evidence_ids": ["Q_LIST_01", "Q_FUNC_01"],
                "expected_task_topics": ["Python列表", "函数返回值"],
                "forbidden_question_ids": ["Q_SECRET_01"],
            },
            "zero_wrong_plan": {"expected_status": "no_recorded_wrong_questions"},
            "material_unavailable_plan": {"expected_status": "course_materials_not_configured"},
        }
        case = {**legacy.get(case["id"], {}), **case}
    if case.get("expect_error"):
        return {"expected_error": error is not None and type(error).__name__ == case["expect_error"]}
    if error is not None:
        return {"completed": False, "error": type(error).__name__}
    plan = result.get("review_plan") or {}
    trace = result.get("tool_trace") or []
    tools = result.get("called_tools") or []
    status = plan.get("status")
    trace_text = json.dumps(trace, ensure_ascii=False, default=str)
    course_id = case.get("course_id", "C_EVAL_MAIN")
    checks = {
        "completed": bool(result.get("answer")),
        "trace_complete": tools == [item.get("tool_name") for item in trace],
        "correct_course": plan.get("scope", {}).get("course_id") in {None, course_id},
        "no_cross_course_ids": not any(
            qid in json.dumps(plan, ensure_ascii=False)
            for qid in case.get("forbidden_question_ids", [])),
    }
    expected_status = case.get("expected_status")
    if expected_status in {"success", "partial"}:
        ids = {x.get("question_id") for x in plan.get("diagnoses", [])}
        chunks = {x.get("chunk_id") for x in plan.get("material_evidence", [])}
        cited = {cid for task in plan.get("review_tasks", [])
                 for cid in task.get("material_chunk_ids", [])}
        expected_topics = set(case.get("expected_task_topics", []))
        checks.update({
            "plan_status": status == expected_status,
            "evidence_ids_valid": ids == set(case.get("expected_evidence_ids", [])),
            "tasks_grounded": {task.get("topic") for task in plan.get("review_tasks", [])}
            == expected_topics and bool(cited) and cited <= chunks,
        })
    elif expected_status == "no_recorded_wrong_questions":
        checks.update({
            "zero_wrong_confirmed": (status == "no_recorded_wrong_questions"
                                     or "no_recorded_wrong_questions" in trace_text),
            "no_invented_tasks": not plan.get("review_tasks") and not plan.get("weak_topics"),
            "checked_business_data": any(x.get("tool_name") in {
                "prepare_review_plan_foundation", "prepare_current_course_review_plan",
                "analyze_current_course_wrong_questions", "get_current_course_wrong_questions"
            } for x in trace),
        })
    else:
        checks.update({
            "no_ungrounded_tasks": not plan.get("review_tasks"),
            "material_unavailable_confirmed": (status == expected_status
                                               or any(marker in trace_text for marker in (
                                                   "course_materials_not_configured",
                                                   "course_materials_not_indexed",
                                                   "topic_materials_not_indexed",
                                                   "no_relevant_content",
                                                   "material_retrieval_failed",
                                                   "mcp_unavailable"))),
            "retrieval_attempted": any(x.get("tool_name") in {
                "mcp_search_course_material", "validate_current_course_diagnoses"
            } for x in trace),
        })
    return checks


def _failure_diagnostic(result, error, checks):
    """Persist only IDs/statuses, never answer text or retrieved material content."""
    if error is not None:
        return {"stage": "agent_invocation", "error_type": type(error).__name__,
                "rule": "调用异常，未取得可校验的候选输出", "candidate_fields": None}
    if result and result.get("failure_diagnostic"):
        return result["failure_diagnostic"]
    failed = [name for name, passed in checks.items() if passed is False]
    if not failed:
        return None
    plan = (result or {}).get("review_plan") or {}
    return {"stage": "evaluation_checks", "error_type": None,
            "rule": failed,
            "candidate_fields": {
                "status": plan.get("status"),
                "weak_topics": [x.get("topic") for x in plan.get("weak_topics", [])],
                "diagnosis_question_ids": [x.get("question_id") for x in plan.get("diagnoses", [])],
                "material_chunk_ids": [x.get("chunk_id") for x in plan.get("material_evidence", [])],
                "task_topics": [x.get("topic") for x in plan.get("review_tasks", [])],
                "task_chunk_ids": [x.get("material_chunk_ids") for x in plan.get("review_tasks", [])],
            }}


def validate_cases(cases, dataset):
    minimum = 60 if dataset["dataset_id"] == "student-agent-synthetic-v3" else 30
    if len(cases) < minimum:
        raise ValueError(f"复习计划对照集至少需要{minimum}个用例")
    ids = [case["id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("评测用例 ID 重复")
    students = {x["id"] for x in dataset["students"]}
    courses = {x["id"] for x in dataset["courses"]}
    enrollments = {(x["student_id"], x["course_id"]) for x in dataset["enrollments"]}
    for case in cases:
        course_id = case.get("course_id", "C_EVAL_MAIN")
        if (case["student_id"] not in students or course_id not in courses
                or not case["question"].strip() or
                case["material_mode"] not in {"success", "unavailable", "partial",
                                             "no_relevant", "mcp_failure"}):
            raise ValueError(f"评测用例格式无效：{case['id']}")
        if not case.get("expect_error") and (case["student_id"], course_id) not in enrollments:
            raise ValueError(f"评测学生未选当前课程：{case['id']}")
        if case["material_mode"] == "partial" and not case.get("blocked_topics"):
            raise ValueError(f"部分资料场景没有指定缺失知识点：{case['id']}")
        if not case.get("expect_error") and not all(
            isinstance(case.get(key), list)
            for key in ("expected_topics", "expected_evidence_ids", "expected_task_topics")
        ):
            raise ValueError(f"评测用例缺少冻结的知识点和错题预期：{case['id']}")
    return {"case_count": len(cases), "categories": sorted({c["category"] for c in cases})}


def run_comparison(output_dir=ROOT / "eval_results", *,
                   cases_file=CASES_FILE, dataset_file=DATASET_FILE,
                   case_ids=None, architectures=("single", "multi")):
    dataset, dataset_sha256 = load_dataset(dataset_file)
    cases = json.loads(Path(cases_file).read_text(encoding="utf-8"))
    validate_cases(cases, dataset)
    if case_ids is not None:
        unknown = set(case_ids) - {case["id"] for case in cases}
        if unknown:
            raise ValueError(f"未知评测用例：{sorted(unknown)}")
    selected_cases = [case for case in cases if case_ids is None or case["id"] in case_ids]
    if not selected_cases or not set(architectures) <= {"single", "multi"}:
        raise ValueError("需要至少一个用例和一个有效架构")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    rows = []
    provider_blocker = None
    result_files = {
        architecture: output_dir / f"review_plan_comparison_{run_id}_{architecture}.jsonl"
        for architecture in ("single", "multi")
    }
    for architecture in architectures:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            engine = create_engine(f"sqlite:///{(tmp_path / 'education.db').as_posix()}",
                                   connect_args={"check_same_thread": False})
            Base.metadata.create_all(engine)
            sessions = sessionmaker(bind=engine)
            seed_fixture(sessions, cases, dataset)
            from app.services.review_plan_service import prepare_review_plan_foundation
            with sessions() as oracle_db:
                all_question_ids = {q["id"] for q in dataset["questions"]}
                by_course = {course["id"]: {q["id"] for q in dataset["questions"]
                                                  if q["course_id"] == course["id"]}
                             for course in dataset["courses"]}
                for case in cases:
                    if case.get("expect_error"):
                        continue
                    cid = case.get("course_id", "C_EVAL_MAIN")
                    base = prepare_review_plan_foundation(oracle_db, case["student_id"], cid)
                    if ([x["topic"] for x in base["weak_topics"]] != case["expected_topics"]
                            or [x["question_id"] for x in base["wrong_question_evidence"]]
                            != case["expected_evidence_ids"]):
                        raise ValueError(f"冻结的评测预期与业务数据不一致：{case['id']}")
                    case["forbidden_question_ids"] = sorted(all_question_ids - by_course[cid])
            checkpoint_connection = sqlite3.connect(str(tmp_path / "checkpoint.db"),
                                                    check_same_thread=False)
            saver = SqliteSaver(checkpoint_connection)
            saver.setup()
            agent = build_student_agent(checkpointer=saver)
            original_multi = agent_runner.run_multi_agent_review
            try:
                with patch.object(agent_runner, "SessionLocal", sessions), \
                     patch.object(agent_runner, "student_agent", agent), \
                     patch.object(memory_service, "get_short_term_messages", return_value=[]), \
                     patch.object(memory_service, "add_short_term_message"):
                    for case in selected_cases:
                        mode = case["material_mode"]
                        search = lambda **kwargs: _fixture_search(
                            dataset, mode, blocked_topics=case.get("blocked_topics", ()), **kwargs)
                        def run_multi(**kwargs):
                            # Pass the exact same fixed materials through the MCP boundary adapter.
                            from app.workflows import student_multi_agent as workflow
                            with patch.object(workflow, "search_material", search):
                                # Default arguments are bound when defined; inject at the graph call.
                                original_build = workflow.build_student_review_graph
                                def build(**build_kwargs):
                                    build_kwargs["material_search"] = search
                                    return original_build(**build_kwargs)
                                with patch.object(workflow, "build_student_review_graph", build):
                                    return original_multi(**kwargs)
                        with patch("student_agent.search_course_material", side_effect=search), \
                             patch("app.services.review_plan_service.search_indexed_course_materials",
                                   side_effect=lambda *, course_id, topic, query, top_k: search(
                                       course_id=course_id, topic=topic, query=query)), \
                             patch.object(agent_runner, "run_multi_agent_review", side_effect=run_multi):
                            outcome = EvaluationHarness(
                                score=_score, diagnose=_failure_diagnostic,
                                usage_context=get_usage_metadata_callback,
                            ).run_case(case, lambda: agent_runner.run_agent_with_memory(
                                        user_id=case["student_id"],
                                        session_id=f"SESSION_EVAL_{case['id']}",
                                        user_input=case["question"],
                                        workflow="multi_agent_review" if architecture == "multi" else "single",
                                        capture_failure_diagnostics=architecture == "multi",
                                    ))
                            result, error, checks = outcome.result, outcome.error, outcome.checks
                            rows.append({
                                "architecture": architecture, "case_id": case["id"],
                                "question": case["question"],
                                "answer": result.get("answer") if result else None,
                                "review_plan": result.get("review_plan") if result else None,
                                "called_tools": result.get("called_tools", []) if result else [],
                                "tool_trace": result.get("tool_trace", []) if result else [],
                                "failure_diagnostic": outcome.failure_diagnostic,
                                "checks": checks,
                                "auto_pass": outcome.passed,
                                "structured_status_reported": bool(
                                    (result or {}).get("review_plan", {}).get("status")
                                ) if result and isinstance(result.get("review_plan"), dict) else False,
                                "error_type": type(error).__name__ if error else None,
                                "error_message": str(error)[:300] if error else None,
                                "elapsed_s": outcome.elapsed_s,
                                "token_usage": outcome.token_usage,
                                "manual_review": "pending",
                            })
                            with result_files[architecture].open("a", encoding="utf-8") as output:
                                output.write(json.dumps(rows[-1], ensure_ascii=False, default=str) + "\n")
                            print(json.dumps({
                                "architecture": architecture,
                                "case": len([row for row in rows if row["architecture"] == architecture]),
                                "of": len(selected_cases), "case_id": case["id"],
                                "passed": rows[-1]["auto_pass"],
                                "status": (result or {}).get("review_plan", {}).get("status")
                                if result and isinstance(result.get("review_plan"), dict) else None,
                                "elapsed_s": rows[-1]["elapsed_s"],
                                "error_type": rows[-1]["error_type"],
                            }, ensure_ascii=False), flush=True)
                            if (error is not None and type(error).__name__ == "APIStatusError"
                                    and "Error code: 402" in str(error)):
                                provider_blocker = {"provider": "DeepSeek", "http_status": 402,
                                                    "message": "Insufficient Balance",
                                                    "first_affected_case": case["id"]}
                                break
            finally:
                checkpoint_connection.close()
                engine.dispose()
        if provider_blocker:
            break
    summary = {"run_id": run_id, "dataset_id": dataset["dataset_id"],
               "dataset_sha256": dataset_sha256,
               "cases_file": str(cases_file), "case_count": len(selected_cases),
               "selected_case_ids": [case["id"] for case in selected_cases],
               "models": "deepseek-chat",
               "architectures": {},
               "run_valid_for_architecture_comparison": (
                   provider_blocker is None and case_ids is None
                   and set(architectures) == {"single", "multi"}
               ),
               "targeted_diagnostic_run": case_ids is not None or set(architectures) != {"single", "multi"},
               "external_blocker": provider_blocker}
    for architecture in ("single", "multi"):
        selected = [row for row in rows if row["architecture"] == architecture]
        if not selected:
            summary["architectures"][architecture] = {"passed": 0, "total": 0,
                                                      "pass_rate": None, "case_results": []}
            continue
        times = [row["elapsed_s"] for row in selected]
        measured = [row["token_usage"] for row in selected if row.get("token_usage")]
        ranked_times = sorted(times)
        p95_index = max(0, (len(ranked_times) * 95 + 99) // 100 - 1)
        summary["architectures"][architecture] = {
            "passed": sum(row["auto_pass"] for row in selected),
            "total": len(selected),
            "pass_rate": round(mean(row["auto_pass"] for row in selected), 3),
            "structured_status_reported": sum(row["structured_status_reported"] for row in selected),
            "trace_events": sum(len(row["called_tools"]) for row in selected),
            "mean_trace_events": round(mean(len(row["called_tools"]) for row in selected), 2),
            "mean_latency_s": round(mean(times), 3),
            "median_latency_s": round(median(times), 3),
            "p95_latency_s": ranked_times[p95_index],
            "token_measurement_coverage": len(measured),
            "total_input_tokens": sum(item["input_tokens"] for item in measured),
            "total_output_tokens": sum(item["output_tokens"] for item in measured),
            "case_results": [{"case_id": row["case_id"], "passed": row["auto_pass"],
                              "checks": row["checks"], "elapsed_s": row["elapsed_s"],
                              "error_type": row["error_type"]} for row in selected],
        }
    summary_path = output_dir / f"review_plan_comparison_{run_id}.summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def rescore_run(run_id, output_dir=ROOT / "eval_results"):
    """Regrade saved model outputs without making another external model call."""
    output_dir = Path(output_dir)
    summary = json.loads((output_dir / f"review_plan_comparison_{run_id}.summary.json")
                         .read_text(encoding="utf-8"))
    cases_file = Path(summary["cases_file"])
    cases = {case["id"]: case for case in json.loads(cases_file.read_text(encoding="utf-8"))}
    for architecture in ("single", "multi"):
        rows_path = output_dir / f"review_plan_comparison_{run_id}_{architecture}.jsonl"
        rows = [json.loads(line) for line in rows_path.read_text(encoding="utf-8").splitlines()]
        for row in rows:
            checks = _score(cases[row["case_id"]], row, None if row["error_type"] is None
                            else RuntimeError(row["error_type"]))
            row["checks"] = checks
            row["auto_pass"] = bool(checks) and all(v is True for v in checks.values())
            row["structured_status_reported"] = isinstance(row.get("review_plan"), dict) and bool(
                row["review_plan"].get("status"))
        output = output_dir / f"review_plan_comparison_{run_id}_{architecture}.rescored.jsonl"
        output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                          encoding="utf-8")
        times = [row["elapsed_s"] for row in rows]
        summary["architectures"][architecture] = {
            "passed": sum(row["auto_pass"] for row in rows), "total": len(rows),
            "pass_rate": round(mean(row["auto_pass"] for row in rows), 3),
            "structured_status_reported": sum(row["structured_status_reported"] for row in rows),
            "trace_events": sum(len(row["called_tools"]) for row in rows),
            "mean_trace_events": round(mean(len(row["called_tools"]) for row in rows), 2),
            "mean_latency_s": round(mean(times), 3), "median_latency_s": round(median(times), 3),
            "case_results": [{"case_id": row["case_id"], "passed": row["auto_pass"],
                              "checks": row["checks"], "elapsed_s": row["elapsed_s"],
                              "error_type": row["error_type"]} for row in rows],
        }
    summary["scoring_version"] = "behavior-v2"
    summary["scoring_note"] = ("单 Agent 的零错题/无资料可由已核查工具结果和回答表达；"
                               "结构化状态报告单列，内部图节点与 LangChain 工具次数不直接比较")
    output = output_dir / f"review_plan_comparison_{run_id}.rescored.summary.json"
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--rescore", metavar="RUN_ID")
    parser.add_argument("--cases", type=Path, default=CASES_FILE)
    parser.add_argument("--dataset", type=Path, default=DATASET_FILE)
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--case-ids", nargs="+", help="只运行指定 ID；仍校验完整固定评测集")
    parser.add_argument("--architecture", choices=("single", "multi"), action="append")
    args = parser.parse_args()
    if args.validate:
        fixed, sha = load_dataset(args.dataset)
        items = json.loads(args.cases.read_text(encoding="utf-8"))
        result = {**validate_cases(items, fixed), "dataset_id": fixed["dataset_id"],
                  "dataset_sha256": sha}
    elif args.rescore:
        result = rescore_run(args.rescore)
    else:
        result = run_comparison(cases_file=args.cases, dataset_file=args.dataset,
                                case_ids=args.case_ids,
                                architectures=tuple(args.architecture or ("single", "multi")))
    print(json.dumps(result,
                     ensure_ascii=False, indent=2))
