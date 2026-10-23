"""Run the single-agent baseline on existing graded PYTHON101 exam records.

The business SQLite database is copied with SQLite's backup API. Evaluation
sessions and messages exist only in that copy; Chroma and the LLM are real.
"""

import argparse
import hashlib
import json
import sqlite3
import traceback
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from unittest.mock import patch
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import agent_runner
from app.core.config import DATABASE_FILE
from app.models.entities import ChatSession, Exam, ExamAnswer, ExamAttempt
from app.services import memory_service
from student_agent import build_student_agent
from app.services.material_search_service import search_course_materials_with_fallback


PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_DIR / "eval_results"
COURSE_ID = "PYTHON101"
CASES = (
    ("wrong_exam", "S008", (
        "请根据我在当前课程已评分考试中的错题，分析薄弱知识点和依据。",
        "请检索当前课程资料，结合刚才的薄弱知识点解释相关内容，并标出资料来源。",
        "请根据真实错题诊断和课程资料，生成完整的结构化复习计划。",
    )),
    ("zero_wrong", "S007", (
        "我认为自己没有错题。请先核查当前课程已评分考试记录，再告诉我是否有薄弱知识点；不要猜测。",
    )),
)


def graded_counts(db, student_id):
    attempts = db.scalar(
        select(func.count(ExamAttempt.id))
        .join(Exam, Exam.id == ExamAttempt.exam_id)
        .where(ExamAttempt.student_id == student_id,
               ExamAttempt.status == "graded", Exam.course_id == COURSE_ID)
    ) or 0
    answers = db.execute(
        select(ExamAnswer.question_id, ExamAnswer.is_correct)
        .join(ExamAttempt, ExamAttempt.id == ExamAnswer.exam_attempt_id)
        .join(Exam, Exam.id == ExamAttempt.exam_id)
        .where(ExamAttempt.student_id == student_id,
               ExamAttempt.status == "graded", Exam.course_id == COURSE_ID,
               ExamAnswer.grading_status == "graded")
    ).all()
    return {"graded_attempts": attempts, "graded_answers": len(answers),
            "wrong_question_ids": sorted({q for q, correct in answers if correct is False})}


