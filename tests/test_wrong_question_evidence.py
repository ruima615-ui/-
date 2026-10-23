import unittest
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.entities import (
    Course,
    Exam,
    ExamAnswer,
    ExamAttempt,
    Question,
    User,
    WrongQuestion,
)
from app.services.wrong_question_service import (
    get_course_wrong_question_details,
)


class WrongQuestionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        self.db.add_all([
            User(
                id="STUDENT_A",
                name="学生 A",
                role="student",
                status="active",
            ),
            User(
                id="STUDENT_B",
                name="学生 B",
                role="student",
                status="active",
            ),
            Course(
                id="COURSE_A",
                code="COURSE_A",
                name="课程 A",
                status="active",
            ),
            Course(
                id="COURSE_B",
                code="COURSE_B",
                name="课程 B",
                status="active",
            ),
        ])

        question_a = Question(
            id="QUESTION_A",
            difficulty="medium",
            knowledge_count_level=1,
            reasoning_level=1,
            transfer_level=1,
            distractor_level=1,
            difficulty_score=4,
            course_id="COURSE_A",
            question_type="single_choice",
            topic="Python列表",
            stem="Python 列表的第一个元素使用哪个索引？",
            options={"A": "0", "B": "1"},
            answer_key="A",
            explanation="Python 列表索引从 0 开始。",
            max_score=5.0,
        )
        question_b = Question(
            id="QUESTION_B",
            course_id="COURSE_B",
            question_type="true_false",
            topic="其他课程知识点",
            stem="其他课程题目",
            answer_key=True,
            explanation="其他课程解析",
            max_score=5.0,
        )
        self.db.add_all([question_a, question_b])

        exam_a = Exam(
            id="EXAM_A",
            course_id="COURSE_A",
            title="课程 A 考试",
            status="published",
            duration_minutes=30,
        )
        exam_b = Exam(
            id="EXAM_B",
            course_id="COURSE_B",
            title="课程 B 考试",
            status="published",
            duration_minutes=30,
        )
        self.db.add_all([exam_a, exam_b])
        self.db.flush()

        submitted_at = datetime(2026, 1, 1, 12, 0, 0)
        attempt_a = ExamAttempt(
            exam_id="EXAM_A",
            student_id="STUDENT_A",
            status="graded",
            total_score=0.0,
            submitted_at=submitted_at,
        )
        attempt_other_student = ExamAttempt(
            exam_id="EXAM_A",
            student_id="STUDENT_B",
            status="graded",
            total_score=0.0,
            submitted_at=submitted_at + timedelta(minutes=1),
        )
        attempt_other_course = ExamAttempt(
            exam_id="EXAM_B",
            student_id="STUDENT_A",
            status="graded",
            total_score=0.0,
            submitted_at=submitted_at + timedelta(minutes=2),
        )
        self.db.add_all([
            attempt_a,
            attempt_other_student,
            attempt_other_course,
        ])
        self.db.flush()

        self.db.add_all([
            ExamAnswer(
                exam_attempt_id=attempt_a.id,
                question_id="QUESTION_A",
                answer="B",
                grading_status="graded",
                is_correct=False,
                score=0.0,
            ),
            ExamAnswer(
                exam_attempt_id=attempt_other_student.id,
                question_id="QUESTION_A",
                answer="OTHER_STUDENT_ANSWER",
                grading_status="graded",
                is_correct=False,
                score=0.0,
            ),
            ExamAnswer(
                exam_attempt_id=attempt_other_course.id,
                question_id="QUESTION_B",
                answer=False,
                grading_status="graded",
                is_correct=False,
                score=0.0,
            ),
            WrongQuestion(
                student_id="STUDENT_A",
                course_id="COURSE_A",
                question_id="QUESTION_A",
                topic="Python列表",
                mistake="学生错误选择了 B。",
            ),
            WrongQuestion(
                student_id="STUDENT_A",
                course_id="COURSE_B",
                question_id="QUESTION_B",
                topic="其他课程知识点",
                mistake="其他课程错题。",
            ),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_details_include_complete_evidence_and_stay_isolated(self):
        result = get_course_wrong_question_details(
            db=self.db,
            student_id="STUDENT_A",
            course_id="COURSE_A",
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["student_id"], "STUDENT_A")
        self.assertEqual(result["course_id"], "COURSE_A")
        self.assertEqual(result["total_wrong_questions"], 1)

        evidence = result["wrong_questions"][0]
        self.assertEqual(evidence["question_id"], "QUESTION_A")
        self.assertEqual(evidence["topic"], "Python列表")
        self.assertEqual(evidence["question_type"], "single_choice")
        self.assertEqual(evidence["difficulty"], "medium")
        self.assertEqual(evidence["difficulty_score"], 4)
        self.assertEqual(
            evidence["stem"],
            "Python 列表的第一个元素使用哪个索引？",
        )
        self.assertEqual(evidence["options"], {"A": "0", "B": "1"})
        self.assertEqual(evidence["student_answer"], "B")
        self.assertEqual(evidence["correct_answer"], "A")
        self.assertEqual(
            evidence["explanation"],
            "Python 列表索引从 0 开始。",
        )
        self.assertEqual(evidence["mistake"], "学生错误选择了 B。")
        self.assertIsNotNone(evidence["recorded_at"])
        self.assertNotEqual(
            evidence["student_answer"],
            "OTHER_STUDENT_ANSWER",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
