from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from server import conversation_repository as repo
from server import database
from server.models import AgentRun, Base, ProviderCall, UsageRecord, users_table


class ConversationRepositoryTests(unittest.TestCase):
    def test_run_inputs_freeze_body_and_history_but_allow_completed_tool_outputs(self):
        conversation = repo.create_conversation('user-a')
        _, seed, _ = repo.create_message_run(conversation['id'], 'user-a', 'initial draft', 'input-seed')
        original = repo.create_artifact(seed['id'], 'user-a', 'article', content='Submitted body')
        trigger, run, _ = repo.create_message_run(conversation['id'], 'user-a', 'review this', 'input-freeze')
        repo.create_artifact_version(original['id'], 'user-a', content='Later human edit')
        repo.add_message(conversation['id'], 'user-a', 'user', 'Future unrelated request')
        inputs = repo.run_inputs(run['id'], 'user-a')
        self.assertEqual([original['id']], [row['id'] for row in inputs['artifacts']])
        self.assertEqual('review this', inputs['messages'][-1]['content'])
        self.assertNotIn('Future unrelated request', [row['content'] for row in inputs['messages']])
        tool, _ = repo.create_tool_call(run['id'], 'user-a', call_id='one', skill_id='wechat_writer',
                                      tool_name='review_article', arguments={})
        output = repo.create_artifact(run['id'], 'user-a', 'article', content='Worker result',
                                     source_key=tool['id'] + ':article:0')
        self.assertNotIn(output['id'], [row['id'] for row in repo.run_inputs(run['id'], 'user-a')['artifacts']])
        repo.finish_tool_call(tool['id'], run['id'], 'user-a', result={'saved': True})
        human = repo.create_artifact_version(output['id'], 'user-a', content='Another tab changed worker output')
        ids = [row['id'] for row in repo.run_inputs(run['id'], 'user-a')['artifacts']]
        self.assertIn(output['id'], ids)
        self.assertNotIn(human['id'], ids)
        replayed, _, replay = repo.create_message_run(conversation['id'], 'user-a', 'review this', 'input-freeze')
        self.assertTrue(replay)
        self.assertEqual(trigger['metadata'], replayed['metadata'])
        with self.assertRaises(KeyError):
            repo.run_inputs(run['id'], 'user-b')

    def test_empty_submission_snapshot_does_not_fall_back_to_future_artifacts(self):
        conversation = repo.create_conversation('user-a')
        _, run, _ = repo.create_message_run(conversation['id'], 'user-a', 'start', 'empty-snapshot')
        _, other, _ = repo.create_message_run(conversation['id'], 'user-a', 'later', 'later-snapshot')
        repo.create_artifact(other['id'], 'user-a', 'article', content='Must not enter old task')
        self.assertEqual([], repo.run_inputs(run['id'], 'user-a')['artifacts'])

    def test_activity_list_includes_only_owners_unfinished_runs(self):
        first = repo.create_conversation('user-a', title='First task')
        second = repo.create_conversation('user-a', title='Second task')
        other = repo.create_conversation('user-b', title='Private other task')
        _, one, _ = repo.create_message_run(first['id'], 'user-a', 'write', 'active-one')
        _, two, _ = repo.create_message_run(second['id'], 'user-a', 'write', 'active-two')
        repo.create_message_run(other['id'], 'user-b', 'write', 'other-task')
        self.assertEqual({one['id'], two['id']}, {row['id'] for row in repo.list_active_runs('user-a')})
        page = repo.list_active_runs('user-a', limit=1)
        older = repo.list_active_runs('user-a', limit=1, before=page[0]['id'])
        self.assertEqual({one['id'], two['id']}, {page[0]['id'], older[0]['id']})
        with self.assertRaises(ValueError):
            repo.list_active_runs('user-b', before=one['id'])
        repo.cancel_run(one['id'], 'user-a')
        active = repo.list_active_runs('user-a')
        self.assertEqual([two['id']], [row['id'] for row in active])
        self.assertEqual('Second task', active[0]['conversation_title'])

    def test_conflicting_editor_cannot_silently_overwrite_newer_version(self):
        conversation = repo.create_conversation('user-a')
        _, run, _ = repo.create_message_run(conversation['id'], 'user-a', 'write', 'edit-conflict')
        first = repo.create_artifact(run['id'], 'user-a', 'article', content='original')
        second = repo.create_artifact_version(first['id'], 'user-a', content='tab A', expected_current_id=first['id'])
        with self.assertRaises(repo.ArtifactVersionConflict):
            repo.create_artifact_version(first['id'], 'user-a', content='tab B', expected_current_id=first['id'])
        replay = repo.create_artifact_version(first['id'], 'user-a', content='tab A', expected_current_id=first['id'])
        self.assertEqual(second['id'], replay['id'])
        self.assertEqual(2, len(repo.list_artifacts(conversation['id'], 'user-a')))
        merged = repo.create_artifact_version(first['id'], 'user-a', content='merged', expected_current_id=second['id'])
        self.assertEqual(3, merged['version'])

    def test_request_lookup_is_scoped_to_owner_and_conversation(self):
        conversation = repo.create_conversation('user-a')
        other = repo.create_conversation('user-a')
        _, run, _ = repo.create_message_run(conversation['id'], 'user-a', 'write', 'lost-response-key')
        self.assertEqual(run['id'], repo.find_request_run(conversation['id'], 'user-a', 'lost-response-key')['id'])
        self.assertIsNone(repo.find_request_run(conversation['id'], 'user-b', 'lost-response-key'))
        self.assertIsNone(repo.find_request_run(other['id'], 'user-a', 'lost-response-key'))

    def test_workspace_pages_metadata_without_old_bodies_and_preserves_legacy_access(self):
        conversation = repo.create_conversation('user-a')
        _, run, _ = repo.create_message_run(conversation['id'], 'user-a', 'write', 'history-workspace')
        for index in range(7):
            repo.create_artifact(run['id'], 'user-a', 'article', content=f'{index}:' + 'x' * 10000)
        page = repo.artifact_workspace(conversation['id'], 'user-a', limit=2)
        self.assertEqual(7, page['total'])
        self.assertIsNotNone(page['next_cursor'])
        loaded = [item for item in page['artifacts'] if item['content_loaded']]
        self.assertEqual(1, len(loaded))
        self.assertEqual(7, loaded[0]['version'])
        old = next(item for item in page['artifacts'] if not item['content_loaded'])
        self.assertNotIn('content', old)
        self.assertNotIn('content_json', old)
        self.assertEqual(10002, len(repo.get_artifact(old['id'], 'user-a')['content']))
        seen = {item['id'] for item in page['artifacts']}
        while page['next_cursor']:
            page = repo.artifact_workspace(conversation['id'], 'user-a', limit=2, before=page['next_cursor'])
            seen.update(item['id'] for item in page['artifacts'])
        self.assertEqual(7, len(seen))
        self.assertEqual(7, len(repo.list_artifacts(conversation['id'], 'user-a')))
        with self.assertRaises(KeyError):
            repo.artifact_workspace(conversation['id'], 'user-b')
        with self.assertRaises(ValueError):
            repo.artifact_workspace(conversation['id'], 'user-a', before='unknown')

    def test_empty_metadata_cannot_bypass_idempotency_conflict(self):
        conversation = repo.create_conversation('user-a')
        repo.create_message_run(conversation['id'], 'user-a', 'write', 'metadata-key',
                                content_json={'workflow_stage': 'writing'})
        with self.assertRaises(repo.IdempotencyConflict):
            repo.create_message_run(conversation['id'], 'user-a', 'write', 'metadata-key',
                                    content_json={})

    def test_active_run_is_restored_from_server_and_owner_scoped(self):
        conversation = repo.create_conversation('user-a')
        _, run, _ = repo.create_message_run(conversation['id'], 'user-a', 'write', 'restore-key')
        self.assertEqual(run['id'], repo.get_conversation(conversation['id'], 'user-a')['active_run']['id'])
        self.assertIsNone(repo.get_conversation(conversation['id'], 'user-b'))
        repo.transition_run(run['id'], 'user-a', 'cancelled')
        self.assertIsNone(repo.get_conversation(conversation['id'], 'user-a')['active_run'])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        engine = create_engine(f"sqlite:///{Path(self.temp.name, 'conversation.db').as_posix()}",
                               connect_args={"check_same_thread": False})
        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

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

    def test_cancel_closes_active_tool_and_late_finish_cannot_reopen_it(self):
        conversation = repo.create_conversation('user-a')
        _, run, _ = repo.create_message_run(conversation['id'], 'user-a', 'review', 'cancel-tool-test')
        tool, _ = repo.create_tool_call(run['id'], 'user-a', call_id='call', skill_id='wechat_writer',
            tool_name='review_article', arguments={}, idempotency_key='cancel-tool')
        repo.cancel_run(run['id'], 'user-a')
        finished = repo.finish_tool_call(tool['id'], run['id'], 'user-a', error='late failure')
        self.assertEqual('cancelled', finished['status'])

    def test_failed_run_closes_tools_from_all_recovered_attempts(self):
        from server.models import ToolCall
        conversation = repo.create_conversation('user-a')
        _, run, _ = repo.create_message_run(conversation['id'], 'user-a', 'review', 'failed-tool-test')
        tools = [repo.create_tool_call(run['id'], 'user-a', call_id=str(i), skill_id='wechat_writer',
            tool_name='review_article', arguments={}, idempotency_key=f'failed-tool-{i}')[0]
            for i in range(2)]
        repo.transition_run(run['id'], 'user-a', 'failed', error_message='deadline exceeded')
        with database.session_scope() as db:
            for item in tools:
                tool = db.get(ToolCall, item['id'])
                self.assertEqual('failed', tool.status)
                self.assertIsNotNone(tool.finished_at)

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

    def test_long_history_returns_latest_window_in_chronological_order(self):
        from server.agent.context import conversation_messages, stage_messages

        conversation = repo.create_conversation("user-a")
        for index in range(205):
            repo.add_message(conversation["id"], "user-a", "user", f"message-{index}")
        history = repo.list_messages(conversation["id"], "user-a", limit=3)
        self.assertEqual([f"message-{index}" for index in range(202, 205)],
                         [item["content"] for item in history])
        generic = conversation_messages(conversation["id"], "user-a")
        self.assertEqual("message-204", generic[-1]["content"])
        self.assertEqual("message-165", generic[0]["content"])
        staged = stage_messages(conversation["id"], "user-a", stage="writing")
        self.assertEqual("message-204", staged[-1]["content"])
        self.assertEqual("message-193", staged[1]["content"])
        with self.assertRaises(KeyError):
            repo.list_messages(conversation["id"], "user-b", limit=3)

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

    def test_auto_conversation_does_not_prebind_new_run_to_previous_skill(self):
        conversation = repo.create_conversation("user-a", mode="auto")
        repo.bind_conversation_skill(conversation["id"], "user-a", "wechat_writer")
        _, run, _ = repo.create_message_run(
            conversation["id"], "user-a", "改做小红书", "auto-switch-skill",
        )
        self.assertIsNone(run["skill_id"])

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
