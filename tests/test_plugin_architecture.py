from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server import conversation_repository, database
from server.agent import runtime
from server.agent.orchestrator import AgentOrchestrator
from server.agent.router import SkillRouter
from server.models import Base, UsageRecord, Wallet, users_table
from server.providers import ModelProvider, ModelService, ProviderResponse, ToolInvocation
from server.skills.registry import SkillRegistry


class DemoProvider(ModelProvider):
    def __init__(self):
        self.responses = [
            ProviderResponse(tool_calls=(ToolInvocation("provider-call", "make_demo", {"topic": "插件"}),)),
            ProviderResponse(text="Demo 已完成。"),
        ]

    def create_response(self, messages, **kwargs):
        return self.responses.pop(0)

    def generate_image(self, prompt, **kwargs):
        return {"data": []}


class PluginArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        engine = create_engine(f"sqlite:///{(root / 'plugin.db').as_posix()}",
                               connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        database.ENGINE = engine
        database.SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
        with engine.begin() as connection:
            connection.execute(users_table.insert(), {"id": "plugin-user", "email": "plugin@example.com",
                "display_name": "Plugin", "password_hash": "x", "role": "user", "status": "active",
                "created_at": "2026-01-01"})
        with database.session_scope() as db:
            db.add(Wallet(user_id="plugin-user", balance=50, trial_balance=50,
                          bonus_balance=0, paid_balance=0, updated_at="2026-01-01"))

    def tearDown(self):
        database.ENGINE.dispose()
        self.temp.cleanup()

    @staticmethod
    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_demo_skill_installs_without_agent_router_or_api_core_changes(self):
        project = Path(__file__).resolve().parents[1]
        core = [project / "server/agent/router.py", project / "server/agent/orchestrator.py",
                project / "server/agent/runtime.py", project / "server/conversation_api.py"]
        before = {path: self.digest(path) for path in core}

        skill = Path(self.temp.name) / "skills" / "demo_skill"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("你是 Demo Skill，只调用 make_demo。", encoding="utf-8")
        (skill / "skill.json").write_text(json.dumps({
            "id": "demo_skill", "name": "Demo", "version": "1.0.0",
            "description": "验证插件架构", "capabilities": ["demo"],
            "routing": {"keywords": ["演示插件"], "examples": ["运行演示插件"], "priority": 100},
            "runtime": {"type": "adapter", "adapter": "adapter.py", "default_artifact": "report"},
            "tools": [{"name": "make_demo", "executor": "make_demo", "description": "生成演示报告",
                       "parameters": {"type": "object", "properties": {"topic": {"type": "string"}},
                                      "required": ["topic"], "additionalProperties": False}}],
            "pricing": {"base_points": 7}, "trusted": True,
        }, ensure_ascii=False), encoding="utf-8")
        (skill / "adapter.py").write_text(
            "from server.skills.tool_result import ToolResult, ArtifactOutput\n"
            "def create_tools():\n"
            "    def make_demo(args, context):\n"
            "        text = 'Demo:' + args['topic']\n"
            "        return ToolResult({'report': text}, (ArtifactOutput(type='report', title='Demo', content=text),))\n"
            "    return {'make_demo': make_demo}\n", encoding="utf-8")

        registry = SkillRegistry((skill.parent,)).reload()
        decision = SkillRouter(registry).route("请运行演示插件", mode="auto")
        self.assertEqual("demo_skill", decision.skill_id)
        conversation = conversation_repository.create_conversation("plugin-user", mode="auto")
        message, run, replay = conversation_repository.create_message_run(
            conversation["id"], "plugin-user", "请运行演示插件", "plugin-demo-key",
            reserve_points=7, feature="Demo")
        self.assertFalse(replay)
        provider = ModelService(DemoProvider())
        result = AgentOrchestrator(
            registry=registry, model_service=provider,
            tool_resolver=lambda skill_id, run_id, user_id: runtime.resolve_tools(
                skill_id, registry=registry, model_service=provider, run_id=run_id, user_id=user_id),
        ).execute(run["id"], "plugin-user")

        self.assertEqual("completed", result["status"])
        artifacts = conversation_repository.list_artifacts(conversation["id"], "plugin-user")
        self.assertEqual([("report", "Demo:插件")], [(item["type"], item["content"]) for item in artifacts])
        with database.session_scope() as db:
            usage = db.query(UsageRecord).filter_by(run_id=run["id"]).one()
            wallet = db.get(Wallet, "plugin-user")
            self.assertEqual(("completed", 7), (usage.status, usage.points))
            self.assertEqual(43, wallet.balance)
        self.assertIsNone(conversation_repository.get_conversation(
            conversation["id"], "plugin-user")["skill_id"])
        self.assertEqual(before, {path: self.digest(path) for path in core})


if __name__ == "__main__":
    unittest.main()
