"""版本化评测证据：加载、校验与指纹。"""

import hashlib
import json
from pathlib import Path
from datetime import datetime

from app.models.entities import (
    ChatSession, Course, Enrollment, Exam, ExamAnswer, ExamAttempt,
    ExamQuestion, Question, User, WrongQuestion,
)


DATASET_PATH = Path(__file__).resolve().parent / "fixtures" / "student_agent_dataset_v1.json"


def load_dataset(path=DATASET_PATH):
    raw = Path(path).read_bytes()
    data = json.loads(raw)
    if data.get("dataset_id") not in {"student-agent-synthetic-v1", "student-agent-synthetic-v2",
                                       "student-agent-synthetic-v3"}:
        raise ValueError("评测集版本不受支持")
    students = {row["id"] for row in data["students"]}
    courses = {row["id"] for row in data["courses"]}
    questions = {row["id"]: row for row in data["questions"]}
    exams = {row["id"]: row for row in data["exams"]}
    memberships = {(row["student_id"], row["course_id"]) for row in data["enrollments"]}
    if len(students) != len(data["students"]) or len(courses) != len(data["courses"]):
        raise ValueError("学生或课程 ID 重复")
    if len(questions) != len(data["questions"]) or len(exams) != len(data["exams"]):
        raise ValueError("题目或试卷 ID 重复")
    if len(memberships) != len(data["enrollments"]):
        raise ValueError("选课关系重复")
    for student_id, course_id in memberships:
        if student_id not in students or course_id not in courses:
            raise ValueError("选课关系引用了不存在的学生或课程")
    for question in questions.values():
        if question["course_id"] not in courses:
            raise ValueError("题目引用了不存在的课程")
        if question["answer_key"] not in question["options"]:
            raise ValueError("题目标准答案不在选项中")
    for exam in exams.values():
        if exam["course_id"] not in courses or len(set(exam["question_ids"])) != len(exam["question_ids"]):
            raise ValueError("试卷课程无效或题目重复")
        if not exam["question_ids"] or any(
            qid not in questions or questions[qid]["course_id"] != exam["course_id"]
            for qid in exam["question_ids"]
        ):
            raise ValueError("试卷题目不存在或跨课程")
    wrong_answers = set()
    for attempt in data["attempts"]:
        exam = exams[attempt["exam_id"]]
        student_id = attempt["student_id"]
        if (student_id, exam["course_id"]) not in memberships:
            raise ValueError("考试作答学生未选该课程")
        if len({a["question_id"] for a in attempt["answers"]}) != len(attempt["answers"]):
            raise ValueError("一次考试有重复作答")
        for answer in attempt["answers"]:
            qid = answer["question_id"]
            if qid not in exam["question_ids"]:
                raise ValueError("作答题目不属于试卷")
            question = questions[qid]
            if answer["answer"] not in question["options"]:
                raise ValueError("作答选项不存在")
            correct = answer["answer"] == question["answer_key"]
            if answer["is_correct"] != correct:
                raise ValueError("作答对错与标准答案不一致")
            if not correct:
                wrong_answers.add((student_id, exam["course_id"], qid))
    wrong_rows = {(w["student_id"], w["course_id"], w["question_id"])
                  for w in data["wrong_questions"]}
    if len(wrong_rows) != len(data["wrong_questions"]) or wrong_rows != wrong_answers:
        raise ValueError("错题表必须与错误考试作答一一对应")
    for row in data["wrong_questions"]:
        if row["topic"] != questions[row["question_id"]]["topic"]:
            raise ValueError("错题知识点与题目不一致")
    material_ids, chunk_ids = set(), set()
    for material in data["materials"]:
        if material["material_id"] in material_ids or material["course_id"] not in courses:
            raise ValueError("资料 ID 重复或课程不存在")
        material_ids.add(material["material_id"])
        positions = set()
        for chunk in material["chunks"]:
            if (chunk["chunk_id"] in chunk_ids or chunk["position"] in positions
                    or not chunk["content"].strip()):
                raise ValueError("资料片段 ID/位置重复或正文为空")
            chunk_ids.add(chunk["chunk_id"])
            positions.add(chunk["position"])
    return data, hashlib.sha256(raw).hexdigest()


