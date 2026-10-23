import json
from pathlib import Path


# student_tools.py所在的文件夹
BASE_DIR = Path(__file__).resolve().parent

# 学生数据文件路径
DATA_FILE = BASE_DIR / "education_data.json"


def load_education_data():
    """读取教育数据JSON文件"""

    with DATA_FILE.open("r", encoding="utf-8") as file:
        return json.load(file)


def getstudentscore(student_name):
    """根据学生姓名查询模拟成绩"""

    data = load_education_data()
    students = data["students"]

    if student_name not in students:
        return "没有找到该学生的成绩"

    return students[student_name]["score"]


def getwrongquestions(student_name):
    """根据学生姓名查询模拟错题记录"""

    data = load_education_data()
    students = data["students"]

    if student_name not in students:
        return "没有找到该学生的错题记录"

    return students[student_name]["wrong_questions"]


def analyzewrongquestions(student_name):
    """分析学生错题，找出优先复习知识点"""

    # 调用本文件中的错题查询函数
    records = getwrongquestions(student_name)

    # 情况1：没有该学生
    if isinstance(records, str):
        return {
            "status": "student_not_found",
            "message": records
        }

    # 情况2：有该学生，但是没有错题记录
    if len(records) == 0:
        return {
            "status": "no_recorded_wrong_questions",
            "student_name": student_name,
            "message": "当前没有已记录的错题，不能据此判断学生已经全部掌握"
        }

    # 情况3：统计每个知识点的错题数量
    topic_counts = {}

    for question in records:
        topic = question["topic"]

        if topic not in topic_counts:
            topic_counts[topic] = 1
        else:
            topic_counts[topic] += 1

    # 找出错题数量最多的知识点
    priority_topic = max(
        topic_counts,
        key=topic_counts.get
    )

    # 保存优先知识点对应的错题证据
    evidence_questions = []

    for question in records:
        if question["topic"] == priority_topic:
            evidence_questions.append({
                "question_id": question["question_id"],
                "mistake": question["mistake"]
            })

    return {
        "status": "success",
        "student_name": student_name,
        "total_wrong_questions": len(records),
        "topic_counts": topic_counts,
        "priority_topic": priority_topic,
        "evidence_questions": evidence_questions
    }