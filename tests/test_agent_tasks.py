from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server import conversation_repository, database
from server.agent_tasks import execute_agent_run
from server.celery_app import celery_app
from server.models import Base, users_table


class AgentTaskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        engine = create_engine(f"sqlite:///{Path(self.temp.name, 'agent-task.db').as_posix()}",
                               connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        database.ENGINE = engine
        database.SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
        with engine.begin() as connection:
            connection.execute(users_table.insert(), {"id": "user-a", "email": "a@example.com",
                "display_name": "A", "password_hash": "x", "role": "user", "status": "active", "created_at": "2026"})
        conversation = conversation_repository.create_conversation("user-a", mode="manual", skill_id="wechat_writer")
        message = conversation_repository.add_message(conversation["id"], "user-a", "user", "写文章")
        self.run, _ = conversation_repository.create_run(conversation["id"], "user-a", message["id"], "task-key")
        celery_app.conf.task_always_eager = True
        celery_app.conf.task_eager_propagates = True

    def tearDown(self):
        database.ENGINE.dispose()
        self.temp.cleanup()

    def test_duplicate_delivery_executes_once(self):
        orchestrator = Mock()
        orchestrator.execute.return_value = {"status": "completed"}
        with patch("server.agent_tasks._orchestrator_factory", return_value=orchestrator):
            first = execute_agent_run.apply(args=[self.run["id"]]).get()
            second = execute_agent_run.apply(args=[self.run["id"]]).get()
        self.assertEqual("completed", first["status"])
        self.assertEqual("ignored", second["status"])
        orchestrator.execute.assert_called_once()

    def test_chat_task_has_dedicated_queue(self):
        self.assertEqual("chat", celery_app.conf.task_routes["agent.run"]["queue"])


if __name__ == "__main__":
    unittest.main()
