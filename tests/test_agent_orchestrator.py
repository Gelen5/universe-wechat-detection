from __future__ import annotations

import base64
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server import conversation_repository, database
from server.agent.orchestrator import AgentOrchestrator
from server.agent.router import SkillRouter
from server.agent.tool_loop import ExecutableTool, run_tool_loop
from server.models import Base, ToolCall, users_table
from server.providers import ModelProvider, ModelService, ProviderResponse, ToolInvocation
from server.skills.registry import DEFAULT_ROOT, SkillRegistry
from server.storage import get_storage


class SequenceProvider(ModelProvider):
    def __init__(self, responses):
        self.responses = list(responses)
        self.messages = []

    def create_response(self, messages, **kwargs):
        self.messages.append(list(messages))
        return self.responses.pop(0)

    def generate_image(self, prompt, **kwargs):
        return {"data": []}


class AgentOrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        engine = create_engine(f"sqlite:///{Path(self.temp.name, 'agent.db').as_posix()}",
                               connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        database.ENGINE = engine
        database.SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
        with engine.begin() as connection:
            connection.execute(users_table.insert(), {"id": "user-a", "email": "a@example.com",
                "display_name": "A", "password_hash": "x", "role": "user", "status": "active",
                "created_at": "2026-01-01"})
        self.registry = SkillRegistry((DEFAULT_ROOT,)).reload()

    def tearDown(self):
        database.ENGINE.dispose()
        self.temp.cleanup()

    def make_run(self, mode="manual", skill_id="wechat_writer", content="写一篇公众号文章"):
        conversation = conversation_repository.create_conversation(
            "user-a", mode=mode, skill_id=skill_id if mode == "manual" else None)
        message = conversation_repository.add_message(conversation["id"], "user-a", "user", content)
        run, _ = conversation_repository.create_run(conversation["id"], "user-a", message["id"], "key-" + message["id"])
        return conversation, run

    def test_manual_router_never_guesses_another_skill(self):
        decision = SkillRouter(self.registry).route("帮我写小红书", mode="manual", bound_skill_id="wechat_writer")
        self.assertEqual("wechat_writer", decision.skill_id)
        self.assertEqual(1.0, decision.confidence)

    def test_ambiguous_auto_route_requests_confirmation(self):
        decision = SkillRouter(self.registry).route("帮我处理一下", mode="auto")
        self.assertTrue(decision.needs_confirmation)
        self.assertIsNone(decision.skill_id)

    def test_tool_loop_records_call_and_returns_final_answer(self):
        _, run = self.make_run()
        provider = SequenceProvider([
            ProviderResponse(tool_calls=(ToolInvocation("call-1", "write_article", {"topic": "AI"}),)),
            ProviderResponse(text="文章完成"),
        ])
        result = run_tool_loop(model_service=ModelService(provider), messages=[],
            tools={"write_article": ExecutableTool(
                {"name": "write_article", "description": "write", "parameters": {"type": "object"}},
                lambda args: {"title": args["topic"]})},
            run_id=run["id"], user_id="user-a", skill_id="wechat_writer",
            max_tool_calls=2, timeout_seconds=30)
        self.assertEqual("文章完成", result)
        with database.session_scope() as db:
            call = db.query(ToolCall).one()
            self.assertEqual("completed", call.status)
            self.assertEqual({"title": "AI"}, call.result_json)

    def test_tool_loop_stops_at_manifest_limit(self):
        _, run = self.make_run()
        provider = SequenceProvider([
            ProviderResponse(tool_calls=(ToolInvocation("call-1", "again", {}),)),
            ProviderResponse(tool_calls=(ToolInvocation("call-2", "again", {}),)),
        ])
        with self.assertRaisesRegex(RuntimeError, "maximum tool calls"):
            run_tool_loop(model_service=ModelService(provider), messages=[],
                tools={"again": ExecutableTool(
                    {"name": "again", "description": "again", "parameters": {"type": "object"}},
                    lambda args: {"ok": True})}, run_id=run["id"], user_id="user-a",
                skill_id="wechat_writer", max_tool_calls=1, timeout_seconds=30)

    def test_orchestrator_persists_assistant_message_and_completes_run(self):
        conversation, run = self.make_run()
        provider = SequenceProvider([ProviderResponse(text="这是完成的文章")])
        orchestrator = AgentOrchestrator(registry=self.registry, model_service=ModelService(provider),
                                         tool_resolver=lambda *_: {})
        result = orchestrator.execute(run["id"], "user-a")
        self.assertEqual("completed", result["status"])
        self.assertEqual("completed", conversation_repository.get_run(run["id"], "user-a")["status"])
        history = conversation_repository.list_messages(conversation["id"], "user-a")
        self.assertEqual(["写一篇公众号文章", "这是完成的文章"], [item["content"] for item in history])
        artifacts = conversation_repository.list_artifacts(conversation["id"], "user-a")
        self.assertEqual(["这是完成的文章"], [item["content"] for item in artifacts])

    def test_orchestrator_persists_tool_output_as_idempotent_artifact(self):
        conversation, run = self.make_run()
        provider = SequenceProvider([
            ProviderResponse(tool_calls=(ToolInvocation(
                "write-1", "write_article", {"topic": "普通人使用 AI"},
            ),)),
            ProviderResponse(text="文章已经写好。"),
        ])
        orchestrator = AgentOrchestrator(
            registry=self.registry,
            model_service=ModelService(provider),
            tool_resolver=lambda *_: {"write_article": ExecutableTool(
                {"name": "write_article", "description": "write", "parameters": {"type": "object"}},
                lambda args: {"title": args["topic"], "article": "这是工具生成的正文"},
            )},
        )
        result = orchestrator.execute(run["id"], "user-a")
        artifacts = conversation_repository.list_artifacts(conversation["id"], "user-a")
        self.assertEqual(1, len(artifacts))
        self.assertEqual("article", artifacts[0]["type"])
        self.assertEqual("这是工具生成的正文", artifacts[0]["content"])
        self.assertTrue(artifacts[0]["source_key"].endswith(":article:0"))
        self.assertEqual(artifacts[0]["id"], result["artifact"]["id"])

    def test_generated_image_is_copied_into_owner_scoped_storage(self):
        conversation, run = self.make_run()
        stream = io.BytesIO()
        Image.new("RGB", (8, 8), "blue").save(stream, format="PNG")
        encoded = base64.b64encode(stream.getvalue()).decode("ascii")
        provider = SequenceProvider([
            ProviderResponse(tool_calls=(ToolInvocation(
                "image-1", "generate_image", {"prompt": "蓝色方块"},
            ),)),
            ProviderResponse(text="图片已经生成。"),
        ])
        orchestrator = AgentOrchestrator(
            registry=self.registry,
            model_service=ModelService(provider),
            tool_resolver=lambda *_: {"generate_image": ExecutableTool(
                {"name": "generate_image", "description": "image", "parameters": {"type": "object"}},
                lambda args: {"data": [{"b64_json": encoded}]},
            )},
        )
        storage_root = str(Path(self.temp.name, "storage"))
        with patch.dict("os.environ", {
            "STORAGE_PROVIDER": "local", "LOCAL_STORAGE_ROOT": storage_root,
        }):
            get_storage(refresh=True)
            orchestrator.execute(run["id"], "user-a")
            artifact = conversation_repository.list_artifacts(conversation["id"], "user-a")[0]
            self.assertEqual("image", artifact["type"])
            self.assertTrue(artifact["storage_url"].startswith("/api/storage/user-a/"))
            self.assertTrue(get_storage().local_path(artifact["storage_key"]).is_file())
            self.assertNotIn("b64_json", artifact["content_json"])

    def test_auto_route_is_persisted_on_run(self):
        conversation, run = self.make_run(mode="auto", content="写一篇公众号文章")
        provider = SequenceProvider([ProviderResponse(text="文章完成")])
        AgentOrchestrator(
            registry=self.registry, model_service=ModelService(provider), tool_resolver=lambda *_: {},
        ).execute(run["id"], "user-a")
        self.assertEqual(
            "wechat_writer", conversation_repository.get_run(run["id"], "user-a")["skill_id"],
        )
        self.assertEqual(
            "wechat_writer",
            conversation_repository.get_conversation(conversation["id"], "user-a")["skill_id"],
        )

    def test_context_preserves_reference_to_previous_turn(self):
        conversation, first_run = self.make_run(content="给我三个选题：甲、乙、丙")
        conversation_repository.add_message(conversation["id"], "user-a", "assistant", "1甲 2乙 3丙")
        conversation_repository.create_artifact(
            first_run["id"], "user-a", "article", content="第一版完整正文",
        )
        message = conversation_repository.add_message(conversation["id"], "user-a", "user", "第三个")
        run, _ = conversation_repository.create_run(conversation["id"], "user-a", message["id"], "follow-up")
        provider = SequenceProvider([ProviderResponse(text="我将围绕丙继续")])
        AgentOrchestrator(registry=self.registry, model_service=ModelService(provider),
                          tool_resolver=lambda *_: {}).execute(run["id"], "user-a")
        sent = provider.messages[0]
        self.assertTrue(any(item.get("content") == "1甲 2乙 3丙" for item in sent))
        self.assertTrue(any(item.get("content") == "第三个" for item in sent))
        self.assertTrue(any("第一版完整正文" in item.get("content", "") for item in sent))


if __name__ == "__main__":
    unittest.main()
