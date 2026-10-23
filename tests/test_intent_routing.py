"""阶段由模型理解，不由关键词猜。"""
from __future__ import annotations

import unittest

from server.agent import intent as routing
from server.providers import ModelProvider, ModelService, ProviderResponse


class ScriptedProvider(ModelProvider):
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = 0

    def create_response(self, messages, **kwargs):
        self.calls += 1
        self.messages = messages
        if self.error:
            raise self.error
        return ProviderResponse(text=self.payload or "")

    def generate_image(self, prompt, **kwargs):
        return {"data": []}


def resolve(text, payload=None, *, hint="writing", error=None, explicit=None, artifacts=None):
    provider = ScriptedProvider(payload, error)
    result = routing.resolve_intent(
        model_service=ModelService(provider), text=text, stage_hint=hint,
        artifacts=artifacts or [], recent=[{"role": "user", "content": text}],
        run_id="run-1", user_id="user-a", explicit_stage=explicit,
    )
    return result, provider


class IntentRoutingTests(unittest.TestCase):
    def test_topic_beats_the_word_write(self):
        # 原 bug：这句话里"写一篇"命中了写作，用户真正要的是选题。
        result, _ = resolve(
            "我准备写一篇关于AI相关的文章 给我下选题",
            '{"stage":"topic","direction":"AI 相关","instruction":"给 10 个选题",'
            '"reason":"先给你 10 个选题","confidence":0.93}',
        )
        self.assertEqual("topic", result.stage)
        self.assertEqual("AI 相关", result.direction)
        self.assertEqual("model", result.source)

    def test_explicit_stage_skips_the_model(self):
        result, provider = resolve("开始", hint="typeset", explicit="typeset")
        self.assertEqual("typeset", result.stage)
        self.assertEqual("explicit", result.source)
        self.assertEqual(0, provider.calls)

    def test_low_confidence_switch_keeps_the_current_tab(self):
        result, _ = resolve("随便看看", '{"stage":"typeset","reason":"猜的","confidence":0.2}')
        self.assertEqual("writing", result.stage)
        self.assertEqual("fallback", result.source)

    def test_low_confidence_same_stage_is_fine(self):
        result, _ = resolve("开始写吧", '{"stage":"writing","reason":"写正文","confidence":0.3}')
        self.assertEqual("writing", result.stage)
        self.assertEqual("model", result.source)

    def test_question_returns_no_stage(self):
        result, _ = resolve("这篇能发吗？", '{"stage":null,"reason":"这是提问","confidence":0.9}')
        self.assertIsNone(result.stage)
        self.assertEqual("model", result.source)

    def test_invalid_json_falls_back(self):
        result, _ = resolve("嗯", "我觉得应该先选题")
        self.assertEqual("writing", result.stage)
        self.assertEqual("fallback", result.source)

    def test_provider_error_falls_back_without_failing_the_run(self):
        result, _ = resolve("写吧", error=RuntimeError("provider down"))
        self.assertEqual("writing", result.stage)
        self.assertEqual("fallback", result.source)
        self.assertIn("按当前步骤继续", result.reason)

    def test_chinese_aliases_are_understood(self):
        result, _ = resolve("排版吧", '{"stage":"排版","confidence":0.9}')
        self.assertEqual("typeset", result.stage)

    def test_prompt_carries_state_and_recent_titles(self):
        _, provider = resolve(
            "继续", '{"stage":"topic","confidence":0.9}', hint="outline",
            artifacts=[
                {"type": "topic", "version": 1, "content": "1. 老选题",
                 "content_json": {"topics": [{"title": "AI 会取代谁"}]}},
                {"type": "article", "version": 2, "content": "正文", "title": "旧文"},
            ],
        )
        prompt = provider.messages[-1]["content"]
        self.assertIn("当前标签：outline", prompt)
        self.assertIn("AI 会取代谁", prompt)
        self.assertIn("旧文", prompt)


if __name__ == "__main__":
    unittest.main()