def seed_fixture(session_factory, cases, dataset):
    submitted_at = datetime.fromisoformat(dataset["submitted_at"])
    with session_factory() as db:
        for student in dataset["students"]:
            db.add(User(id=student["id"], name=student["name"], role="student",
                        status="active", created_at=submitted_at))
        for course in dataset["courses"]:
            db.add(Course(id=course["id"], code=course["code"], name=course["name"],
                          status="active", created_at=submitted_at))
        for enrollment in dataset["enrollments"]:
            db.add(Enrollment(**enrollment, enrolled_at=submitted_at))
        for question in dataset["questions"]:
            db.add(Question(
                id=question["id"], course_id=question["course_id"],
                question_type=question["type"], topic=question["topic"],
                difficulty=question["difficulty"], knowledge_count_level=1, reasoning_level=0,
                transfer_level=0, distractor_level=0, difficulty_score=1,
                stem=question["stem"], options=question["options"],
                answer_key=question["answer_key"], explanation=question["explanation"],
                max_score=1.0, created_at=submitted_at,
            ))
        for exam in dataset["exams"]:
            db.add(Exam(id=exam["id"], course_id=exam["course_id"], title=exam["title"],
                        status="published", duration_minutes=30, created_at=submitted_at))
            for position, qid in enumerate(exam["question_ids"], 1):
                db.add(ExamQuestion(exam_id=exam["id"], question_id=qid,
                                    position=position, points=1.0))
        for item in dataset["attempts"]:
            attempt = ExamAttempt(exam_id=item["exam_id"], student_id=item["student_id"],
                                  status="graded", total_score=sum(a["score"] for a in item["answers"]),
                                  submitted_at=submitted_at)
            db.add(attempt)
            db.flush()
            for answer in item["answers"]:
                db.add(ExamAnswer(exam_attempt_id=attempt.id, question_id=answer["question_id"],
                                  answer=answer["answer"], grading_status="graded",
                                  is_correct=answer["is_correct"], score=answer["score"]))
        for wrong in dataset["wrong_questions"]:
            db.add(WrongQuestion(**wrong, created_at=submitted_at))
        for case in cases:
            db.add(ChatSession(id=f"SESSION_EVAL_{case['id']}",
                               user_id=case.get("session_owner", case["student_id"]),
                               course_id=case.get("course_id", "C_EVAL_MAIN"), status="active"))
        db.commit()


def material_search(*, course_id, topic, query, mode="success", dataset):
    if mode == "unavailable":
        return {"status": "course_materials_not_configured", "course_id": course_id,
                "message": "当前课程尚未配置学习资料"}
    materials = [m for m in dataset["materials"] if m["course_id"] == course_id]
    if not materials:
        return {"status": "course_materials_not_configured", "course_id": course_id}
    normalized_topic = "".join(topic.split()).lower()
    matched = [m for m in materials if normalized_topic in "".join(m["topic"].split()).lower()
               or "".join(m["topic"].split()).lower() in normalized_topic]
    if not matched:
        return {"status": "topic_not_found", "course_id": course_id, "topic": topic}
    chunks = [{"chunk_id": chunk["chunk_id"], "position": chunk["position"],
               "material_id": m["material_id"], "topic": m["topic"],
               "original_filename": m["original_filename"], "content": chunk["content"]}
              for m in matched for chunk in m["chunks"]]
    return {"status": "success", "course_id": course_id, "topic": topic,
            "source": "synthetic_course_material", "retrieved_chunks": chunks}


def material_chunk(*, course_id, chunk_id, topic=None, dataset):
    for material in dataset["materials"]:
        if material["course_id"] != course_id:
            continue
        for chunk in material["chunks"]:
            if chunk["chunk_id"] == chunk_id:
                return {"status": "success", "course_id": course_id,
                        "material_id": material["material_id"], "topic": material["topic"],
                        "original_filename": material["original_filename"], **chunk}
    return {"status": "chunk_not_found", "course_id": course_id}


