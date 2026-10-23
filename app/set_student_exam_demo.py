import json

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import (
    Course,
    Enrollment,
    Exam,
    ExamAttempt,
    Question,
    TeacherCourseAssignment,
    User,
    WrongQuestion,
)
from app.services.exam_attempt_service import (
    get_exam_result,
    start_exam,
    submit_exam,
)
from app.services.exam_service import (
    create_exam_draft,
    publish_exam,
)


STUDENT_ID = "TEST_STUDENT_001"
COURSE_ID = "TEST_COURSE_001"
ADMIN_ID = "DEMO_ADMIN_001"
TEACHER_ID = "DEMO_TEACHER_001"
EXAM_TITLE = "PYTHON101_DEMO_EXAM"


def ensure_demo_teacher_assignment(db):
    """准备演示教师及其课程授权。"""

    admin = db.get(User, ADMIN_ID)

    if admin is None:
        admin = User(
            id=ADMIN_ID,
            name="演示管理员",
            role="admin",
            status="active",
        )
        db.add(admin)

    teacher = db.get(User, TEACHER_ID)
    if teacher is None:
        teacher = User(
            id=TEACHER_ID,
            name="演示教师",
            role="teacher",
            status="active",
        )
        db.add(teacher)

    assignment = db.get(
        TeacherCourseAssignment,
        (TEACHER_ID, COURSE_ID),
    )
    if assignment is None:
        db.add(TeacherCourseAssignment(
            teacher_id=TEACHER_ID,
            course_id=COURSE_ID,
            assigned_by=ADMIN_ID,
        ))


def ensure_demo_questions(db):
    """为课程准备两个可以自动判分的题目。"""

    questions = [
        {
            "id": "DEMO_Q_LIST_INDEX",
            "question_type": "single_choice",
            "topic": "Python列表",
            "stem": "Python 列表的第一个元素使用哪个索引？",
            "options": {
                "A": "0",
                "B": "1",
                "C": "-1",
                "D": "列表长度",
            },
            "answer_key": "A",
            "explanation": (
                "Python 列表索引从 0 开始。"
            ),
        },
        {
            "id": "DEMO_Q_FUNCTION_RETURN",
            "question_type": "true_false",
            "topic": "函数返回值",
            "stem": (
                "在函数中调用 print()，"
                "等同于使用 return 返回结果。"
            ),
            "options": None,
            "answer_key": False,
            "explanation": (
                "print() 只负责显示内容，"
                "return 才会把结果返回给调用者。"
            ),
        },
    ]

    for data in questions:
        question = db.get(Question, data["id"])

        if question is None:
            db.add(Question(
                id=data["id"],
                course_id=COURSE_ID,
                question_type=data[
                    "question_type"
                ],
                topic=data["topic"],
                stem=data["stem"],
                options=data["options"],
                answer_key=data["answer_key"],
                explanation=data["explanation"],
                max_score=5.0,
            ))


def get_or_create_exam(db):
    """创建并发布演示考试，重复运行时复用旧考试。"""

    exam = db.scalar(
        select(Exam).where(
            Exam.course_id == COURSE_ID,
            Exam.title == EXAM_TITLE,
        )
    )

    if exam is None:
        created = create_exam_draft(
            db=db,
            teacher_id=TEACHER_ID,
            course_id=COURSE_ID,
            title=EXAM_TITLE,
            duration_minutes=30,
            items=[
                {
                    "question_id": (
                        "DEMO_Q_LIST_INDEX"
                    ),
                    "points": 5,
                },
                {
                    "question_id": (
                        "DEMO_Q_FUNCTION_RETURN"
                    ),
                    "points": 5,
                },
            ],
        )
        exam_id = created["exam_id"]

        publish_exam(
            db=db,
            teacher_id=TEACHER_ID,
            exam_id=exam_id,
        )

        return db.get(Exam, exam_id)

    if exam.status == "draft":
        publish_exam(
            db=db,
            teacher_id=TEACHER_ID,
            exam_id=exam.id,
        )
        db.refresh(exam)

    if exam.status != "published":
        raise ValueError(
            f"演示考试状态不可用：{exam.status}"
        )

    return exam


def submit_wrong_answers(db, exam):
    """让测试学生提交两个错误答案。"""

    attempt = db.scalar(
        select(ExamAttempt).where(
            ExamAttempt.exam_id == exam.id,
            ExamAttempt.student_id == STUDENT_ID,
        )
    )

    # 支持重复运行脚本。
    if (
        attempt is not None
        and attempt.status == "graded"
    ):
        return get_exam_result(
            db=db,
            student_id=STUDENT_ID,
            attempt_id=attempt.id,
        )

    started = start_exam(
        db=db,
        student_id=STUDENT_ID,
        exam_id=exam.id,
    )

    return submit_exam(
        db=db,
        student_id=STUDENT_ID,
        attempt_id=started["attempt_id"],
        answers=[
            {
                "question_id": (
                    "DEMO_Q_LIST_INDEX"
                ),
                # 正确答案为 A，故意选择 B。
                "answer": "B",
            },
            {
                "question_id": (
                    "DEMO_Q_FUNCTION_RETURN"
                ),
                # 正确答案为 False，故意选择 True。
                "answer": True,
            },
        ],
    )


def main():
    db = SessionLocal()

    try:
        student = db.get(User, STUDENT_ID)
        course = db.get(Course, COURSE_ID)
        enrollment = db.get(
            Enrollment,
            (STUDENT_ID, COURSE_ID),
        )

        if student is None:
            raise ValueError(
                f"学生不存在：{STUDENT_ID}"
            )

        if course is None:
            raise ValueError(
                f"课程不存在：{COURSE_ID}"
            )

        if enrollment is None:
            raise ValueError(
                "测试学生尚未选修测试课程"
            )

        ensure_demo_teacher_assignment(db)
        ensure_demo_questions(db)
        db.commit()

        exam = get_or_create_exam(db)
        result = submit_wrong_answers(db, exam)

        wrong_questions = db.scalars(
            select(WrongQuestion).where(
                WrongQuestion.student_id
                == STUDENT_ID,
                WrongQuestion.course_id
                == COURSE_ID,
            )
        ).all()

        print("考试结果：")
        print(json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            default=str,
        ))

        print("生成的错题：")
        print(json.dumps(
            [
                {
                    "question_id": item.question_id,
                    "topic": item.topic,
                    "mistake": item.mistake,
                }
                for item in wrong_questions
            ],
            ensure_ascii=False,
            indent=2,
        ))

    finally:
        db.close()


if __name__ == "__main__":
    main()
