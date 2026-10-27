"""每个阶段只带它需要的上下文，避免长对话把模型顶爆。"""
from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server import conversation_repository, database
from server.agent.context import stage_messages
from server.models import Base, users_table


class StageContextTests(unittest.TestCase):
    def test_writer_adapter_consumes_submitted_outline_after_later_edit(self):
        from server.skills.executor import ToolContext
        from vendor.skills.wechat_writer import adapter

        _, run, _ = conversation_repository.create_message_run(
            self.conversation['id'], 'user-a', 'Write this outline', 'adapter-pinned')
        outline = next(row for row in conversation_repository.list_artifacts(
            self.conversation['id'], 'user-a') if row['type'] == 'outline')
        conversation_repository.create_artifact_version(
            outline['id'], 'user-a', content='1. Future first\n2. Future second')
        context = ToolContext(
            user_id='user-a', conversation_id=self.conversation['id'], run_id=run['id'],
            skill_id='wechat_writer', tool_call_id='call', idempotency_key='call-key',
            storage=None, model_service=None, emit=lambda *_: None,
            is_cancelled=lambda: False, heartbeat=lambda: True, remaining_seconds=lambda: 60)
        with patch.object(adapter, 'with_provider', side_effect=lambda invoke: invoke()), \
             patch.object(adapter.workbench, '_draft', return_value='Saved article') as draft:
            adapter.create_tools()['write_article']({'title': 'Title'}, context)
        self.assertEqual(draft.call_args.args[1]['outline'], ['开头', '结尾'])

    def test_run_context_does_not_include_post_submission_changes(self):
        _, run, _ = conversation_repository.create_message_run(
            self.conversation['id'], 'user-a', 'Write from submitted outline', 'pinned-context')
        prior = next(row for row in conversation_repository.list_artifacts(self.conversation['id'], 'user-a') if row['type'] == 'outline')
        conversation_repository.create_artifact_version(prior['id'], 'user-a', content='Future outline must not be used')
        conversation_repository.add_message(self.conversation['id'], 'user-a', 'user', 'Unrelated later instruction')
        body = '\n'.join(row['content'] for row in stage_messages(
            self.conversation['id'], 'user-a', stage='writing', run_id=run['id']))
        self.assertIn('1. 开头', body)
        self.assertNotIn('Future outline', body)
        self.assertNotIn('Unrelated later instruction', body)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        engine = create_engine(f"sqlite:///{Path(self.temp.name, 'ctx.db').as_posix()}",
                               connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        database.ENGINE = engine
        database.SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
        with engine.begin() as connection:
            connection.execute(users_table.insert(), {
                "id": "user-a", "email": "a@example.com", "display_name": "A",
                "password_hash": "x", "role": "user", "status": "active",
                "created_at": "2026-01-01"})
        self.conversation = conversation_repository.create_conversation(
            "user-a", mode="manual", skill_id="wechat_writer")
        message = conversation_repository.add_message(
            self.conversation["id"], "user-a", "user", "写一篇 AI 的文章")
        self.run, _ = conversation_repository.create_run(
            self.conversation["id"], "user-a", message["id"], "k1")
        conversation_repository.create_artifact(
            self.run["id"], "user-a", "topic", title="选题",
            content="1. 方向甲", content_json={"topics": [{"title": "方向甲"}]})
        conversation_repository.create_artifact(
            self.run["id"], "user-a", "outline", title="大纲", content="1. 开头\n2. 结尾")
        conversation_repository.create_artifact(
            self.run["id"], "user-a", "article", title="正文", content="很长的正文" * 5000)
        conversation_repository.create_artifact(
            self.run["id"], "user-a", "html", title="排版", content="<html>" + "x" * 50000 + "</html>")

    def tearDown(self):
        database.ENGINE.dispose()
        self.temp.cleanup()

    def text(self, stage):
        messages = stage_messages(self.conversation["id"], "user-a", stage=stage)
        return "\n".join(item["content"] for item in messages)

    def test_writing_gets_the_outline_not_the_article(self):
        body = self.text("writing")
        self.assertIn("1. 开头", body)
        self.assertNotIn("很长的正文", body)
        self.assertNotIn("<html>", body)

    def test_typeset_gets_a_short_excerpt_only(self):
        body = self.text("typeset")
        self.assertIn("正文", body)
        self.assertLess(len(body), 12000)

    def test_topic_gets_no_artifact_dump(self):
        body = self.text("topic")
        self.assertNotIn("1. 开头", body)
        self.assertNotIn("很长的正文", body)

    def test_long_history_is_trimmed(self):
        for index in range(30):
            conversation_repository.add_message(
                self.conversation["id"], "user-a", "user", f"第 {index} 条" + "呀" * 1000)
        messages = stage_messages(self.conversation["id"], "user-a", stage="writing")
        self.assertLessEqual(len([m for m in messages if m["role"] != "system"]), 12)
        self.assertTrue(all(len(m["content"]) <= 900 for m in messages))


if __name__ == "__main__":
    unittest.main()
