"""Saved plan tasks are scoped to the owning student and plan message."""

import json
import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.sessions import (CompleteReviewTaskRequest, complete_review_task,
                              list_review_task_progress, plan_wrong_question)
from app.core.database import Base
from app.models.entities import ChatMessage, ChatSession, Course, User


class ReviewTaskProgressTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                               poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.owner = User(id="S1", name="甲", role="student", status="active")
        self.other = User(id="S2", name="乙", role="student", status="active")
        self.db.add_all([self.owner, self.other,
                         Course(id="C1", code="C1", name="课程", status="active")])
        self.db.flush()
        self.db.add(ChatSession(id="SESSION1", user_id="S1", course_id="C1", status="active"))
        self.db.flush()
        plan = {"scope": {"course_id": "C1"}, "review_tasks": [
            {"task_id": "T1", "self_check_questions": ["为什么？"]}],
            "wrong_question_evidence": [{"question_id": "Q1"}],
            "material_evidence": []}
        message = ChatMessage(session_id="SESSION1", role="assistant", content="plan",
                              metadata_json=json.dumps({"review_plan": plan}))
        self.db.add(message)
        self.db.commit()
        self.message_id = message.id

    def tearDown(self):
        self.db.close()

    def test_owner_can_complete_saved_task_and_other_student_cannot(self):
        response = complete_review_task("SESSION1", self.message_id, "T1",
            CompleteReviewTaskRequest(answers=["因为规则不同"]), self.db, self.owner)
        self.assertEqual(response["answers"], ["因为规则不同"])
        self.assertEqual(len(list_review_task_progress("SESSION1", self.db, self.owner)), 1)
        with self.assertRaises(HTTPException) as denied:
            complete_review_task("SESSION1", self.message_id, "T1",
                CompleteReviewTaskRequest(answers=["猜测"]), self.db, self.other)
        self.assertEqual(denied.exception.status_code, 403)
        with self.assertRaises(HTTPException) as missing:
            complete_review_task("SESSION1", self.message_id, "made-up",
                CompleteReviewTaskRequest(answers=["猜测"]), self.db, self.owner)
        self.assertEqual(missing.exception.status_code, 404)

    def test_evidence_requires_plan_membership(self):
        with self.assertRaises(HTTPException) as missing:
            plan_wrong_question("SESSION1", self.message_id, "Q2", self.db, self.owner)
        self.assertEqual(missing.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
