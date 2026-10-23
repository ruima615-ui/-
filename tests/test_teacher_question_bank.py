import unittest

from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.entities import Course, Question, TeacherCourseAssignment, User
from app.schemas.question import CreateQuestionRequest
from app.services.question_service import import_teacher_questions, list_teacher_questions
from app.services.exam_service import (
    create_exam_draft, publish_exam, list_teacher_exams, get_teacher_exam_detail,
)
from frontend.question_import import parse_questions_csv


class TeacherQuestionBankTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.db.add_all([
            User(id="T1", name="授权教师", role="teacher", status="active"),
            User(id="T2", name="未授权教师", role="teacher", status="active"),
            User(id="A1", name="管理员", role="admin", status="active"),
            Course(id="C1", code="C1", name="课程", status="active"),
            TeacherCourseAssignment(teacher_id="T1", course_id="C1", assigned_by="A1"),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def item(self, **changes):
        data = dict(course_id="C1", question_type="single_choice", topic="列表", stem="首个下标？",
                    options={"A": "0", "B": "1"}, answer_key="A", explanation="从零开始")
        data.update(changes)
        return CreateQuestionRequest(**data)

    def test_import_select_draft_and_publish(self):
        result = import_teacher_questions(self.db, "T1", "C1", [self.item(), self.item(stem="第二题")])
        self.assertEqual(result["count"], 2)
        listed = list_teacher_questions(self.db, "T1", "C1")
        self.assertEqual({row["question_id"] for row in listed}, set(result["question_ids"]))
        draft = create_exam_draft(self.db, "T1", "C1", "期末卷", 30,
                                  [{"question_id": item, "points": index + 1}
                                   for index, item in enumerate(result["question_ids"])])
        self.assertEqual(publish_exam(self.db, "T1", draft["exam_id"])["status"], "published")

    def test_invalid_item_rejects_entire_batch(self):
        with self.assertRaisesRegex(ValueError, "第 2 道题"):
            import_teacher_questions(self.db, "T1", "C1", [self.item(), self.item(answer_key="C")])
        self.assertEqual(self.db.scalar(select(func.count()).select_from(Question)), 0)

    def test_unassigned_teacher_cannot_read_or_import(self):
        with self.assertRaises(PermissionError):
            list_teacher_questions(self.db, "T2", "C1")
        with self.assertRaises(PermissionError):
            import_teacher_questions(self.db, "T2", "C1", [self.item()])

    def test_csv_parser(self):
        csv_data = ('question_type,topic,stem,options,answer_key\n'
                    'true_false,布尔,真或假,,true\n').encode("utf-8-sig")
        self.assertIs(parse_questions_csv(csv_data, "C1")[0]["answer_key"], True)

    def test_draft_can_be_reopened_from_database(self):
        question_id = import_teacher_questions(self.db, "T1", "C1", [self.item()])["question_ids"][0]
        exam_id = create_exam_draft(self.db, "T1", "C1", "可恢复草稿", 45,
                                    [{"question_id": question_id, "points": 3}])["exam_id"]
        self.db.expire_all()
        self.assertEqual(list_teacher_exams(self.db, "T1", "C1")[0]["exam_id"], exam_id)
        detail = get_teacher_exam_detail(self.db, "T1", exam_id)
        self.assertEqual(detail["questions"][0]["answer_key"], "A")
        self.assertEqual(detail["questions"][0]["points"], 3)
        with self.assertRaises(PermissionError):
            get_teacher_exam_detail(self.db, "T2", exam_id)
        self.assertEqual(publish_exam(self.db, "T1", exam_id)["status"], "published")
        self.assertEqual(get_teacher_exam_detail(self.db, "T1", exam_id)["status"], "published")


if __name__ == "__main__":
    unittest.main()
