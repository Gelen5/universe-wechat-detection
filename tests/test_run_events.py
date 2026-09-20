from __future__ import annotations

import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server import conversation_repository as repo
from server import database
from server.models import AgentRun, Base, users_table


class RunEventRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        engine = create_engine(
            f"sqlite:///{Path(self.temp.name, 'events.db').as_posix()}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(engine)
        database.ENGINE = engine
        database.SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
        with engine.begin() as connection:
            connection.execute(users_table.insert(), [
                {"id": "user-a", "email": "a@example.com", "display_name": "A",
                 "password_hash": "x", "role": "user", "status": "active",
                 "created_at": "2026-01-01"},
                {"id": "user-b", "email": "b@example.com", "display_name": "B",
                 "password_hash": "x", "role": "user", "status": "active",
                 "created_at": "2026-01-01"},
            ])
        self.conversation = repo.create_conversation(
            "user-a", skill_id="wechat_writer", mode="manual")
        _, self.run, _ = repo.create_message_run(
            self.conversation["id"], "user-a", "写文章", "event-key")

    def tearDown(self):
        database.ENGINE.dispose()
        self.temp.cleanup()

    def test_events_are_durable_ordered_and_cursor_replayable(self):
        claimed = repo.claim_run(self.run["id"], "task-1")
        self.assertIsNotNone(claimed)
        repo.record_run_event(self.run["id"], "user-a", "assistant.thinking", {})
        repo.transition_run(self.run["id"], "user-a", "completed", task_id="task-1")

        events = repo.events_after(self.run["id"], "user-a")
        self.assertEqual(
            ["run.created", "run.queued", "run.started", "assistant.thinking", "run.completed"],
            [event["type"] for event in events],
        )
        self.assertEqual(sorted(event["id"] for event in events), [event["id"] for event in events])
        replay = repo.events_after(self.run["id"], "user-a", events[2]["id"])
        self.assertEqual(["assistant.thinking", "run.completed"], [event["type"] for event in replay])

    def test_events_are_owner_isolated(self):
        with self.assertRaises(KeyError):
            repo.events_after(self.run["id"], "user-b")
        with self.assertRaises(KeyError):
            repo.record_run_event(self.run["id"], "user-b", "assistant.thinking")

    def test_stale_run_recovery_is_visible_in_event_log(self):
        repo.claim_run(self.run["id"], "lost-task")
        with database.session_scope() as db:
            row = db.get(AgentRun, self.run["id"])
            row.heartbeat_at = row.heartbeat_at - timedelta(minutes=30)
        self.assertEqual([self.run["id"]], repo.recover_stale_runs(60))
        types = [event["type"] for event in repo.events_after(self.run["id"], "user-a")]
        self.assertEqual(["run.recovered", "run.queued"], types[-2:])


if __name__ == "__main__":
    unittest.main()
