from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server import database
from server.models import Base, users_table
from server.models import WorkflowNode
from server import workflow_repository as repo


class WorkflowRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        engine = create_engine(f"sqlite:///{Path(self.temp.name, 'workflow.db').as_posix()}",
                               connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        database.ENGINE = engine
        database.SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
        with engine.begin() as connection:
            connection.execute(users_table.insert(), [
                {"id": "user-a", "email": "a@example.com", "display_name": "A",
                 "password_hash": "x", "role": "user", "status": "active", "created_at": "2026-01-01"},
                {"id": "user-b", "email": "b@example.com", "display_name": "B",
                 "password_hash": "x", "role": "user", "status": "active", "created_at": "2026-01-01"},
            ])

    def tearDown(self):
        database.ENGINE.dispose()
        self.temp.cleanup()

    def create(self, key="request-key-1", mode="interactive"):
        return repo.create_workflow("user-a", key, mode, {"topic": "测试主题"})[0]

    def test_idempotent_creation(self):
        first, replay1 = repo.create_workflow("user-a", "same-request", "interactive", {})
        second, replay2 = repo.create_workflow("user-a", "same-request", "interactive", {})
        self.assertFalse(replay1)
        self.assertTrue(replay2)
        self.assertEqual(first["id"], second["id"])

    def test_owner_isolation(self):
        workflow = self.create()
        self.assertIsNone(repo.get_workflow(workflow["id"], "user-b"))

    def test_queue_is_idempotent(self):
        workflow = self.create()
        first = repo.queue_node(workflow["id"], "intent")
        second = repo.queue_node(workflow["id"], "intent")
        self.assertEqual(first["id"], second["id"])

    def test_duplicate_claim_is_rejected(self):
        workflow = self.create()
        repo.queue_node(workflow["id"], "intent")
        self.assertIsNotNone(repo.claim_node(workflow["id"], "intent", "task-1"))
        self.assertIsNone(repo.claim_node(workflow["id"], "intent", "task-2"))

    def test_completed_node_is_not_claimed_again(self):
        workflow = self.create()
        repo.queue_node(workflow["id"], "intent")
        repo.claim_node(workflow["id"], "intent", "task-1")
        repo.complete_node(workflow["id"], "intent", {"value": 1})
        self.assertIsNone(repo.claim_node(workflow["id"], "intent", "task-1"))

    def test_interactive_pause_and_decision(self):
        workflow = self.create()
        paused = repo.pause_workflow(workflow["id"], "topic")
        decided = repo.record_decision(workflow["id"], "user-a", "topic", paused["version"], {"selection": 2})
        self.assertEqual("queued", decided["status"])
        self.assertEqual(2, decided["state"]["decisions"]["topic"]["selection"])

    def test_stale_decision_is_rejected(self):
        workflow = self.create()
        paused = repo.pause_workflow(workflow["id"], "topic")
        with self.assertRaises(RuntimeError):
            repo.record_decision(workflow["id"], "user-a", "topic", paused["version"] - 1, {})

    def test_wrong_checkpoint_is_rejected(self):
        workflow = self.create()
        paused = repo.pause_workflow(workflow["id"], "topic")
        with self.assertRaises(ValueError):
            repo.record_decision(workflow["id"], "user-a", "visual", paused["version"], {})

    def test_event_replay_uses_monotonic_ids(self):
        workflow = self.create()
        repo.queue_node(workflow["id"], "intent")
        events = repo.events_after(workflow["id"], "user-a")
        replay = repo.events_after(workflow["id"], "user-a", events[0]["id"])
        self.assertTrue(replay)
        self.assertTrue(all(item["id"] > events[0]["id"] for item in replay))

    def test_cancel_queued_workflow_is_terminal(self):
        workflow = self.create()
        cancelled = repo.request_cancel(workflow["id"], "user-a")
        self.assertEqual("cancelled", cancelled["status"])
        self.assertTrue(cancelled["cancel_requested"])

    def test_cancel_does_not_cross_users(self):
        workflow = self.create()
        with self.assertRaises(KeyError):
            repo.request_cancel(workflow["id"], "user-b")

    def test_failed_workflow_creates_new_retry_attempt(self):
        workflow = self.create()
        repo.queue_node(workflow["id"], "intent")
        repo.claim_node(workflow["id"], "intent", "task-1")
        repo.fail_workflow(workflow["id"], "intent", "temporary")
        retried, node = repo.retry_failed(workflow["id"], "user-a")
        queued = repo.queue_node(workflow["id"], node)
        self.assertEqual("queued", retried["status"])
        self.assertEqual(2, queued["attempt"])

    def test_upstream_edit_invalidates_downstream_nodes(self):
        workflow = self.create()
        repo.queue_node(workflow["id"], "intent")
        repo.claim_node(workflow["id"], "intent", "task-1")
        current = repo.complete_node(workflow["id"], "intent", {"old": True})
        current = repo.pause_workflow(workflow["id"], "topic")
        edited = repo.invalidate_from(workflow["id"], "user-a", "topic", {"brief": "new"}, current["version"])
        self.assertEqual("queued", edited["status"])
        self.assertEqual("new", edited["state"]["brief"])
        self.assertEqual(["intent"], edited["state"]["completed_nodes"])

    def test_stale_running_node_is_recovered(self):
        workflow = self.create()
        repo.queue_node(workflow["id"], "intent")
        repo.claim_node(workflow["id"], "intent", "lost-task")
        with database.session_scope() as db:
            node = db.query(WorkflowNode).filter_by(workflow_id=workflow["id"]).one()
            node.heartbeat_at = datetime.now(timezone.utc) - timedelta(hours=3)
        recovered = repo.recover_stale_nodes(7200)
        self.assertEqual([(workflow["id"], "intent")], recovered)


if __name__ == "__main__":
    unittest.main()
