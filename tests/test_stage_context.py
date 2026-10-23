"""每个阶段只带它需要的上下文，避免长对话把模型顶爆。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server import conversation_repository, database
from server.agent.context import stage_messages
from server.models import Base, users_table


class StageContextTests(unittest.TestCase):
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
