"""Select a stratified Gold v1 draft; human approval remains explicit."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures"
GOLD_PATH = FIXTURES / "review_plan_gold_v1.json"
REVIEW_SHEET = ROOT.parent / "docs" / "review_plan_gold_v1_review_sheet.md"

# Ten successful plans, then coverage of zero wrong, unavailable/partial
# materials, no relevance, MCP failure and two independent ownership cases.
GOLD_CASE_IDS = (
    "main_top2_plan", "list_single_topic", "function_single_topic",
    "mixed_four_topics", "both_course_scope", "loop_three_errors",
    "dict_three_errors", "slice_two_topics", "retry_repeat_wrong", "hybrid_top2",
    "empty_no_exam", "correct_verify_zero",
    "no_explanation", "loop_no_material",
    "dict_partial_func", "hybrid_partial",
    "slice_no_relevant", "dict_mcp_failure",
    "session_ownership", "session_ownership_v3",
)


def build():
    cases = {row["id"]: row for row in json.loads(
        (FIXTURES / "review_plan_comparison_cases_v3.json").read_text(encoding="utf-8"))}
    if len(set(GOLD_CASE_IDS)) != 20 or set(GOLD_CASE_IDS) - cases.keys():
        raise ValueError("Gold v1 选择的 20 个用例 ID 无效")
    rows = []
    for case_id in GOLD_CASE_IDS:
        case = cases[case_id]
        reference = {
            "status": case.get("expected_status", case.get("expect_error")),
            "topics": case.get("expected_topics", []),
            "evidence_question_ids": case.get("expected_evidence_ids", []),
            "task_topics": case.get("expected_task_topics", []),
        }
        rows.append({
            "case_id": case_id,
            "reference": reference,
            "review": {
                "status": "pending_human",
                "reviewer": None,
                "reviewed_at": None,
                "topic_priority_correct": None,
                "evidence_selection_correct": None,
                "expected_status_correct": None,
                "acceptable_material_ids": None,
                "notes": None,
            },
        })
    return {
        "gold_id": "review-plan-gold-v1-draft",
        "dataset_id": "student-agent-synthetic-v3",
        "case_count": 20,
        "provenance": "业务预期拷贝后独立检查原始数据；尚未人工复核",
        "cases": rows,
    }


def build_review_sheet(gold):
    data = json.loads((FIXTURES / "student_agent_dataset_v3.json").read_text(encoding="utf-8"))
    cases = {row["id"]: row for row in json.loads(
        (FIXTURES / "review_plan_comparison_cases_v3.json").read_text(encoding="utf-8"))}
    questions = {row["id"]: row for row in data["questions"]}
    exams = {row["id"]: row for row in data["exams"]}
    lines = ["# Gold v1 人工复核表（待审核）", "",
             "以下预期来自现有评测用例，尚不能称为独立人工 Gold。逐项核对后，",
             "在 `review_plan_gold_v1.json` 的对应 `review` 字段登记审核人、时间、判断与备注。",
             "重点复核 Top-2 优先级、证据题目是否恰当，以及资料是否足以支持计划任务。", ""]
    for index, row in enumerate(gold["cases"], 1):
        case = cases[row["case_id"]]
        ref = row["reference"]
        sid, cid = case["student_id"], case["course_id"]
        wrong_counts = {}
        answers = {}
        for attempt in data["attempts"]:
            if attempt["student_id"] != sid or exams[attempt["exam_id"]]["course_id"] != cid:
                continue
            for answer in attempt["answers"]:
                if answer["is_correct"] is False:
                    qid = answer["question_id"]
                    topic = questions[qid]["topic"]
                    wrong_counts[topic] = wrong_counts.get(topic, 0) + 1
                    answers[qid] = answer["answer"]
        lines += [f"## {index}. `{row['case_id']}`", "",
                  f"- 提问：{case['question']}",
                  f"- 学生 / 课程：`{sid}` / `{cid}`",
                  f"- 当前课程错误作答次数（按知识点）：{wrong_counts or '无'}",
                  f"- 预期状态：`{ref['status']}`；资料模式：`{case['material_mode']}`",
                  f"- 预期 Top-2：{ref['topics']}",
                  f"- 预期任务知识点：{ref['task_topics']}",
                  f"- 资料缺失知识点：{case.get('blocked_topics', [])}",
                  "- 选中错题证据：", ""]
        for qid in ref["evidence_question_ids"]:
            q = questions[qid]
            chosen = answers.get(qid)
            lines.append(f"  - `{qid}`｜{q['topic']}｜{q['stem']}｜学生："
                         f"{chosen}「{q['options'].get(chosen, '')}」｜正确："
                         f"{q['answer_key']}「{q['options'][q['answer_key']]}」")
        if not ref["evidence_question_ids"]:
            lines.append("  - 无")
        lines += ["", "- 人工复核：知识点排序 □；证据选择 □；状态/任务范围 □；资料适用性 □。", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    gold = build()
    GOLD_PATH.write_text(json.dumps(gold, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    REVIEW_SHEET.write_text(build_review_sheet(gold), encoding="utf-8")
    print(GOLD_PATH)
    print(REVIEW_SHEET)
