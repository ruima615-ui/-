import json
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.sessions import _load_message_metadata
from app.core.database import Base
from app.models.entities import ChatSession
from app.models.entities import User
from app.repositories.conversation_repository import (
    add_chat_message,
    get_recent_chat_messages,
)
from app.schemas.message import MessageResponse
from tests.test_review_plan_schema import (
    build_valid_review_plan,
)


class ChatMessageMetadataTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.db.add(User(
            id="SYNTHETIC_STUDENT",
            name="合成学生",
            role="student",
            status="active",
        ))
        self.db.add(ChatSession(
            id="SYNTHETIC_SESSION",
            user_id="SYNTHETIC_STUDENT",
            title="合成历史会话",
            status="active",
        ))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_review_plan_metadata_survives_database_reload(self):
        metadata = {
            "called_tools": [
                "finalize_current_course_review_plan"
            ],
            "steps": 4,
            "review_plan": build_valid_review_plan(),
        }
        add_chat_message(
            db=self.db,
            session_id="SYNTHETIC_SESSION",
            role="assistant",
            content="复习计划已经生成。",
            metadata_json=json.dumps(
                metadata,
                ensure_ascii=False,
            ),
        )

        stored = get_recent_chat_messages(
            db=self.db,
            session_id="SYNTHETIC_SESSION",
        )[0]
        restored = _load_message_metadata(
            stored.metadata_json
        )
        response = MessageResponse(
            message_id=stored.id,
            session_id=stored.session_id,
            role=stored.role,
            content=stored.content,
            called_tools=restored["called_tools"],
            steps=restored["steps"],
            review_plan=restored["review_plan"],
            created_at=stored.created_at,
        )

        self.assertEqual(response.steps, 4)
        self.assertEqual(
            response.review_plan.status,
            "success",
        )
        self.assertEqual(
            response.review_plan.review_tasks[0].topic,
            metadata["review_plan"]["review_tasks"][0]["topic"],
        )

    def test_invalid_metadata_is_ignored(self):
        self.assertEqual(
            _load_message_metadata("not-json"),
            {},
        )


if __name__ == "__main__":
    unittest.main()