def run(output_dir=DEFAULT_OUTPUT):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    results_path = output_dir / f"real_exam_single_agent_{run_id}.jsonl"
    summary_path = output_dir / f"real_exam_single_agent_{run_id}.summary.json"
    rows, evidence = [], {}

    snapshot_dir = output_dir / f"real_exam_single_agent_{run_id}.snapshot"
    snapshot_dir.mkdir()
    # Keep the SQLite snapshot: it documents the exact graded data used by this run.
    with patch.object(memory_service, "get_short_term_messages", return_value=[]):
        db_path = snapshot_dir / "education.db"
        with sqlite3.connect(str(DATABASE_FILE)) as source, sqlite3.connect(str(db_path)) as target:
            source.backup(target)
        engine = create_engine(f"sqlite:///{db_path.as_posix()}",
                               connect_args={"check_same_thread": False})
        session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        checkpoint_connection = sqlite3.connect(str(snapshot_dir / "checkpoint.db"),
                                                check_same_thread=False)
        saver = SqliteSaver(checkpoint_connection)
        saver.setup()
        agent = build_student_agent(checkpointer=saver)
        try:
            # Fail early if the actual course material index cannot be opened.
            preflight = search_course_materials_with_fallback(
                course_id=COURSE_ID, topic="Python列表", query="列表索引", top_k=1)
            print(json.dumps({"retrieval_preflight": preflight.get("status")},
                             ensure_ascii=False), flush=True)
            with session_factory() as db:
                for case_id, student_id, _ in CASES:
                    counts = graded_counts(db, student_id)
                    if counts["graded_attempts"] < 1:
                        raise RuntimeError(f"{case_id}: no graded exam")
                    if bool(counts["wrong_question_ids"]) != (case_id == "wrong_exam"):
                        raise RuntimeError(f"{case_id}: wrong-answer precondition failed")
                    evidence[case_id] = {"student_id": student_id, "course_id": COURSE_ID, **counts}
                    db.add(ChatSession(id=f"EVAL_{run_id}_{case_id}", user_id=student_id,
                                       course_id=COURSE_ID, title="single-agent real exam baseline",
                                       status="active"))
                db.commit()

            with patch.object(agent_runner, "SessionLocal", session_factory), \
                 patch.object(agent_runner, "student_agent", agent), \
                 patch.object(memory_service, "get_short_term_messages", return_value=[]), \
                 patch.object(memory_service, "add_short_term_message"):
                for case_id, student_id, questions in CASES:
                    session_id = f"EVAL_{run_id}_{case_id}"
                    for number, question in enumerate(questions, 1):
                        started = perf_counter()
                        result, error = None, None
                        try:
                            result = agent_runner.run_agent_with_memory(
                                user_id=student_id, session_id=session_id, user_input=question)
                        except Exception as exc:
                            error = exc
                            error_traceback = traceback.format_exc(limit=12)
                        row = {
                            "case_id": case_id, "turn": number, "question": question,
                            "answer": result.get("answer") if result else None,
                            "called_tools": result.get("called_tools", []) if result else [],
                            "tool_trace": result.get("tool_trace", []) if result else [],
                            "review_plan": result.get("review_plan") if result else None,
                            "steps": result.get("steps") if result else None,
                            "elapsed_s": round(perf_counter() - started, 3),
                            "error_type": type(error).__name__ if error else None,
                            "error_message": str(error)[:500] if error else None,
                            "error_traceback": error_traceback if error else None,
                        }
                        rows.append(row)
                        with results_path.open("a", encoding="utf-8") as output:
                            output.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
                        print(json.dumps({"case": case_id, "turn": number,
                                          "tools": row["called_tools"],
                                          "error": row["error_type"]}, ensure_ascii=False), flush=True)
                        if error:
                            break  # A failed tool call can leave an incomplete checkpoint.
        finally:
            checkpoint_connection.close()
            engine.dispose()

    wrong_rows = [row for row in rows if row["case_id"] == "wrong_exam"]
    zero_row = next(row for row in rows if row["case_id"] == "zero_wrong")
    wrong_tools = [tool for row in wrong_rows for tool in row["called_tools"]]
    plan = wrong_rows[-1]["review_plan"] if wrong_rows else None
    plan_question_ids = {item["question_id"] for item in (plan or {}).get("wrong_question_evidence", [])}
    zero_trace = json.dumps(zero_row["tool_trace"], ensure_ascii=False)
    checks = {
        "graded_wrong_exam_present": bool(evidence["wrong_exam"]["wrong_question_ids"]),
        "graded_zero_wrong_exam_present": evidence["zero_wrong"]["graded_attempts"] > 0
            and not evidence["zero_wrong"]["wrong_question_ids"],
        "analysis_called": "analyze_current_course_wrong_questions" in wrong_tools,
        "material_search_called": "searchlearningmaterial" in wrong_tools
            or "validate_current_course_diagnoses" in wrong_tools,
        "plan_prepared": "prepare_current_course_review_plan" in wrong_tools,
        "plan_validated": "validate_current_course_diagnoses" in wrong_tools,
        "plan_finalized": "finalize_current_course_review_plan" in wrong_tools
            and isinstance(plan, dict) and plan.get("status") == "success",
        "plan_question_ids_grounded": bool(plan_question_ids) and plan_question_ids <= set(
            evidence["wrong_exam"]["wrong_question_ids"]),
        "zero_wrong_checked": bool(set(zero_row["called_tools"]) & {
            "analyze_current_course_wrong_questions", "get_current_course_wrong_questions"}),
        "zero_wrong_tool_result": "no_recorded_wrong_questions" in zero_trace,
        "zero_wrong_no_plan": zero_row["review_plan"] is None,
        "all_turns_completed": all(row["error_type"] is None and row["answer"] for row in rows),
    }
    summary = {"run_id": run_id, "data_source": "live graded exam SQLite snapshot",
               "retrieval": "live Chroma", "llm": "configured DeepSeek",
               "evidence": evidence, "checks": checks, "turn_count": len(rows),
               "sqlite_snapshot_sha256": hashlib.sha256(db_path.read_bytes()).hexdigest(),
               "total_elapsed_s": round(sum(row["elapsed_s"] for row in rows), 3),
               "results_file": str(results_path),
               "snapshot_dir": str(snapshot_dir),
               "note": "Tool previews are capped by agent_runner; inspect review_plan for structured evidence. Semantic quality needs human review."}
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str),
                            encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(run(args.output_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
