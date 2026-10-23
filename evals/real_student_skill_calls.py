"""Four real DeepSeek student-Agent questions with per-turn tool traces.

Evaluation conversations and checkpoints use a snapshot of the current
business SQLite database. Existing exam answers are never modified.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from unittest.mock import patch
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import agent_runner
from app.core.config import DATABASE_FILE
from app.models.entities import ChatSession
from app.services import memory_service
from app.services.material_search_service import search_course_materials_with_fallback
from student_agent import build_student_agent


ROOT = Path(__file__).resolve().parents[1]
CASES = (
    ("weak_topics", "S008", "分析我这门课的薄弱知识点"),
    ("review_plan", "S008", "根据我的错题制定复习计划"),
    ("list_index", "S008", "这门课程的列表索引是什么意思？"),
    ("zero_wrong_plan", "S007", "我没有错题，请根据我的错题制定复习计划"),
)


def inspect_case(case_id: str, result: dict | None) -> dict:
    if result is None:
        return {"completed": False}
    names = result.get("called_tools", [])
    trace = result.get("tool_trace", [])
    arguments = [(entry["tool_name"], entry.get("arguments", {})) for entry in trace]
    skill_ids = [args.get("skill_id") for name, args in arguments
                 if name == "load_student_skill"]
    checks = {
        "completed": bool(result.get("answer")),
        "tool_trace_complete": len(names) == len(trace),
    }
    if case_id == "weak_topics":
        checks.update({
            "queried_wrong_data": bool({"analyze_current_course_wrong_questions",
                                        "get_current_course_wrong_questions"} & set(names)),
            "diagnosis_skill_loaded": "wrong_question_diagnosis" in skill_ids,
            "no_complete_plan": "finalize_current_course_review_plan" not in names,
        })
    elif case_id == "review_plan":
        ordered = ("prepare_current_course_review_plan",
                   "validate_current_course_diagnoses",
                   "finalize_current_course_review_plan")
        positions = [names.index(name) if name in names else -1 for name in ordered]
        checks.update({
            "both_skills_loaded": {"wrong_question_diagnosis", "grounded_review_plan"}
                                  <= set(skill_ids),
            "plan_tool_order": -1 not in positions and positions == sorted(positions),
            "final_plan_success": isinstance(result.get("review_plan"), dict)
                                  and result["review_plan"].get("status") == "success",
        })
    elif case_id == "list_index":
        checks.update({
            "material_search_called": "searchlearningmaterial" in names,
            "no_unrelated_diagnosis_skill": "wrong_question_diagnosis" not in skill_ids,
            "no_wrong_question_lookup": not {"analyze_current_course_wrong_questions",
                                             "get_current_course_wrong_questions"} & set(names),
        })
    else:
        checks.update({
            "wrong_data_checked": bool({"prepare_current_course_review_plan",
                                        "analyze_current_course_wrong_questions",
                                        "get_current_course_wrong_questions"} & set(names)),
            "no_invented_plan": result.get("review_plan") is None or not result["review_plan"].get("weak_topics"),
            "zero_wrong_status_seen": "no_recorded_wrong_questions" in json.dumps(trace, ensure_ascii=False),
        })
    return checks


def main() -> None:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    output_dir = ROOT / "eval_results" / f"real_student_skill_calls_{run_id}"
    output_dir.mkdir(parents=True)
    with sqlite3.connect(str(DATABASE_FILE)) as source, sqlite3.connect(str(output_dir / "education.db")) as dest:
        source.backup(dest)
    engine = create_engine(f"sqlite:///{(output_dir / 'education.db').as_posix()}",
                           connect_args={"check_same_thread": False})
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    checkpoint_connection = sqlite3.connect(str(output_dir / "checkpoint.db"), check_same_thread=False)
    saver = SqliteSaver(checkpoint_connection)
    saver.setup()
    rows = []
    try:
        with sessions() as db:
            for case_id, student_id, _ in CASES:
                db.add(ChatSession(id=f"EVAL_{run_id}_{case_id}", user_id=student_id,
                                   course_id="PYTHON101", status="active", title="real skill evaluation"))
            db.commit()
        preflight = search_course_materials_with_fallback(
            course_id="PYTHON101", topic="Python列表", query="列表索引", top_k=1)
        agent = build_student_agent(checkpointer=saver)
        with patch.object(agent_runner, "SessionLocal", sessions), \
             patch.object(agent_runner, "student_agent", agent), \
             patch.object(memory_service, "get_short_term_messages", return_value=[]), \
             patch.object(memory_service, "add_short_term_message"):
            for case_id, student_id, question in CASES:
                started = perf_counter()
                result = None
                error = None
                try:
                    result = agent_runner.run_agent_with_memory(
                        user_id=student_id,
                        session_id=f"EVAL_{run_id}_{case_id}",
                        user_input=question,
                    )
                except Exception as exc:
                    error = exc
                row = {
                    "case_id": case_id, "student_id": student_id,
                    "course_id": "PYTHON101", "question": question,
                    "answer": result.get("answer") if result else None,
                    "called_tools": result.get("called_tools", []) if result else [],
                    "tool_trace": result.get("tool_trace", []) if result else [],
                    "review_plan": result.get("review_plan") if result else None,
                    "checks": inspect_case(case_id, result),
                    "error_type": type(error).__name__ if error else None,
                    "error_message": str(error)[:500] if error else None,
                    "elapsed_s": round(perf_counter() - started, 3),
                }
                rows.append(row)
                (output_dir / f"{case_id}.json").write_text(
                    json.dumps(row, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
                print(json.dumps({"case_id": case_id, "called_tools": row["called_tools"],
                                  "checks": row["checks"], "error": row["error_type"]},
                                 ensure_ascii=False), flush=True)
    finally:
        checkpoint_connection.close()
        engine.dispose()
    summary = {
        "run_id": run_id, "model": "deepseek-chat", "preflight_status": preflight.get("status"),
        "case_count": len(rows), "cases": [{"id": row["case_id"], "checks": row["checks"],
                                        "error_type": row["error_type"],
                                        "elapsed_s": row["elapsed_s"]} for row in rows],
        "note": "tool_trace is the real per-turn Agent trace; its result_preview is capped by agent_runner.",
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                              encoding="utf-8")
    print(json.dumps({"output_dir": str(output_dir), "summary": summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
