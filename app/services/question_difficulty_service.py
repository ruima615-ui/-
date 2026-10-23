#教师后台计算题目难度
ALLOWED_LEVELS = {0, 1, 2}


def calculate_question_difficulty(
    *,
    knowledge_count_level: int,
    reasoning_level: int,
    transfer_level: int,
    distractor_level: int,
) -> dict:
    """根据教师选择的四个维度计算题目难度。"""

    dimensions = {
        "knowledge_count_level": knowledge_count_level,
        "reasoning_level": reasoning_level,
        "transfer_level": transfer_level,
        "distractor_level": distractor_level,
    }

    invalid_dimensions = {
        name: value
        for name, value in dimensions.items()
        if type(value) is not int
        or value not in ALLOWED_LEVELS
    }

    if invalid_dimensions:
        raise ValueError(
            f"难度维度必须是 0、1、2：{invalid_dimensions}"
        )
    difficulty_score = sum(dimensions.values())

    if difficulty_score == 0:
        difficulty = "easy"
    elif difficulty_score <= 4:
        difficulty = "medium"
    else:
        difficulty = "hard"

    return {
        "difficulty": difficulty,
        "difficulty_score": difficulty_score,
    }