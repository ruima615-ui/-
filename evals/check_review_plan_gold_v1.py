"""Independent raw-fixture checks; does not import review-plan business services."""

import json
from collections import Counter
from pathlib import Path

from evals.build_review_plan_gold_v1 import FIXTURES, GOLD_PATH


def check_gold(gold_path=GOLD_PATH):
    data = json.loads((FIXTURES / "student_agent_dataset_v3.json").read_text(encoding="utf-8"))
    cases = {row["id"]: row for row in json.loads(
        (FIXTURES / "review_plan_comparison_cases_v3.json").read_text(encoding="utf-8"))}
    gold = json.loads(Path(gold_path).read_text(encoding="utf-8"))
    questions = {q["id"]: q for q in data["questions"]}
    exams = {e["id"]: e for e in data["exams"]}
    enrollments = {(r["student_id"], r["course_id"]) for r in data["enrollments"]}
    materials = {(r["course_id"], r["topic"]) for r in data["materials"]}
    wrong = set()
    for attempt in data["attempts"]:
        course_id = exams[attempt["exam_id"]]["course_id"]
        for answer in attempt["answers"]:
            if answer["is_correct"] is False:
                wrong.add((attempt["student_id"], course_id, answer["question_id"]))

    errors = []
    for row in gold["cases"]:
        case_id, ref = row["case_id"], row["reference"]
        case = cases.get(case_id)
        if case is None:
            errors.append(f"{case_id}: 用例不存在")
            continue
        sid, cid = case["student_id"], case["course_id"]
        if (sid, cid) not in enrollments:
            errors.append(f"{case_id}: 学生未选当前课程")
        if ref["status"] == "PermissionError":
            if case.get("session_owner", sid) == sid:
                errors.append(f"{case_id}: 越权用例的会话所有者与学生相同")
            continue
        if len(ref["topics"]) > 2 or len(ref["topics"]) != len(set(ref["topics"])):
            errors.append(f"{case_id}: Top-2 知识点数量或唯一性错误")
        if len(ref["evidence_question_ids"]) > 4 or len(ref["evidence_question_ids"]) != len(set(ref["evidence_question_ids"])):
            errors.append(f"{case_id}: 错题证据数量或唯一性错误")
        actual_wrong = {qid for owner, course, qid in wrong if owner == sid and course == cid}
        for qid in ref["evidence_question_ids"]:
            question = questions.get(qid)
            if (qid not in actual_wrong or question is None or question["course_id"] != cid
                    or question["topic"] not in ref["topics"]):
                errors.append(f"{case_id}: 证据题目 {qid} 不属于该学生当前课程的所选错题知识点")
        if not set(ref["task_topics"]) <= set(ref["topics"]):
            errors.append(f"{case_id}: 任务知识点超出所选知识点")
        if len(ref["task_topics"]) != len(set(ref["task_topics"])):
            errors.append(f"{case_id}: 同一知识点重复生成任务")
        for topic in ref["task_topics"]:
            if (cid, topic) not in materials or topic in case.get("blocked_topics", []):
                errors.append(f"{case_id}: 任务知识点 {topic} 没有可用固定资料")
        mode = case["material_mode"]
        if not actual_wrong:
            if ref["status"] != "no_recorded_wrong_questions" or any(
                    ref[key] for key in ("topics", "evidence_question_ids", "task_topics")):
                errors.append(f"{case_id}: 零错题预期不一致")
        elif mode in {"unavailable", "no_relevant", "mcp_failure"}:
            expected = {"unavailable": "course_materials_not_configured",
                        "no_relevant": "course_materials_insufficient",
                        "mcp_failure": "material_retrieval_failed"}[mode]
            if ref["status"] != expected:
                errors.append(f"{case_id}: 资料模式和预期状态不一致")
            if ref["task_topics"]:
                errors.append(f"{case_id}: 无可用检索结果却预期生成任务")
        elif ref["status"] == "success" and set(ref["task_topics"]) != set(ref["topics"]):
            errors.append(f"{case_id}: 完整计划缺少知识点任务")
        elif ref["status"] == "partial" and (not ref["task_topics"] or
                                                 set(ref["task_topics"]) == set(ref["topics"])):
            errors.append(f"{case_id}: 部分计划的任务范围不合理")

    counts = Counter(row["reference"]["status"] for row in gold["cases"])
    reviewed = sum(
        row["review"]["status"] == "approved"
        and bool(row["review"].get("reviewer"))
        and bool(row["review"].get("reviewed_at"))
        and all(row["review"].get(key) is True for key in (
            "topic_priority_correct", "evidence_selection_correct", "expected_status_correct"))
        and isinstance(row["review"].get("acceptable_material_ids"), list)
        for row in gold["cases"]
    )
    return {"case_count": len(gold["cases"]), "unique_ids": len({r["case_id"] for r in gold["cases"]}),
            "status_counts": dict(counts), "raw_data_errors": errors,
            "human_approved": reviewed, "gold_ready": not errors and reviewed == len(gold["cases"])}


if __name__ == "__main__":
    print(json.dumps(check_gold(), ensure_ascii=False, indent=2))
