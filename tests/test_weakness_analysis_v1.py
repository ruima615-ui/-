import unittest
from datetime import datetime, timedelta, timezone

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
    analyze_course_wrong_questions,
    calculate_difficulty_weight,
    calculate_recency_weight,
)


class WeaknessAnalysisV2Tests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        self.Session = sessionmaker(bind=self.engine)
        Base.metadata.create_all(self.engine)
        self.db = self.Session()

        self.now = datetime.now(
            timezone.utc
        ).replace(tzinfo=None)

        self.db.add(
            User(
                id="STUDENT_V1",
                name="第一版测试学生",
                role="student",
                status="active",
            )
        )
        self.db.add(
            Course(
                id="COURSE_V1",
                code="COURSE_V1",
                name="第一版测试课程",
                status="active",
            )
        )
        self.db.add_all([
            Question(
                id="LIST_Q1",
                difficulty="medium",
                knowledge_count_level=1,
                reasoning_level=1,
                transfer_level=1,
                distractor_level=1,
                difficulty_score=4,
                course_id="COURSE_V1",
                question_type="single_choice",
                topic="Python列表",
                stem="列表第一题",
                answer_key="A",
                max_score=5.0,
            ),
            Question(
                id="LIST_Q2",
                difficulty="medium",
                knowledge_count_level=1,
                reasoning_level=1,
                transfer_level=1,
                distractor_level=1,
                difficulty_score=4,
                course_id="COURSE_V1",
                question_type="single_choice",
                topic="Python列表",
                stem="列表第二题",
                answer_key="A",
                max_score=5.0,
            ),
        ])
        self.db.add_all([
            Exam(
                id="EXAM_V1_A",
                course_id="COURSE_V1",
                title="第一次考试",
                status="published",
                duration_minutes=30,
            ),
            Exam(
                id="EXAM_V1_B",
                course_id="COURSE_V1",
                title="第二次考试",
                status="published",
                duration_minutes=30,
            ),
        ])
        self.db.flush()

        first_attempt = ExamAttempt(
            exam_id="EXAM_V1_A",
            student_id="STUDENT_V1",
            status="graded",
            total_score=5.0,
            submitted_at=self.now - timedelta(days=3),
        )
        second_attempt = ExamAttempt(
            exam_id="EXAM_V1_B",
            student_id="STUDENT_V1",
            status="graded",
            total_score=0.0,
            submitted_at=self.now - timedelta(days=1),
        )
        self.db.add_all([
            first_attempt,
            second_attempt,
        ])
        self.db.flush()

        self.db.add_all([
            # LIST_Q1 在两次考试中都答错。
            ExamAnswer(
                exam_attempt_id=first_attempt.id,
                question_id="LIST_Q1",
                answer="B",
                grading_status="graded",
                is_correct=False,
                score=0.0,
            ),
            ExamAnswer(
                exam_attempt_id=second_attempt.id,
                question_id="LIST_Q1",
                answer="C",
                grading_status="graded",
                is_correct=False,
                score=0.0,
            ),
            # LIST_Q2 第一次答对，第二次答错。
            ExamAnswer(
                exam_attempt_id=first_attempt.id,
                question_id="LIST_Q2",
                answer="A",
                grading_status="graded",
                is_correct=True,
                score=5.0,
            ),
            ExamAnswer(
                exam_attempt_id=second_attempt.id,
                question_id="LIST_Q2",
                answer="B",
                grading_status="graded",
                is_correct=False,
                score=0.0,
            ),
            WrongQuestion(
                student_id="STUDENT_V1",
                course_id="COURSE_V1",
                question_id="LIST_Q1",
                topic="Python列表",
                mistake="两次考试都回答错误。",
            ),
            WrongQuestion(
                student_id="STUDENT_V1",
                course_id="COURSE_V1",
                question_id="LIST_Q2",
                topic="Python列表",
                mistake="第二次考试回答错误。",
            ),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_error_rate_and_repeated_wrong_question_counts(self):
        result = analyze_course_wrong_questions(
            db=self.db,
            student_id="STUDENT_V1",
            course_id="COURSE_V1",
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["analysis_version"], "v2")
        self.assertEqual(result["total_wrong_questions"], 2)
        self.assertEqual(result["total_wrong_attempts"], 3)
        self.assertEqual(result["total_attempts"], 4)
        self.assertEqual(result["priority_topic"], "Python列表")

        topic = result["topic_analysis"][0]
        self.assertEqual(topic["unique_wrong_questions"], 2)
        self.assertEqual(topic["wrong_attempts"], 3)
        self.assertEqual(topic["total_attempts"], 4)
        self.assertEqual(topic["error_rate"], 0.75)
        self.assertEqual(topic["recency_weight"], 1.0)
        self.assertEqual(
            topic["difficulty_distribution"],
            {
                "easy": 0,
                "medium": 3,
                "hard": 0,
            },
        )
        self.assertEqual(topic["difficulty_weight"], 0.6)
        self.assertEqual(topic["priority_score"], 0.77)
        self.assertEqual(topic["priority_level"], "high")
        self.assertEqual(topic["analysis_basis"], "exam_history")

    def test_difficulty_weight(self):
        cases = [
            ({"easy": 2, "medium": 0, "hard": 0}, 1.0),
            ({"easy": 0, "medium": 2, "hard": 0}, 0.6),
            ({"easy": 0, "medium": 0, "hard": 2}, 0.3),
            ({"easy": 1, "medium": 0, "hard": 1}, 0.65),
        ]

        for distribution, expected in cases:
            with self.subTest(distribution=distribution):
                self.assertEqual(
                    calculate_difficulty_weight(
                        wrong_attempts=2,
                        difficulty_distribution=distribution,
                    ),
                    expected,
                )

    def test_difficulty_distribution_must_match_wrong_attempts(self):
        with self.assertRaises(ValueError):
            calculate_difficulty_weight(
                wrong_attempts=3,
                difficulty_distribution={
                    "easy": 1,
                    "medium": 1,
                    "hard": 0,
                },
            )

    def test_difficulty_distribution_rejects_unknown_level(self):
        with self.assertRaises(ValueError):
            calculate_difficulty_weight(
                wrong_attempts=2,
                difficulty_distribution={
                    "easy": 1,
                    "medium": 0,
                    "hard": 0,
                    "unknown": 1,
                },
            )

    def test_recency_weight_boundaries(self):
        self.assertEqual(
            calculate_recency_weight(None, self.now),
            0.0,
        )
        self.assertEqual(
            calculate_recency_weight(
                self.now - timedelta(days=7),
                self.now,
            ),
            1.0,
        )
        self.assertEqual(
            calculate_recency_weight(
                self.now - timedelta(days=8),
                self.now,
            ),
            0.6,
        )
        self.assertEqual(
            calculate_recency_weight(
                self.now - timedelta(days=31),
                self.now,
            ),
            0.3,
        )
        self.assertEqual(
            calculate_recency_weight(
                self.now - timedelta(days=91),
                self.now,
            ),
            0.1,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
