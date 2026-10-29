"""失败必须落到对话流里，而不是只改一行状态。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server import conversation_repository, database
from server.agent import failures
from server.agent.orchestrator import stage_contract
from server.models import Base, users_table
from server.providers import ProviderRequestError

class FailureClassificationTests(unittest.TestCase):
    def test_review_fidelity_failure_explains_original_was_preserved(self):
        result = failures.describe(RuntimeError('自动修稿后仍需处理：保真检查。已保留原文，未进入配图。'))
        self.assertEqual(result['error_kind'], 'review_validation')
        self.assertIn('保真', result['reason'])
    def test_hotspot_failure_is_retryable(self):
        detail = failures.describe(RuntimeError("选题 Skill 热点抓取未成功，已停止生成；请稍后重试。"))
        self.assertEqual("topic_source", detail["error_kind"])
        self.assertTrue(detail["retryable"])

    def test_missing_skill_is_not_retryable(self):
        detail = failures.describe(RuntimeError("wechat-publisher-ultimate Skill 未完整安装：SKILL.md"))
        self.assertEqual("skill_missing", detail["error_kind"])
        self.assertFalse(detail["retryable"])

    def test_topic_schema_failure_is_retryable(self):
        detail = failures.describe(RuntimeError("模型只返回了 4 个选题，少于最低要求 6 个"))
        self.assertEqual("topic_schema", detail["error_kind"])
        self.assertTrue(detail["retryable"])

    def test_provider_ip_error_maps_to_access(self):
        exc = ProviderRequestError("IP 不在令牌允许访问范围", code="ip_not_allowed")
        self.assertEqual("provider_access", failures.describe(exc)["error_kind"])

    def test_credentials_are_redacted(self):
        detail = failures.describe(RuntimeError("boom sk-abcdefghijklmnop"))
        self.assertNotIn("sk-abcdefghijklmnop", detail["technical"])

    def test_stage_contract_names_tool_and_direction(self):
        contract = stage_contract("topic", "search_topics",
                                  {"topic_direction": "AI 工具实测", "selected_topic": "主题"})
        self.assertIn("search_topics", contract)
        self.assertIn("AI 工具实测", contract)
        self.assertIn("选题", contract)


class RunTestCase(unittest.TestCase):
    """One sqlite database, one user, one staged conversation per test."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        engine = create_engine(f"sqlite:///{Path(self.temp.name, 'failures.db').as_posix()}",
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
            self.conversation["id"], "user-a", "user", "写一篇 AI 的文章",
            content_json={"workflow_stage": "topic", "topic_direction": "AI 工具实测"})
        self.run, _ = conversation_repository.create_run(
            self.conversation["id"], "user-a", message["id"], "key-" + message["id"])

    def tearDown(self):
        database.ENGINE.dispose()
        self.temp.cleanup()

    def messages(self):
        return conversation_repository.list_messages(self.conversation["id"], "user-a")


class FailedRunMessageTests(RunTestCase):
    def test_failure_is_written_into_the_thread(self):
        exc = RuntimeError("选题 Skill 热点抓取未成功，已停止生成；请稍后重试。")
        failures.fail_run(self.run["id"], "user-a", exc)

        messages = self.messages()
        self.assertEqual(2, len(messages))
        failure = messages[-1]
        self.assertEqual("assistant", failure["role"])
        self.assertEqual("run_failed", failure["content_json"]["kind"])
        self.assertEqual("topic", failure["content_json"]["stage"])
        self.assertEqual("topic_source", failure["content_json"]["error_code"])
        self.assertTrue(failure["content_json"]["retryable"])
        self.assertIn("选题", failure["content"])
        self.assertIn("重试", failure["content"])

        run = conversation_repository.get_run(self.run["id"], "user-a")
        self.assertEqual("failed", run["status"])
        self.assertEqual("topic_source", run["error_kind"])
        self.assertEqual("topic_source", run["error_code"])

    def test_failure_message_is_not_duplicated(self):
        exc = RuntimeError("provider connection failed")
        failures.fail_run(self.run["id"], "user-a", exc)
        failures.fail_run(self.run["id"], "user-a", exc)
        failures.fail_run(self.run["id"], "user-a", RuntimeError("another error"))
        self.assertEqual(2, len(self.messages()))

    def test_completed_run_is_not_downgraded(self):
        conversation_repository.transition_run(self.run["id"], "user-a", "completed")
        result = failures.fail_run(self.run["id"], "user-a", RuntimeError("late failure"))
        self.assertIsNone(result)
        self.assertEqual("completed", conversation_repository.get_run(self.run["id"], "user-a")["status"])
        self.assertEqual(1, len(self.messages()))

    def test_run_view_never_leaks_provider_detail(self):
        failures.fail_run(self.run["id"], "user-a",
                          ProviderRequestError("用户余额不足, request id: secret-provider-id",
                                               code="http_error", transient=False))
        run = conversation_repository.get_run(self.run["id"], "user-a")
        self.assertNotIn("error_message", run)
        self.assertEqual("provider_balance", run["error_kind"])
        self.assertNotIn("secret-provider-id", str(run))

    def test_retry_after_failure_starts_a_new_run(self):
        failures.fail_run(self.run["id"], "user-a", RuntimeError("boom"))
        retry = conversation_repository.add_message(
            self.conversation["id"], "user-a", "user", "重试",
            content_json={"workflow_stage": "topic"})
        new_run, replay = conversation_repository.create_run(
            self.conversation["id"], "user-a", retry["id"], "retry-" + retry["id"])
        self.assertFalse(replay)
        self.assertNotEqual(self.run["id"], new_run["id"])
        self.assertEqual("queued", new_run["status"])

    def test_orchestrator_writes_the_failure_message(self):
        from unittest.mock import patch

        from server.agent.orchestrator import AgentOrchestrator
        from server.agent.tool_loop import ExecutableTool
        from server.providers import ModelProvider, ModelService, ProviderResponse
        from server.skills.registry import DEFAULT_ROOT, SkillRegistry

        class Router(ModelProvider):
            def create_response(self, messages, **kwargs):
                return ProviderResponse(text=(
                    '{"stage":"topic","direction":"AI 工具实测","instruction":"给我选题",'
                    '"reason":"先给选题","confidence":0.9}'))

            def generate_image(self, prompt, **kwargs):
                return {"data": []}

        tool = ExecutableTool({"name": "search_topics", "parameters": {"type": "object"}},
                              lambda args: {"topics": []})
        orchestrator = AgentOrchestrator(
            registry=SkillRegistry((DEFAULT_ROOT,)).reload(),
            model_service=ModelService(Router()),
            tool_resolver=lambda *_: {"search_topics": tool},
        )
        with patch("server.agent.orchestrator.run_tool_loop",
                   side_effect=RuntimeError("选题 Skill 热点抓取未成功，已停止生成；请稍后重试。")):
            with self.assertRaises(RuntimeError):
                orchestrator.execute(self.run["id"], "user-a")

        failure = self.messages()[-1]
        self.assertEqual("run_failed", failure["content_json"]["kind"])
        self.assertEqual("topic", failure["content_json"]["stage"])
        self.assertEqual("topic_source", failure["content_json"]["error_code"])
        run = conversation_repository.get_run(self.run["id"], "user-a")
        self.assertEqual("failed", run["status"])
        self.assertEqual("topic", run["stage"])


