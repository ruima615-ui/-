from sqlalchemy.orm import Session
from datetime import datetime, timezone
from app.repositories.wrong_question_repository import (
    get_course_question,
    get_latest_wrong_exam_answer,
    get_student_topic_wrong_stats,
    get_student_wrong_questions,
)


#薄弱知识点评分权重
ERROR_RATE_WEIGHT = 0.6
RECENCY_WEIGHT = 0.2
DIFFICULTY_WEIGHT = 0.2
#难题的权重
DIFFICULTY_LEVEL_WEIGHTS = {
    "easy": 1.0,
    "medium": 0.6,
    "hard": 0.3,
}
#计算错误率
def calculate_error_rate(
    wrong_attempts: int,#这个知识点总共错了多少次
    total_attempts: int,#这个知识点总共做了多少次
) -> float:
    if total_attempts <= 0:
        return 0.0

    return round(wrong_attempts / total_attempts,4)
#计算最近一次答错距离现在有多久
def calculate_recency_weight(
    last_wrong_at,
    now=None,
) -> float:
    """根据最近一次错误时间计算权重。"""

    if last_wrong_at is None:
        return 0.0

    if now is None:
        now = datetime.now(
            timezone.utc
        ).replace(tzinfo=None)

    days_since_wrong = max(
        (now - last_wrong_at).days,
        0,
    )

    if days_since_wrong <= 7:
        return 1.0

    if days_since_wrong <= 30:
        return 0.6

    if days_since_wrong <= 90:
        return 0.3

    return 0.1

def calculate_difficulty_weight(
    *,
    wrong_attempts: int,
    difficulty_distribution: dict[str, int],
) -> float:
    """校验难度分布，并计算难度修正权重。"""

    expected_levels = {
        "easy",
        "medium",
        "hard",
    }

    # 只能包含三种合法难度。
    if set(difficulty_distribution) != expected_levels:
        raise ValueError(
            "难度分布必须且只能包含："
            "easy、medium、hard"
        )

    # 每种难度的错误次数必须是非负整数。
    if any(
        type(count) is not int or count < 0
        for count
        in difficulty_distribution.values()
    ):
        raise ValueError(
            "各难度的错误次数必须是非负整数"
        )

    counted_wrong_attempts = sum(
        difficulty_distribution.values()
    )

    # 检查是否存在没有合法难度的错题。
    if counted_wrong_attempts != wrong_attempts:
        raise ValueError(
            "错题难度数据不完整："
            f"错误作答共 {wrong_attempts} 次，"
            f"按合法难度统计到 "
            f"{counted_wrong_attempts} 次"
        )

    if wrong_attempts == 0:
        return 0.0

    weighted_sum = sum(
        difficulty_distribution[level]
        * DIFFICULTY_LEVEL_WEIGHTS[level]
        for level in expected_levels
    )

    return round(
        weighted_sum / wrong_attempts,
        4,
    )
def calculate_priority_score(
    error_rate: float,
    recency_weight: float,
    difficulty_weight: float,
) -> float:
    """结合错误率和最近错误权重以及难度权重计算薄弱度"""
    score = (
        error_rate * ERROR_RATE_WEIGHT
        + recency_weight * RECENCY_WEIGHT
        + difficulty_weight * DIFFICULTY_WEIGHT
    )
    return round(score, 4)
def classify_priority(
    priority_score: float,
) -> str:
    """将薄弱度分数转换为等级。"""

    if priority_score >= 0.75:
        return "high"

    if priority_score >= 0.45:
        return "medium"

    return "low"
    
