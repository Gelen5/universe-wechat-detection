from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server import conversation_repository as repo
from server import database
from server.models import AgentRun, Base, ProviderCall, UsageRecord, users_table


class ConversationRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        engine = create_engine(f"sqlite:///{Path(self.temp.name, 'conversation.db').as_posix()}",
                               connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        database.ENGINE = engine
        database.SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
        with engine.begin() as connection:
            connection.execute(users_table.insert(), [
                {"id": "user-a", "email": "a@example.com", "display_name": "A", "password_hash": "x",
                 "role": "user", "status": "active", "created_at": "2026-01-01"},
                {"id": "user-b", "email": "b@example.com", "display_name": "B", "password_hash": "x",
                 "role": "user", "status": "active", "created_at": "2026-01-01"},
            ])

    def tearDown(self):
        database.ENGINE.dispose()
        self.temp.cleanup()

    def test_manual_conversation_requires_skill(self):
        with self.assertRaises(ValueError):
            repo.create_conversation("user-a", mode="manual")

    def test_history_is_persistent_and_owner_isolated(self):
        conversation = repo.create_conversation("user-a", skill_id="wechat_writer", mode="manual")
        first = repo.add_message(conversation["id"], "user-a", "user", "第三个")
        repo.add_message(conversation["id"], "user-a", "assistant", "收到")
        self.assertEqual(["第三个", "收到"], [m["content"] for m in repo.list_messages(conversation["id"], "user-a")])
        self.assertEqual("user", first["role"])
        self.assertIsNone(repo.get_conversation(conversation["id"], "user-b"))
        with self.assertRaises(KeyError):
            repo.list_messages(conversation["id"], "user-b")

    def test_run_creation_is_idempotent_per_user(self):
        conversation = repo.create_conversation("user-a", skill_id="wechat_writer", mode="manual")
        message = repo.add_message(conversation["id"], "user-a", "user", "写文章")
        first, replay1 = repo.create_run(conversation["id"], "user-a", message["id"], "same-key")
        second, replay2 = repo.create_run(conversation["id"], "user-a", message["id"], "same-key")
        self.assertFalse(replay1)
        self.assertTrue(replay2)
        self.assertEqual(first["id"], second["id"])

    def test_new_input_replaces_waiting_run_and_refunds_its_reservation(self):
        conversation = repo.create_conversation("user-a")
        first_message, first_run, _ = repo.create_message_run(
            conversation["id"], "user-a", "帮我处理一下", "waiting-first",
        )
        self.assertEqual("user", first_message["role"])
        repo.transition_run(first_run["id"], "user-a", "waiting_input")
        _, second_run, replay = repo.create_message_run(
            conversation["id"], "user-a", "我要写公众号文章", "waiting-follow-up",
        )
        self.assertFalse(replay)
        self.assertEqual("cancelled", repo.get_run(first_run["id"], "user-a")["status"])
        self.assertEqual("queued", second_run["status"])
        with database.session_scope() as db:
            usage = {row.run_id: row.status for row in db.query(UsageRecord).all()}
        self.assertEqual("refunded", usage[first_run["id"]])
        self.assertEqual("reserved", usage[second_run["id"]])

    def test_artifact_versions_increment_without_overwrite(self):
        conversation = repo.create_conversation("user-a")
        message = repo.add_message(conversation["id"], "user-a", "user", "写文章")
        run, _ = repo.create_run(conversation["id"], "user-a", message["id"], "run-1")
        v1 = repo.create_artifact(run["id"], "user-a", "article", content="第一版")
        v2 = repo.create_artifact(run["id"], "user-a", "article", content="第二版")
        self.assertEqual((1, 2), (v1["version"], v2["version"]))
        self.assertEqual("第一版", v1["content"])
        v3 = repo.create_artifact_version(v2["id"], "user-a", content="第三版")
        self.assertEqual(3, v3["version"])
        self.assertEqual(
            ["第一版", "第二版", "第三版"],
            [item["content"] for item in repo.list_artifact_versions(v1["id"], "user-a")],
        )
        with self.assertRaises(KeyError):
            repo.create_artifact_version(v1["id"], "user-b", content="越权")

    def test_artifact_source_key_makes_tool_replay_idempotent(self):
        conversation = repo.create_conversation("user-a")
        message = repo.add_message(conversation["id"], "user-a", "user", "写文章")
        run, _ = repo.create_run(conversation["id"], "user-a", message["id"], "artifact-replay")
        first = repo.create_artifact(
            run["id"], "user-a", "article", content="第一份结果", source_key="tool-1:article:0",
        )
        replay = repo.create_artifact(
            run["id"], "user-a", "article", content="重复投递结果", source_key="tool-1:article:0",
        )
        self.assertEqual(first["id"], replay["id"])
        self.assertEqual("第一份结果", replay["content"])
        self.assertEqual(1, len(repo.list_artifacts(conversation["id"], "user-a")))

    def test_provider_cost_is_attributed_to_run_and_user(self):
        conversation = repo.create_conversation("user-a")
        message = repo.add_message(conversation["id"], "user-a", "user", "写文章")
        run, _ = repo.create_run(conversation["id"], "user-a", message["id"], "run-cost")
        repo.record_provider_call(run["id"], "user-a", provider="compatible", model="text-model",
                                  input_tokens=100, output_tokens=50, estimated_cost_micros=1234)
        with database.session_scope() as db:
            saved_run = db.get(AgentRun, run["id"])
            call = db.query(ProviderCall).one()
            self.assertEqual(1234, saved_run.provider_cost_micros)
            self.assertEqual("user-a", call.user_id)
        with self.assertRaises(KeyError):
            repo.record_provider_call(run["id"], "user-b", provider="x", model="y")

    def test_agent_metrics_report_runs_skills_and_latency_shape(self):
        conversation = repo.create_conversation("user-a", skill_id="wechat_writer", mode="manual")
        message = repo.add_message(conversation["id"], "user-a", "user", "写文章")
        run, _ = repo.create_run(conversation["id"], "user-a", message["id"], "metrics-run")
        repo.transition_run(run["id"], "user-a", "running")
        repo.transition_run(run["id"], "user-a", "completed")
        metrics = repo.agent_metrics()
        self.assertEqual(1, metrics["runs"])
        self.assertEqual(1, metrics["completed_runs"])
        self.assertEqual(1, metrics["skills"]["wechat_writer"]["completed"])
        self.assertIn("p95", metrics["latency_ms"])


if __name__ == "__main__":
    unittest.main()
