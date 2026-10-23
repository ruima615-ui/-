"""The same harness can run injected workflows without losing scope checks."""

import unittest
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.harness import AgentRuntimeHarness, EvaluationHarness
from app.models.entities import ChatSession, Course, Enrollment, User


class HarnessTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                               poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.sessions = sessionmaker(bind=engine)
        with self.sessions() as db:
            db.add_all([User(id="S1", name="甲", role="student", status="active"),
                        User(id="S2", name="乙", role="student", status="active"),
                        Course(id="C1", code="C1", name="课程", status="active")])
            db.flush()
            db.add_all([Enrollment(student_id="S1", course_id="C1"),
                        ChatSession(id="SESSION1", user_id="S1", course_id="C1")])
            db.commit()
        self.saved = []
        self.calls = []
        self.harness = AgentRuntimeHarness(
            session_factory=self.sessions,
            single_agent=SimpleNamespace(get_state=lambda config: None),
            load_context=lambda **kwargs: [{"role": "assistant", "content": "history"}],
            save_message=lambda **kwargs: self.saved.append(kwargs),
            run_single=lambda **kwargs: self._run("single", kwargs),
            run_multi=lambda **kwargs: self._run("multi", kwargs),
        )

    def _run(self, name, kwargs):
        self.calls.append((name, kwargs))
        return {"answer": "ok", "called_tools": [], "steps": 1, "tool_trace": []}

    def test_runtime_uses_same_scope_and_persists_only_successful_turn(self):
        with self.assertRaises(PermissionError):
            self.harness.run(user_id="S2", session_id="SESSION1", user_input="hi")
        self.assertEqual(self.calls, [])
        result = self.harness.run(user_id="S1", session_id="SESSION1", user_input="hi")
        self.assertEqual(result["answer"], "ok")
        self.assertEqual(self.calls[0][1]["messages"][-1], {"role": "user", "content": "hi"})
        self.assertEqual([row["role"] for row in self.saved], ["user", "assistant"])

    def test_multi_is_injected_without_single_checkpoint(self):
        result = self.harness.run(user_id="S1", session_id="SESSION1", user_input="plan",
                                  workflow="multi_agent_review")
        self.assertEqual(result["answer"], "ok")
        self.assertEqual(self.calls[0][0], "multi")

    def test_evaluation_captures_failure_and_checks(self):
        harness = EvaluationHarness(
            score=lambda case, result, error: {"completed": error is None},
            diagnose=lambda result, error, checks: {"stage": "invoke"} if error else None,
        )
        def fail():
            raise RuntimeError("failure")
        outcome = harness.run_case({"id": "one"}, fail)
        self.assertFalse(outcome.passed)
        self.assertEqual(outcome.failure_diagnostic, {"stage": "invoke"})
        self.assertEqual(type(outcome.error), RuntimeError)
        self.assertIsNone(outcome.token_usage)


if __name__ == "__main__":
    unittest.main()
