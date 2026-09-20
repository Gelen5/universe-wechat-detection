from __future__ import annotations

import unittest

from server.providers import ModelService, OpenAICompatibleProvider, ProviderRequestError


class FakeResponse:
    def __init__(self, data, status=200):
        self.data, self.status_code, self.ok = data, status, status < 400

    def json(self):
        return self.data


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

    def test_native_tool_call_is_structured(self):
        provider = self.provider([FakeResponse({"choices": [{"message": {"tool_calls": [{
            "id": "call-1", "function": {"name": "search_topics", "arguments": "{\"query\":\"AI\"}"}}]}}]})])
        result = provider.create_response([{"role": "user", "content": "找选题"}],
                                          tools=[{"name": "search_topics", "description": "search", "parameters": {"type": "object"}}])
        self.assertEqual("search_topics", result.tool_calls[0].name)
        self.assertEqual({"query": "AI"}, result.tool_calls[0].arguments)

    def test_http_429_is_transient(self):
        provider = self.provider([FakeResponse({"error": {"message": "slow down"}}, 429)])
        with self.assertRaises(ProviderRequestError) as caught:
            provider.create_response([])
        self.assertTrue(caught.exception.transient)

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
