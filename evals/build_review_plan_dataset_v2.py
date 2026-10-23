"""Deterministically extend the immutable v1 fixture for review-plan evaluation."""

import json
from pathlib import Path


HERE = Path(__file__).resolve().parent / "fixtures"


def build() -> dict:
    data = json.loads((HERE / "student_agent_dataset_v1.json").read_text(encoding="utf-8"))
    data["dataset_id"] = "student-agent-synthetic-v2"
    data["description"] = (
        "虚构的复习计划对照数据：多学生、多题型、多知识点、重复错误、"
        "缺少解析、无错题与跨课程；不包含真实学生记录。"
    )
    new_students = (
        "S_EVAL_LIST", "S_EVAL_FUNC", "S_EVAL_MIXED", "S_EVAL_CORRECT",
        "S_EVAL_BOTH", "S_EVAL_NOEX", "S_EVAL_OTHER_ONLY",
    )
    data["students"].extend({"id": sid, "name": f"虚构学生{index}"}
                            for index, sid in enumerate(new_students, 1))
    data["enrollments"].extend(
        {"student_id": sid, "course_id": "C_EVAL_MAIN"}
        for sid in new_students if sid != "S_EVAL_OTHER_ONLY"
    )
    data["enrollments"].extend([
        {"student_id": "S_EVAL_BOTH", "course_id": "C_EVAL_OTHER"},
        {"student_id": "S_EVAL_OTHER_ONLY", "course_id": "C_EVAL_OTHER"},
    ])

    def question(qid, topic, stem, right, wrong, explanation, difficulty="medium",
                 qtype="single_choice"):
        return {"id": qid, "course_id": "C_EVAL_MAIN", "topic": topic,
                "type": qtype, "difficulty": difficulty, "stem": stem,
                "options": {"A": right, "B": wrong}, "answer_key": "A",
                "explanation": explanation}

    data["questions"].extend([
        question("Q_LIST_02", "Python列表", "长度为4的列表最后一个正向索引是？",
                 "3", "4", "索引范围是0到长度减1。", "medium"),
        question("Q_LIST_03", "Python列表", "读取列表下标等于长度的位置会怎样？",
                 "抛出IndexError", "返回最后一项", "下标等于长度时越界。", "hard"),
        question("Q_FUNC_02", "函数返回值", "执行return后函数会怎样？",
                 "结束当前函数并返回值", "继续执行后续语句", "return会结束当前函数。", "medium"),
        question("Q_LOOP_01", "Python循环", "range(3)产生哪些整数？",
                 "0、1、2", "1、2、3", "range的终点不包含3。", "easy"),
        question("Q_LOOP_02", "Python循环", "for循环中break的作用是？",
                 "退出当前循环", "跳过本次迭代", "break退出循环；continue跳过本次迭代。", "hard"),
        question("Q_DICT_01", "Python字典", "字典读取不存在的键使用[]会怎样？",
                 "抛出KeyError", "返回None", "[]读取缺失键会抛出KeyError。", "medium"),
        question("Q_DICT_02", "Python字典", "dict.get读取不存在的键默认返回？",
                 "None", "KeyError", "get在键不存在且无默认值时返回None。", "easy"),
        question("Q_BOOL_01", "布尔判断", "Python中bool([])的结果是？",
                 "False", "True", "空列表为假。", "easy", "true_false"),
        question("Q_NOEX_01", "异常处理", "发生异常时except块何时执行？",
                 "匹配到异常时", "每次都执行", None, "medium"),
    ])
    data["exams"].append({
        "id": "E_EVAL_ADVANCED", "course_id": "C_EVAL_MAIN", "title": "综合练习",
        "question_ids": ["Q_LIST_02", "Q_LIST_03", "Q_FUNC_02", "Q_LOOP_01",
                         "Q_LOOP_02", "Q_DICT_01", "Q_DICT_02", "Q_BOOL_01", "Q_NOEX_01"],
    })
    data["exams"].append({
        "id": "E_EVAL_RECHECK", "course_id": "C_EVAL_MAIN", "title": "基础复测",
        "question_ids": ["Q_LIST_01", "Q_FUNC_01"],
    })

    def attempt(exam_id, sid, wrong_ids, answered_ids):
        answers = []
        for qid in answered_ids:
            wrong = qid in wrong_ids
            answers.append({"question_id": qid, "answer": "B" if wrong else "A",
                            "is_correct": not wrong, "score": 0.0 if wrong else 1.0})
        data["attempts"].append({"exam_id": exam_id, "student_id": sid,
                                 "answers": answers})

    main_pair = ["Q_LIST_01", "Q_FUNC_01"]
    advanced = next(exam["question_ids"] for exam in data["exams"]
                    if exam["id"] == "E_EVAL_ADVANCED")
    attempt("E_EVAL_ADVANCED", "S_EVAL_MAIN",
            {"Q_LIST_02", "Q_LOOP_01", "Q_BOOL_01"}, advanced)
    # A second independent graded attempt makes repeated errors measurable.
    attempt("E_EVAL_RECHECK", "S_EVAL_MAIN", {"Q_LIST_01", "Q_FUNC_01"}, main_pair)
    attempt("E_EVAL_MAIN", "S_EVAL_LIST", {"Q_LIST_01"}, main_pair)
    attempt("E_EVAL_ADVANCED", "S_EVAL_LIST", {"Q_LIST_02", "Q_LIST_03"}, advanced)
    attempt("E_EVAL_MAIN", "S_EVAL_FUNC", {"Q_FUNC_01"}, main_pair)
    attempt("E_EVAL_ADVANCED", "S_EVAL_FUNC", {"Q_FUNC_02"}, advanced)
    attempt("E_EVAL_MAIN", "S_EVAL_MIXED", set(main_pair), main_pair)
    attempt("E_EVAL_ADVANCED", "S_EVAL_MIXED",
            {"Q_LOOP_01", "Q_DICT_01", "Q_DICT_02"}, advanced)
    attempt("E_EVAL_MAIN", "S_EVAL_CORRECT", set(), main_pair)
    attempt("E_EVAL_MAIN", "S_EVAL_BOTH", {"Q_LIST_01"}, main_pair)
    attempt("E_EVAL_OTHER", "S_EVAL_BOTH", {"Q_SECRET_01"}, ["Q_SECRET_01"])
    attempt("E_EVAL_ADVANCED", "S_EVAL_NOEX", {"Q_NOEX_01"}, ["Q_NOEX_01"])
    attempt("E_EVAL_OTHER", "S_EVAL_OTHER_ONLY", {"Q_SECRET_01"}, ["Q_SECRET_01"])

    questions = {q["id"]: q for q in data["questions"]}
    exams = {e["id"]: e for e in data["exams"]}
    wrong = {(item["student_id"], exams[item["exam_id"]]["course_id"],
              answer["question_id"])
             for item in data["attempts"] for answer in item["answers"]
             if not answer["is_correct"]}
    data["wrong_questions"] = [
        {"student_id": sid, "course_id": cid, "question_id": qid,
         "topic": questions[qid]["topic"], "mistake": "固定评测错误作答"}
        for sid, cid, qid in sorted(wrong)
    ]

    def material(mid, topic, contents):
        data["materials"].append({
            "material_id": mid, "course_id": "C_EVAL_MAIN", "topic": topic,
            "original_filename": f"{mid.lower()}.md",
            "chunks": [{"chunk_id": f"{mid}:chunk:{i}", "position": i, "content": content}
                       for i, content in enumerate(contents, 1)],
        })

    material("M_LIST_EXTRA", "Python列表", [
        "长度为n的列表，合法正向索引是0到n-1；访问下标n会抛出IndexError。"])
    material("M_LOOP", "Python循环", [
        "range(3)依次产生0、1、2，不包含终点3。",
        "break退出当前循环；continue只跳过当前这次迭代。"])
    material("M_DICT", "Python字典", [
        "字典用[]读取缺失键会抛出KeyError；get读取缺失键默认返回None。"])
    material("M_BOOL", "布尔判断", ["空列表在布尔判断中为False。"])
    return data


if __name__ == "__main__":
    target = HERE / "student_agent_dataset_v2.json"
    target.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target)
