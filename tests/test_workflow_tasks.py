from __future__ import annotations

import contextlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server import database
from server.celery_app import celery_app
from server.models import Base, users_table
from server import workflow_repository as repo
from server.workflow_tasks import (
    NODE_SOFT_TIME_LIMIT, NODE_TIME_LIMIT, _is_transient_error, dispatch_node,
    queue_for_node, run_workflow_node,
)


class WorkflowTaskChainTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{Path(self.temp.name, 'tasks.db').as_posix()}",
                                    connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        database.ENGINE = self.engine
        database.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.engine.begin() as connection:
            connection.execute(users_table.insert(), {"id": "task-user", "email": "task@example.com",
                "display_name": "Task", "password_hash": "x", "role": "user", "status": "active", "created_at": "2026"})
        celery_app.conf.task_always_eager = True
        celery_app.conf.task_eager_propagates = True
        self.patches = [
            patch("server.workflow_tasks.execute_node", side_effect=lambda workflow, node: {f"result_{node}": True}),
            patch("server.workflow_tasks.node_lock", side_effect=lambda *args, **kwargs: contextlib.nullcontext()),
            patch("server.workflow_tasks.notify"),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.engine.dispose()
        self.temp.cleanup()

    def create(self, mode, key):
        return repo.create_workflow("task-user", key, mode, {"topic": "test"})[0]

    def test_auto_mode_uses_all_shared_nodes_to_completion(self):
        workflow = self.create("auto", "auto-chain")
        dispatch_node(workflow["id"], "intent")
        final = repo.get_workflow(workflow["id"], "task-user")
        self.assertEqual("completed", final["status"])
        self.assertEqual(list(repo.NODES), final["state"]["completed_nodes"])

    def test_interactive_mode_pauses_and_resumes_same_engine(self):
        workflow = self.create("interactive", "interactive-chain")
        dispatch_node(workflow["id"], "intent")
        current = repo.get_workflow(workflow["id"], "task-user")
        self.assertEqual(("awaiting_input", "topic"), (current["status"], current["current_node"]))

        current = repo.record_decision(workflow["id"], "task-user", "topic", current["version"], {"selection": 1})
        dispatch_node(workflow["id"], "research")
        current = repo.get_workflow(workflow["id"], "task-user")
        self.assertEqual(("awaiting_input", "strategy"), (current["status"], current["current_node"]))

        current = repo.record_decision(workflow["id"], "task-user", "strategy", current["version"], {})
        dispatch_node(workflow["id"], "draft")
        current = repo.get_workflow(workflow["id"], "task-user")
        self.assertEqual(("awaiting_input", "visual"), (current["status"], current["current_node"]))

        repo.record_decision(workflow["id"], "task-user", "visual", current["version"], {})
        dispatch_node(workflow["id"], "delivery")
        final = repo.get_workflow(workflow["id"], "task-user")
        self.assertEqual("completed", final["status"])
        self.assertEqual(list(repo.NODES), final["state"]["completed_nodes"])

    def test_only_transient_failures_are_retried(self):
        self.assertTrue(_is_transient_error(TimeoutError("provider timeout")))
        self.assertTrue(_is_transient_error(RuntimeError("provider HTTP 503")))
        self.assertFalse(_is_transient_error(ValueError("invalid user selection")))

    def test_transient_node_retry_budget_is_bounded_but_tolerant(self):
        self.assertEqual(2, run_workflow_node.max_retries)
        self.assertEqual(300, NODE_SOFT_TIME_LIMIT)
        self.assertEqual(330, NODE_TIME_LIMIT)

    def test_recovery_task_uses_the_worker_queue(self):
        routes = celery_app.conf.task_routes
        self.assertEqual("workflow", routes["workflow.recover_stale"]["queue"])

    def test_workflow_nodes_use_scalable_queue_classes(self):
        self.assertEqual("chat", queue_for_node("intent"))
        self.assertEqual("text", queue_for_node("draft"))
        self.assertEqual("external", queue_for_node("research"))
        self.assertEqual("image", queue_for_node("visual"))
        self.assertEqual("workflow", queue_for_node("delivery"))
        with self.assertRaisesRegex(ValueError, "unknown workflow node"):
            queue_for_node("missing")


if __name__ == "__main__":
    unittest.main()
