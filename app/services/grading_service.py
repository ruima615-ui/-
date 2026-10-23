#判断题目，单选多选以及判断自动判断，简答题可以暂存答案，人工判断

def grade_answer(
    question_type: str,
    answer_key: dict | None,
    answer: dict,
    max_score: float
) -> dict:
    """判题；返回评分状态、对错和得分"""

    if max_score <= 0:
        raise ValueError("题目分值必须大于0")

    if not isinstance(answer, dict):
        raise ValueError("答案必须是对象")

    if question_type == "short_answer":
        text = answer.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("简答题答案不能为空")

        return {
            "grading_status": "pending",
            "is_correct": None,
            "score": None
        }

    if not isinstance(answer_key, dict):
        raise ValueError("客观题缺少标准答案")

    if question_type == "single_choice":
        selected = answer.get("value")
        correct = answer_key.get("value")

        if not isinstance(selected, str) or not isinstance(correct, str):
            raise ValueError("单选题答案格式错误")

        is_correct = selected.upper() == correct.upper()

    elif question_type == "multiple_choice":
        selected = answer.get("values")
        correct = answer_key.get("values")

        if (
            not isinstance(selected, list)
            or not isinstance(correct, list)
            or not selected
            or not all(isinstance(value, str) for value in selected + correct)
            or len(selected) != len(set(selected))
        ):
            raise ValueError("多选题答案格式错误")

        is_correct = set(selected) == set(correct)

    elif question_type == "true_false":
        selected = answer.get("value")
        correct = answer_key.get("value")

        if type(selected) is not bool or type(correct) is not bool:
            raise ValueError("判断题答案必须为true或false")

        is_correct = selected == correct

    else:
        raise ValueError(f"不支持的题型：{question_type}")

    return {
        "grading_status": "graded",
        "is_correct": is_correct,
        "score": max_score if is_correct else 0.0
    }