class OrchestratorRoutingTests(RunTestCase):
    """Model routing decides the stage; the tab is only a hint."""

    def run_with(self, routing_json, *, tab="writing", text="给我下选题", loop_result="好"):
        from unittest.mock import patch

        from server.agent.orchestrator import AgentOrchestrator
        from server.agent.tool_loop import ExecutableTool
        from server.providers import ModelProvider, ModelService, ProviderResponse
        from server.skills.registry import DEFAULT_ROOT, SkillRegistry

        class Router(ModelProvider):
            def create_response(self, messages, **kwargs):
                return ProviderResponse(text=routing_json)

            def generate_image(self, prompt, **kwargs):
                return {"data": []}

        conversation = conversation_repository.create_conversation(
            "user-a", mode="manual", skill_id="wechat_writer")
        message = conversation_repository.add_message(
            conversation["id"], "user-a", "user", text,
            content_json={"workflow_stage": tab})
        run, _ = conversation_repository.create_run(
            conversation["id"], "user-a", message["id"], "route-" + message["id"])
        tools = {name: ExecutableTool({"name": name, "parameters": {"type": "object"}},
                                      lambda args: {})
                 for name in ("search_topics", "create_outline", "write_article",
                              "review_article", "typeset_article")}
        orchestrator = AgentOrchestrator(
            registry=SkillRegistry((DEFAULT_ROOT,)).reload(),
            model_service=ModelService(Router()),
            tool_resolver=lambda *_: tools,
        )
        with patch("server.agent.orchestrator.run_tool_loop", return_value=loop_result) as loop:
            orchestrator.execute(run["id"], "user-a")
        return run, loop

    def test_model_switches_tab_hint_to_the_right_stage(self):
        run, loop = self.run_with(
            '{"stage":"topic","direction":"AI 相关","instruction":"给我选题",'
            '"reason":"先给你选题","confidence":0.9}')
        self.assertEqual(["search_topics"], list(loop.call_args.kwargs["tools"]))
        self.assertEqual("search_topics", loop.call_args.kwargs["required_tool"])
        stored = conversation_repository.get_run(run["id"], "user-a")
        self.assertEqual("topic", stored["stage"])
        events = [item["type"] for item in
                  conversation_repository.events_after(run["id"], "user-a")]
        self.assertIn("stage.resolved", events)

    def test_question_answers_without_tools_or_artifacts(self):
        run, loop = self.run_with(
            '{"stage":null,"reason":"这是提问","confidence":0.92}',
            text="这篇能发吗", loop_result="可以，先补一个来源。")
        self.assertEqual({}, loop.call_args.kwargs["tools"])
        self.assertIsNone(loop.call_args.kwargs["required_tool"])
        self.assertEqual([], conversation_repository.list_artifacts(
            run["conversation_id"], "user-a"))
        last = self.messages_of(run["conversation_id"])[-1]
        self.assertEqual("answer", last["content_json"]["kind"])

    def messages_of(self, conversation_id):
        return conversation_repository.list_messages(conversation_id, "user-a")


if __name__ == "__main__":
    unittest.main()
