from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server import conversation_repository, database
from server.agent.orchestrator import AgentOrchestrator
from server.integrations.easel.native.catalog import APPROVED_TEXT_SKILLS
from server.models import Base, UsageRecord, Wallet, users_table
from server.providers import ModelProvider, ModelService, ProviderResponse
from server.skills.registry import DEFAULT_ROOT, SkillRegistry


class TextProvider(ModelProvider):
    def __init__(self):
        self.calls = []

    def create_response(self, messages, **kwargs):
        self.calls.append(messages)
        return ProviderResponse(text="Easel Native 完成")

    def generate_image(self, prompt, **kwargs):
        raise AssertionError("text-only Easel Skills must not generate images")


class NativeWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        engine = create_engine(f"sqlite:///{(Path(self.temp.name) / 'native.db').as_posix()}",
                               connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        database.ENGINE = engine
        database.SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
        with engine.begin() as connection:
            connection.execute(users_table.insert(), {"id": "native-user", "email": "native@example.com",
                "display_name": "Native", "password_hash": "x", "role": "user", "status": "active",
                "created_at": "2026-01-01"})
        with database.session_scope() as db:
            db.add(Wallet(user_id="native-user", balance=200, trial_balance=200,
                          bonus_balance=0, paid_balance=0, updated_at="2026-01-01"))

    def tearDown(self):
        database.ENGINE.dispose()
        self.temp.cleanup()

    def test_ten_text_skills_use_universe_run_artifact_and_billing(self):
        with patch.dict("os.environ", {"EASEL_NATIVE_ENABLED": "1"}):
            registry = SkillRegistry((DEFAULT_ROOT,)).reload()
        provider = TextProvider()
        service = ModelService(provider)
        orchestrator = AgentOrchestrator(registry=registry, model_service=service,
                                          tool_resolver=lambda *_: {})
        for name in APPROVED_TEXT_SKILLS:
            skill_id = "easel_" + name.replace("-", "_")
            conversation = conversation_repository.create_conversation(
                "native-user", mode="manual", skill_id=skill_id,
                metadata={"profile": {"audience": "公众号读者"}},
            )
            _, run, replay = conversation_repository.create_message_run(
                conversation["id"], "native-user", "写一段内容", f"native-{name}-request",
                reserve_points=10, feature=name,
            )
            self.assertFalse(replay)
            result = orchestrator.execute(run["id"], "native-user")
            self.assertEqual(result["status"], "completed", name)
            artifacts = conversation_repository.list_artifacts(conversation["id"], "native-user")
            self.assertEqual(artifacts[-1]["content"], "Easel Native 完成", name)
        self.assertEqual(len(provider.calls), 10)
        self.assertTrue(any("公众号读者" in item["content"] for item in provider.calls[0]))
        with database.session_scope() as db:
            usage = db.query(UsageRecord).filter_by(user_id="native-user").all()
            wallet = db.get(Wallet, "native-user")
            self.assertEqual(10, len(usage))
            self.assertEqual(100, wallet.balance)


if __name__ == "__main__":
    unittest.main()