def analyze_course_wrong_questions(
    db: Session,
    student_id: str,
    course_id: str,
) -> dict:
    """使用错误率和最近错误权重分析薄弱知识点。"""

    records = get_student_wrong_questions(
        db=db,
        student_id=student_id,
        course_id=course_id,
    )

    if not records:
        return {
            "status": "no_recorded_wrong_questions",
            "analysis_version": "v2",
            "student_id": student_id,
            "course_id": course_id,
            "total_wrong_questions": 0,
            "total_wrong_attempts": 0,
            "total_attempts": 0,
            "topic_counts": {},
            "topic_analysis": [],
            "priority_topic": None,
            "evidence_questions": [],
            "message": (
                "当前没有已记录的错题，"
                "不能据此判断学生已经全部掌握"
            ),
        }

    history_stats = get_student_topic_wrong_stats(
        db=db,
        student_id=student_id,
        course_id=course_id,
    )

    stats_by_topic = {
        item["topic"]: item
        for item in history_stats
    }

    records_by_topic = {}

    for record in records:
        records_by_topic.setdefault(
            record.topic,
            [],
        ).append(record)

    topic_analysis = []

    for topic, topic_records in records_by_topic.items():
        question_ids = list(dict.fromkeys(
            record.question_id
            for record in topic_records
        ))

        stat = stats_by_topic.get(topic)

        if stat is not None:
            unique_wrong_questions = stat[
                "unique_wrong_questions"
            ]
            wrong_attempts = stat[
                "wrong_attempts"
            ]
            total_attempts = stat[
                "total_attempts"
            ]
            last_wrong_at = stat[
                "last_wrong_at"
            ]
            difficulty_distribution = {
    "easy": stat[
        "easy_wrong_attempts"
    ],
    "medium": stat[
        "medium_wrong_attempts"
    ],
    "hard": stat[
        "hard_wrong_attempts"
    ],
}

            difficulty_weight = (
                calculate_difficulty_weight(
                    wrong_attempts=wrong_attempts,
                    difficulty_distribution=(
                        difficulty_distribution
                    ),
                )
            )


        
            error_rate = calculate_error_rate(
                wrong_attempts=wrong_attempts,
                total_attempts=total_attempts,
            )

            recency_weight = (
                calculate_recency_weight(
                    last_wrong_at=last_wrong_at,
                )
            )

            priority_score = (
                calculate_priority_score(
                    error_rate=error_rate,
                    recency_weight=recency_weight,
                    difficulty_weight=difficulty_weight,
                )
            )

            priority_level = classify_priority(
                priority_score
            )

            analysis_basis = "exam_history"
        else:
            # 兼容旧练习接口产生的错题。
            unique_wrong_questions = len(
                question_ids
            )
            wrong_attempts = len(
                question_ids
            )
            total_attempts = None
            error_rate = None

            recorded_times = [
                record.created_at
                for record in topic_records
                if record.created_at is not None
            ]

            last_wrong_at = (
                max(recorded_times)
                if recorded_times
                else None
            )

            recency_weight = (
                calculate_recency_weight(
                    last_wrong_at=last_wrong_at,
                )
            )

            difficulty_distribution = {
                "easy": 0,
                "medium": 0,
                "hard": 0,
            }

            for question_id in question_ids:
                question = get_course_question(
                    db=db,
                    course_id=course_id,
                    question_id=question_id,
                )

                if question is None:
                    raise ValueError(
                        "错题对应的题目不存在："
                        f"{question_id}"
                    )

                if (
                    question.difficulty
                    not in DIFFICULTY_LEVEL_WEIGHTS
                ):
                    raise ValueError(
                        f"题目 {question.id} "
                        "的难度无效："
                        f"{question.difficulty}"
                    )

                difficulty_distribution[
                    question.difficulty
                ] += 1

            difficulty_weight = (
                calculate_difficulty_weight(
                    wrong_attempts=wrong_attempts,
                    difficulty_distribution=(
                        difficulty_distribution
                    ),
                )
            )

            # 没有完整作答历史时，
            # 不伪造错误率和综合薄弱分数。
            priority_score = None
            priority_level = "insufficient_data"
            analysis_basis = "wrong_records_only"
        topic_analysis.append({
            "topic": topic,
            "unique_wrong_questions": (
                unique_wrong_questions
            ),
            "wrong_attempts": wrong_attempts,
            "total_attempts": total_attempts,
            "error_rate": error_rate,
            "last_wrong_at": last_wrong_at,
            "recency_weight": recency_weight,
            "difficulty_distribution": (
                difficulty_distribution
            ),
            "difficulty_weight": (
                difficulty_weight
            ),
            "priority_score": priority_score,
            "priority_level": priority_level,
            "analysis_basis": analysis_basis,
            "evidence_question_ids": question_ids,
        })

    # 先比较薄弱度，再比较错误次数和不同错题数。
    topic_analysis.sort(
        key=lambda item: (
            (
                item["priority_score"]
                if item["priority_score"] is not None
                else -1
            ),
            item["wrong_attempts"],
            item["unique_wrong_questions"],
        ),
        reverse=True,
    )

    priority_topic = topic_analysis[0][
        "topic"
    ]

    evidence_questions = [
        {
            "question_id": record.question_id,
            "mistake": record.mistake,
        }
        for record in records_by_topic[
            priority_topic
        ]
    ]

    topic_counts = {
        item["topic"]: item[
            "unique_wrong_questions"
        ]
        for item in topic_analysis
    }

    total_wrong_attempts = sum(
        item["wrong_attempts"]
        for item in topic_analysis
    )

    total_attempts = sum(
        item["total_attempts"] or 0
        for item in topic_analysis
    )

    # 工具结果需要可以被 JSON 序列化。
    serialized_topic_analysis = [
        {
            **item,
            "last_wrong_at": (
                item["last_wrong_at"].isoformat()
                if item["last_wrong_at"] is not None
                else None
            ),
        }
        for item in topic_analysis
    ]

    return {
        "status": "success",
        "analysis_version": "v2",
        "student_id": student_id,
        "course_id": course_id,
        "total_wrong_questions": len(records),
        "total_wrong_attempts": (
            total_wrong_attempts
        ),
        "total_attempts": total_attempts,
        "topic_counts": topic_counts,
        "topic_analysis": (
            serialized_topic_analysis
        ),
        "priority_topic": priority_topic,
        "evidence_questions": (
            evidence_questions
        ),
        "scoring_rule": {
        "error_rate_weight": (
            ERROR_RATE_WEIGHT
        ),
        "recency_weight": (
            RECENCY_WEIGHT
        ),
        "difficulty_weight": (
            DIFFICULTY_WEIGHT
        ),
        "difficulty_level_weights": (
            DIFFICULTY_LEVEL_WEIGHTS
        ),
    },
    }
