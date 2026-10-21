from __future__ import annotations

import json
import unittest

from server.providers import ModelService, OpenAICompatibleProvider, ProviderCostPolicy, ProviderRequestError


class FakeResponse:
    def __init__(self, data, status=200):
        self.data, self.status_code, self.ok = data, status, status < 400

    def json(self):
        return self.data

    def iter_lines(self):
        yield b"event: response.completed"
        yield b"data: " + json.dumps({"type": "response.completed", "response": self.data}).encode()

    def close(self):
        pass


class FakeStreamFailure(FakeResponse):
    def iter_lines(self):
        yield b"data: " + json.dumps({"type": "response.failed", "response": self.data}).encode()


class FakeSession:
    trust_env = True

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        return self.responses.pop(0)


class ProviderTests(unittest.TestCase):
    def provider(self, responses):
        return OpenAICompatibleProvider(api_key="secret", base_url="https://example.test/v1",
                                        text_model="text", image_model="image",
                                        session=FakeSession(responses))

    def test_text_response_and_usage(self):
        provider = self.provider([FakeResponse({"choices": [{"message": {"content": "完成"}}],
                                                "usage": {"prompt_tokens": 10, "completion_tokens": 5}})])
        result = ModelService(provider).create_response([{"role": "user", "content": "hello"}])
        self.assertEqual("完成", result.text)
        self.assertEqual((10, 5), (result.input_tokens, result.output_tokens))

    def test_model_service_reports_run_usage(self):
        provider = self.provider([FakeResponse({
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4},
        })])
        recorded = []
        ModelService(provider, usage_recorder=recorded.append).create_response(
            [{"role": "user", "content": "hello"}], run_id="run-1", user_id="user-1")
        self.assertEqual("run-1", recorded[0]["run_id"])
        self.assertEqual("text", recorded[0]["model"])
        self.assertEqual((3, 4), (recorded[0]["input_tokens"], recorded[0]["output_tokens"]))

    def test_model_service_calculates_configured_text_and_image_cost(self):
        provider = self.provider([
            FakeResponse({"choices": [{"message": {"content": "ok"}}],
                          "usage": {"prompt_tokens": 3, "completion_tokens": 4}}),
            FakeResponse({"data": [{"url": "https://image.test/a.png"}]}),
        ])
        recorded = []
        service = ModelService(provider, usage_recorder=recorded.append, cost_policy=ProviderCostPolicy(
            input_micros_per_million_tokens=1_000_000,
            output_micros_per_million_tokens=2_000_000,
            image_micros_each=250,
        ))
        service.create_response([], run_id="run-1", user_id="user-1")
        service.generate_image("prompt", size="768x1024", count=2,
                               run_id="run-1", user_id="user-1")
        self.assertEqual(11, recorded[0]["estimated_cost_micros"])
        self.assertEqual(500, recorded[1]["estimated_cost_micros"])

    def test_native_tool_call_is_structured(self):
        provider = self.provider([FakeResponse({"choices": [{"message": {"tool_calls": [{
            "id": "call-1", "function": {"name": "search_topics", "arguments": "{\"query\":\"AI\"}"}}]}}]})])
        result = provider.create_response([{"role": "user", "content": "找选题"}],
                                          tools=[{"name": "search_topics", "description": "search", "parameters": {"type": "object"}}])
        self.assertEqual("search_topics", result.tool_calls[0].name)
        self.assertEqual({"query": "AI"}, result.tool_calls[0].arguments)

    def test_responses_api_tool_call_and_followup(self):
        session = FakeSession([
            FakeResponse({"status": "completed", "output": [{"type": "function_call", "call_id": "call-1",
                "name": "search_topics", "arguments": '{"query":"AI"}'}],
                "usage": {"input_tokens": 8, "output_tokens": 4}}),
            FakeResponse({"status": "completed", "output": [{"type": "message", "content": [
                {"type": "output_text", "text": "完成"}]}]}),
        ])
        provider = OpenAICompatibleProvider(api_key="secret", base_url="https://example.test/v1/responses",
                                            text_model="text", session=session)
        tools = [{"name": "search_topics", "description": "search", "parameters": {"type": "object"}}]
        first = provider.create_response([{"role": "user", "content": "找选题"}], tools=tools)
        self.assertEqual("https://example.test/v1/responses", session.requests[0][1])
        self.assertTrue(session.requests[0][2]["json"]["stream"])
        self.assertEqual("search_topics", session.requests[0][2]["json"]["tools"][0]["name"])
        self.assertEqual({"query": "AI"}, first.tool_calls[0].arguments)
        self.assertEqual((8, 4), (first.input_tokens, first.output_tokens))
        second = provider.create_response([
            {"role": "user", "content": "找选题"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "call-1", "type": "function",
                "function": {"name": "search_topics", "arguments": '{"query":"AI"}'}}]},
            {"role": "tool", "tool_call_id": "call-1", "content": '{"topics":[]}'}], tools=tools)
        self.assertEqual("完成", second.text)
        self.assertEqual("function_call", session.requests[1][2]["json"]["input"][1]["type"])
        self.assertEqual("function_call_output", session.requests[1][2]["json"]["input"][2]["type"])

    def test_responses_api_overload_is_transient(self):
        session = FakeSession([FakeStreamFailure({"error": {"message": "Our servers are currently overloaded. Please try again later."}})])
        provider = OpenAICompatibleProvider(api_key="secret", base_url="https://example.test/v1/responses",
                                            text_model="text", session=session)
        with self.assertRaises(ProviderRequestError) as caught:
            provider.create_response([{"role": "user", "content": "hello"}])
        self.assertTrue(caught.exception.transient)

    def test_responses_api_reasoning_effort_is_opt_in(self):
        session = FakeSession([FakeResponse({"status": "completed", "output": []})])
        provider = OpenAICompatibleProvider(api_key="secret", base_url="https://example.test/v1/responses",
                                            text_model="text", session=session, reasoning_effort="low")
        provider.create_response([{"role": "user", "content": "review"}])
        self.assertEqual({"effort": "low"}, session.requests[0][2]["json"]["reasoning"])

        default_session = FakeSession([FakeResponse({"status": "completed", "output": []})])
        default_provider = OpenAICompatibleProvider(api_key="secret", base_url="https://example.test/v1/responses",
                                                    text_model="text", session=default_session)
        default_provider.create_response([{"role": "user", "content": "write"}])
        self.assertNotIn("reasoning", default_session.requests[0][2]["json"])

    def test_http_429_is_transient(self):
        provider = self.provider([FakeResponse({"error": {"message": "slow down"}}, 429)])
        with self.assertRaises(ProviderRequestError) as caught:
            provider.create_response([])
        self.assertTrue(caught.exception.transient)

    def test_ip_allowlist_rejection_is_not_retried(self):
        provider = self.provider([FakeResponse({"error": {"message": "您的 IP 不在令牌允许访问的列表中"}}, 403)])
        with self.assertRaises(ProviderRequestError) as caught:
            provider.create_response([])
        self.assertEqual("ip_not_allowed", caught.exception.code)
        self.assertFalse(caught.exception.transient)

    def test_image_generation_uses_image_endpoint_and_idempotency(self):
        session = FakeSession([FakeResponse({"data": [{"url": "https://image.test/a.png"}]})])
        provider = OpenAICompatibleProvider(api_key="text", base_url="https://text.test",
                                            text_model="text", image_api_key="image-key",
                                            image_base_url="https://image.test/v1", image_model="image",
                                            session=session)
        data = provider.generate_image("prompt", size="768x1024", idempotency_key="request-1")
        self.assertTrue(data["data"])
        _, url, kwargs = session.requests[0]
        self.assertTrue(url.endswith("/v1/images/generations"))
        self.assertEqual("request-1", kwargs["headers"]["Idempotency-Key"])


if __name__ == "__main__":
    unittest.main()
