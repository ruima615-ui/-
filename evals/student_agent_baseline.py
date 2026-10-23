"""固定案例评测真实学生 Agent，保存回答、工具轨迹和可复核的规则判定。"""

import argparse
import json
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from unittest.mock import patch
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import agent_runner
from app.core.database import Base
from app.services import memory_service
from evals.fixed_dataset import load_dataset, material_chunk, material_search, seed_fixture
from student_agent import build_student_agent


PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CASES = PROJECT_DIR / "evals" / "student_agent_baseline_cases.json"
DEFAULT_OUTPUT = PROJECT_DIR / "eval_results"


def load_cases(path=DEFAULT_CASES):
    cases = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("评测案例必须是非空列表")
    ids = [case.get("id") for case in cases]
    if any(not isinstance(case_id, str) or not case_id for case_id in ids):
        raise ValueError("每个案例都必须有非空 id")
    if len(ids) != len(set(ids)):
        raise ValueError("案例 id 不能重复")
    for case in cases:
        if not isinstance(case.get("turns"), list) or not case["turns"]:
            raise ValueError(f"案例 {case['id']} 缺少提问轮次")
        for turn in case["turns"]:
            if not isinstance(turn.get("question"), str) or not turn["question"].strip():
                raise ValueError(f"案例 {case['id']} 存在空问题")
    return cases


def grade_turn(case, turn, result=None, error=None):
    """只核对可客观复查的事实和工具轨迹，不宣称替代人工语义评分。"""
    checks = {}
    expected_error = case.get("expect_error")
    if expected_error:
        checks["expected_error"] = type(error).__name__ == expected_error
        return checks
    if error is not None:
        return {"completed": False, "exception": type(error).__name__}
    if not isinstance(result, dict):
        return {"completed": False}

    answer = str(result.get("answer") or "")
    tools = result.get("called_tools") or []
    trace = result.get("tool_trace") or []
    checks["nonempty_answer"] = bool(answer.strip())
    checks["tool_trace_complete"] = Counter(tools) == Counter(
        item.get("tool_name") for item in trace
    )
    checks["required_tools"] = set(turn.get("required_tools", [])) <= set(tools)
    any_tools = turn.get("any_required_tools", [])
    if any_tools:
        checks["any_required_tools"] = bool(set(any_tools) & set(tools))
    checks["forbidden_tools"] = not set(turn.get("forbidden_tools", [])) & set(tools)
    ordered = turn.get("ordered_tools", [])
    if ordered:
        positions = [next((index for index, tool in enumerate(tools) if tool == expected), -1)
                     for expected in ordered]
        checks["tool_order"] = -1 not in positions and positions == sorted(positions)
    checks["required_facts"] = all(text in answer for text in turn.get("answer_contains", []))
    checks["forbidden_facts"] = not any(
        text in answer for text in turn.get("answer_excludes", [])
    )
    any_facts = turn.get("answer_any", [])
    if any_facts:
        checks["fallback_wording"] = any(text in answer for text in any_facts)
    trace_text = json.dumps(trace, ensure_ascii=False, default=str)
    checks["trace_status"] = all(text in trace_text for text in turn.get("trace_contains", []))
    return checks


def run_baseline(cases, output_dir=DEFAULT_OUTPUT):
    import sqlite3

    dataset, dataset_sha256 = load_dataset()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    results_path = output_dir / f"student_agent_baseline_{run_id}.jsonl"
    summary_path = output_dir / f"student_agent_baseline_{run_id}.summary.json"
    rows = []
    with tempfile.TemporaryDirectory() as temp_dir:
        engine = create_engine(f"sqlite:///{(Path(temp_dir) / 'education.db').as_posix()}",
                               connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine)
        seed_fixture(session_factory, cases, dataset)
        checkpoint_connection = sqlite3.connect(
            str(Path(temp_dir) / "agent_checkpoints.db"), check_same_thread=False)
        saver = SqliteSaver(checkpoint_connection)
        saver.setup()
        agent = build_student_agent(checkpointer=saver)
        try:
            with patch.object(agent_runner, "SessionLocal", session_factory), \
                 patch.object(agent_runner, "student_agent", agent), \
                 patch.object(memory_service, "get_short_term_messages", return_value=[]), \
                 patch.object(memory_service, "add_short_term_message"):
                for case in cases:
                    mode = case.get("material_mode", "success")
                    with patch("student_agent.search_course_material",
                               side_effect=lambda *, course_id, topic, query: material_search(
                                   course_id=course_id, topic=topic, query=query, mode=mode,
                                   dataset=dataset,
                               )), \
                         patch("student_agent.load_course_material_chunk",
                               side_effect=lambda *, course_id, chunk_id, topic=None: material_chunk(
                                   course_id=course_id, chunk_id=chunk_id, topic=topic,
                                   dataset=dataset)):
                        for turn_index, turn in enumerate(case["turns"], 1):
                            started = perf_counter()
                            result = None
                            error = None
                            try:
                                result = agent_runner.run_agent_with_memory(
                                    user_id=case["student_id"],
                                    session_id=f"SESSION_EVAL_{case['id']}",
                                    user_input=turn["question"],
                                )
                            except Exception as exc:
                                error = exc
                            checks = grade_turn(case, turn, result, error)
                            row = {
                                "case_id": case["id"], "category": case["category"],
                                "turn": turn_index, "question": turn["question"],
                                "expected": {key: value for key, value in turn.items()
                                             if key != "question"},
                                "answer": result.get("answer") if result else None,
                                "called_tools": result.get("called_tools", []) if result else [],
                                "tool_trace": result.get("tool_trace", []) if result else [],
                                "error_type": type(error).__name__ if error else None,
                                "error_message": str(error)[:300] if error else None,
                                "checks": checks, "auto_pass": bool(checks) and all(
                                    value is True for value in checks.values()),
                                "elapsed_s": round(perf_counter() - started, 3),
                                "manual_review": "pending",
                            }
                            rows.append(row)
                            with results_path.open("a", encoding="utf-8") as output:
                                output.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        finally:
            checkpoint_connection.close()
            engine.dispose()

    by_category = defaultdict(lambda: {"passed": 0, "total": 0})
    for row in rows:
        by_category[row["category"]]["total"] += 1
        by_category[row["category"]]["passed"] += int(row["auto_pass"])
    summary = {
        "run_id": run_id, "model": "deepseek-chat", "fixture": "isolated_sqlite_synthetic_business",
        "dataset_id": dataset["dataset_id"], "dataset_sha256": dataset_sha256,
        "case_count": len(cases), "turn_count": len(rows),
        "auto_passed_turns": sum(row["auto_pass"] for row in rows),
        "auto_pass_rate": round(sum(row["auto_pass"] for row in rows) / len(rows), 3),
        "categories": dict(by_category),
        "results_file": str(results_path),
        "scoring_note": "规则判定只检查工具、轨迹和显式事实；语义质量仍需人工复核",
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description="学生助手单 Agent 基线评测")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--validate-cases", action="store_true")
    args = parser.parse_args()
    cases = load_cases(args.cases)
    if args.validate_cases:
        dataset, sha256 = load_dataset()
        print(json.dumps({"case_count": len(cases), "turn_count": sum(len(c["turns"]) for c in cases),
                          "dataset_id": dataset["dataset_id"], "dataset_sha256": sha256},
                         ensure_ascii=True))
        return
    print(json.dumps(run_baseline(cases, args.output_dir), ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
