"""Regression tests for the runtime reliability findings D01-D10.

Each test pins one invariant that the static architecture review proved was
missing: an orphaned queued Run, a retried tool call that lost its result, a
lease that looked dead while the tool was alive, output written onto a dead
Run, unattributed provider spend, and an idempotency key that answers for a
different request.
"""
from __future__ import annotations

import tempfile
import time
import unittest
from datetime import timedelta
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from server import conversation_repository as repo
from server import database
from server.agent.tool_loop import _HeartbeatSupervisor, run_tool_loop
from server.models import AgentRun, Base, RunEvent, ToolCall, users_table
from server.providers import call_context


class _RuntimeReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        engine = create_engine(f"sqlite:///{Path(self.temp.name, 'runtime.db').as_posix()}",
                               connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(engine)
        database.ENGINE = engine
        database.SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
        with engine.begin() as connection:
            connection.execute(users_table.insert(), [
                {"id": "user-a", "email": "a@example.com", "display_name": "A",
                 "password_hash": "x", "role": "user", "status": "active",
                 "created_at": "2026-01-01"},
            ])

    def tearDown(self):
        database.ENGINE.dispose()
        self.temp.cleanup()

    # ---- helpers ---------------------------------------------------------
    def _running_run(self, key: str) -> tuple[dict, dict]:
        conversation = repo.create_conversation("user-a")
        message = repo.add_message(conversation["id"], "user-a", "user", "写文章")
        run, _ = repo.create_run(conversation["id"], "user-a", message["id"], key)
        repo.transition_run(run["id"], "user-a", "running")
        return conversation, run

    def _backdate_queued(self, run_id: str, seconds: int) -> None:
        with database.session_scope() as db:
            row = db.get(AgentRun, run_id)
            row.updated_at = repo._now() - timedelta(seconds=seconds)

    # ---- D01 -------------------------------------------------------------
    def test_orphaned_queued_run_is_redelivered_once_per_window(self):
        conversation = repo.create_conversation("user-a")
        _, run, _ = repo.create_message_run(
            conversation["id"], "user-a", "写文章", "queued-orphan")

        self.assertEqual("queued", run["status"])
        # A Run that was just committed is still inside the publish window.
        self.assertEqual([], repo.recover_orphaned_queued_runs())

        self._backdate_queued(run["id"], 900)
        self.assertEqual([run["id"]], repo.recover_orphaned_queued_runs())
        # Re-dispatch bumps updated_at, so the next pass cannot select it again.
        self.assertEqual([], repo.recover_orphaned_queued_runs())

        # Redelivery stays safe: only one attempt may claim the Run.
        self.assertIsNotNone(repo.claim_run(run["id"], "task-1"))
        self.assertIsNone(repo.claim_run(run["id"], "task-2"))

    def test_orphaned_recovery_ignores_running_and_terminal_runs(self):
        conversation = repo.create_conversation("user-a")
        _, run, _ = repo.create_message_run(
            conversation["id"], "user-a", "写文章", "queued-running")
        repo.transition_run(run["id"], "user-a", "running")
        self._backdate_queued(run["id"], 900)
        self.assertEqual([], repo.recover_orphaned_queued_runs())

    # ---- D03 -------------------------------------------------------------
    def test_retried_tool_call_keeps_the_successful_result(self):
        _, run = self._running_run("tool-retry")
        record, replay = repo.create_tool_call(
            run["id"], "user-a", call_id="call-1", skill_id="wechat_writer",
            tool_name="create_outline", arguments={"title": "测试"})
        self.assertFalse(replay)

        repo.finish_tool_call(record["id"], run["id"], "user-a", error="provider boom")
        with database.session_scope() as db:
            self.assertEqual("failed", db.get(ToolCall, record["id"]).status)

        # The same logical key is retried and succeeds on the second attempt.
        repo.finish_tool_call(record["id"], run["id"], "user-a",
                              result={"outline": ["第一步", "第二步"]})
        with database.session_scope() as db:
            row = db.get(ToolCall, record["id"])
            self.assertEqual("completed", row.status)
            self.assertEqual({"outline": ["第一步", "第二步"]}, row.result_json)
            types = [item.event_type for item in
                     db.query(RunEvent).filter(RunEvent.run_id == run["id"]).all()]
        self.assertIn("tool.failed", types)
        self.assertIn("tool.retry_succeeded", types)

    def test_terminal_tool_call_is_not_overwritten(self):
        _, run = self._running_run("tool-terminal")
        record, _ = repo.create_tool_call(
            run["id"], "user-a", call_id="call-2", skill_id="wechat_writer",
            tool_name="create_outline", arguments={"title": "测试"})
        repo.finish_tool_call(record["id"], run["id"], "user-a", result={"first": True})
        repo.finish_tool_call(record["id"], run["id"], "user-a", result={"second": True})
        with database.session_scope() as db:
            self.assertEqual({"first": True}, db.get(ToolCall, record["id"]).result_json)

    # ---- D05 -------------------------------------------------------------
    def test_artifact_is_refused_on_a_cancelled_run(self):
        conversation, run = self._running_run("artifact-fence")
        repo.transition_run(run["id"], "user-a", "cancelled")
        with self.assertRaises(RuntimeError):
            repo.create_artifact(run["id"], "user-a", "article", content="迟到结果")
        self.assertEqual([], repo.list_artifacts(conversation["id"], "user-a"))

    def test_tool_completion_is_ignored_after_the_run_is_cancelled(self):
        _, run = self._running_run("tool-fence")
        record, _ = repo.create_tool_call(
            run["id"], "user-a", call_id="call-3", skill_id="wechat_writer",
            tool_name="create_outline", arguments={"title": "测试"})
        repo.transition_run(run["id"], "user-a", "cancelled")
        repo.finish_tool_call(record["id"], run["id"], "user-a", result={"late": True})
        with database.session_scope() as db:
            row = db.get(ToolCall, record["id"])
            self.assertEqual("running", row.status)
            self.assertEqual({}, row.result_json)

    # ---- D04 -------------------------------------------------------------
    def test_heartbeat_supervisor_renews_while_a_tool_blocks(self):
        beats: list[float] = []

        def beat() -> bool:
            beats.append(time.monotonic())
            return True

        with _HeartbeatSupervisor(beat, interval=0.05) as supervisor:
            time.sleep(0.26)
        self.assertFalse(supervisor.lost)
        self.assertGreaterEqual(len(beats), 2)

    def test_heartbeat_supervisor_reports_a_lost_lease(self):
        with _HeartbeatSupervisor(lambda: False, interval=0.02) as supervisor:
            time.sleep(0.12)
        self.assertTrue(supervisor.lost)

    # ---- D06 -------------------------------------------------------------
    def test_call_context_attributes_nested_provider_calls(self):
        self.assertEqual({}, call_context.current())
        self.assertIsNone(call_context.remaining_seconds())
        deadline = time.monotonic() + 30
        with call_context.bind(run_id="run-1", user_id="user-a", idempotency_key="key-1",
                               deadline=deadline):
            context = call_context.current()
            self.assertEqual("run-1", context["run_id"])
            self.assertEqual("user-a", context["user_id"])
            self.assertEqual("key-1", context["idempotency_key"])
            self.assertGreater(call_context.remaining_seconds(), 0)
        # Leaving the block must not leak attribution into later work.
        self.assertEqual({}, call_context.current())

    # ---- D08 -------------------------------------------------------------
    def test_tool_loop_refuses_to_start_past_its_deadline(self):
        with self.assertRaises(TimeoutError):
            run_tool_loop(model_service=object(), messages=[], tools={}, run_id="run-1",
                          user_id="user-a", skill_id="wechat_writer", max_tool_calls=1,
                          timeout_seconds=0)


if __name__ == "__main__":
    unittest.main()