def get_course_wrong_question_details(
    db: Session,
    student_id: str,
    course_id: str,
) -> dict:
    """返回当前学生在当前课程中的完整错题证据。"""

    records = get_student_wrong_questions(
        db=db,
        student_id=student_id,
        course_id=course_id,
    )

    wrong_questions = []

    for record in records:
        question = get_course_question(
            db=db,
            course_id=course_id,
            question_id=record.question_id,
        )

        latest_answer = get_latest_wrong_exam_answer(
            db=db,
            student_id=student_id,
            course_id=course_id,
            question_id=record.question_id,
        )

        wrong_questions.append({
            "question_id": record.question_id,
            "topic": record.topic,
            "question_type": (
                question.question_type
                if question is not None
                else None
            ),
            "difficulty": (
                question.difficulty
                if question is not None
                else None
            ),
            "difficulty_score": (
                question.difficulty_score
                if question is not None
                else None
            ),
            "stem": (
                question.stem
                if question is not None
                else None
            ),
            "options": (
                question.options
                if question is not None
                else None
            ),
            "student_answer": (
                latest_answer.answer
                if latest_answer is not None
                else None
            ),
            "correct_answer": (
                question.answer_key
                if question is not None
                else None
            ),
            "explanation": (
                question.explanation
                if question is not None
                else None
            ),
            "mistake": record.mistake,
            "recorded_at": (
                record.created_at.isoformat()
                if record.created_at is not None
                else None
            ),
        })

    return {
        "status": (
            "success"
            if records
            else "no_recorded_wrong_questions"
        ),
        "student_id": student_id,
        "course_id": course_id,
        "total_wrong_questions": len(records),
        "wrong_questions": wrong_questions,
    }