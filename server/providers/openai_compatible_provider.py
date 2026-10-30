from __future__ import annotations

import json
import time
from typing import Any

import requests

from .base import ModelProvider, ProviderRequestError, ProviderResponse, ToolInvocation


# Upstream gateways behind relay stations answer with prose, not error codes.
# Treat those as retryable so a flaky upstream does not become a failed run.
TRANSIENT_MARKERS = (
    "overload", "try again later", "timed out", "timeout", "rate limit",
    "an error occurred while processing your request", "internal server error",
    "bad gateway", "service unavailable", "gateway timeout", "temporarily",
    "upstream", "please retry", "please try again", "server error",
)


class OpenAICompatibleProvider(ModelProvider):
    def __init__(self, *, api_key: str, base_url: str, text_model: str,
                 image_api_key: str | None = None, image_base_url: str | None = None,
                 image_model: str | None = None, verify_ssl: bool = True,
                 session: requests.Session | None = None,
                 reasoning_effort: str | None = None,
                 max_output_tokens: int | None = None):
        self.api_key = api_key
        self.responses_api = base_url.strip().rstrip("/").endswith("/responses") or text_model == "gpt-6.1-sol"
        if self.responses_api:
            base_url = base_url.strip().rstrip("/").removesuffix("/responses")
        self.base_url = self._v1(base_url)
        self.text_model = text_model
        self.image_api_key = image_api_key or api_key
        self.image_base_url = self._v1(image_base_url or base_url)
        self.image_model = image_model or "gpt-image-2"
        self.verify_ssl = verify_ssl
        self.reasoning_effort = reasoning_effort
        self.max_output_tokens = max_output_tokens
        self.session = session or requests.Session()
        self.session.trust_env = False

    @staticmethod
    def _v1(value: str) -> str:
        base = value.strip().rstrip("/")
        return base if base.endswith("/v1") else base + "/v1"

    def create_response(self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None,
                        timeout: int = 120, idempotency_key: str | None = None) -> ProviderResponse:
        if self.responses_api:
            return self._create_responses_response(messages, tools=tools, timeout=timeout,
                                                   idempotency_key=idempotency_key)
        body: dict[str, Any] = {"model": self.text_model, "messages": messages}
        if self.max_output_tokens:
            body["max_tokens"] = self.max_output_tokens
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        if tools:
            body["tools"] = [{"type": "function", "function": tool} for tool in tools]
            body["tool_choice"] = "auto"
        data = self._post(self.base_url + "/chat/completions", self.api_key, body, timeout, idempotency_key)
        choices = data.get("choices") or []
        message = choices[0].get("message") if choices else {}
        content = message.get("content") or ""
        if isinstance(content, list):
            content = "".join(str(item.get("text") or "") for item in content if isinstance(item, dict))
        calls = []
        for item in message.get("tool_calls") or []:
            function = item.get("function") or {}
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except json.JSONDecodeError as exc:
                raise ProviderRequestError("provider returned invalid tool arguments", code="invalid_tool_call") from exc
            if not isinstance(arguments, dict):
                raise ProviderRequestError("tool arguments must be an object", code="invalid_tool_call")
            calls.append(ToolInvocation(id=str(item.get("id") or ""), name=str(function.get("name") or ""), arguments=arguments))
        usage = data.get("usage") or {}
        return ProviderResponse(text=str(content).strip(), tool_calls=tuple(calls),
                                input_tokens=int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0),
                                output_tokens=int(usage.get("completion_tokens") or usage.get("output_tokens") or 0), raw=data)

    def _create_responses_response(self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None,
                                   timeout: int, idempotency_key: str | None) -> ProviderResponse:
        inputs: list[dict[str, Any]] = []
        for message in messages:
            role = message.get("role")
            if role == "tool":
                inputs.append({"type": "function_call_output", "call_id": message["tool_call_id"],
                               "output": str(message.get("content") or "")})
            elif role == "assistant" and message.get("tool_calls"):
                for call in message["tool_calls"]:
                    function = call.get("function") or {}
                    inputs.append({"type": "function_call", "call_id": call["id"],
                                   "name": function["name"], "arguments": function.get("arguments") or "{}"})
            else:
                inputs.append({"role": role, "content": message.get("content") or ""})
        body: dict[str, Any] = {"model": self.text_model, "input": inputs}
        if self.max_output_tokens:
            body["max_output_tokens"] = self.max_output_tokens
        if self.reasoning_effort:
            body["reasoning"] = {"effort": self.reasoning_effort}
        if tools:
            body["tools"] = [{"type": "function", **tool} for tool in tools]
            body["tool_choice"] = "auto"
        body["stream"] = True
        deadline = time.monotonic() + timeout
        response = self._request("POST", self.base_url + "/responses", self.api_key, body,
                                 timeout, idempotency_key, stream=True)
        data: dict[str, Any] | None = None
        try:
            for line in response.iter_lines():
                if time.monotonic() >= deadline:
                    raise ProviderRequestError('provider response exceeded time budget', code='deadline', transient=False)
                if not line or not line.startswith(b"data: "):
                    continue
                try:
                    event = json.loads(line[6:])
                except ValueError as exc:
                    raise ProviderRequestError("provider returned invalid stream event", code="invalid_response") from exc
                if event.get("type") == "response.completed":
                    data = event.get("response")
                    # A relay may keep SSE alive after the terminal event.
                    # Completion is defined by the protocol, not TCP EOF.
                    break
                elif event.get("type") in {"response.failed", "response.incomplete", "error"}:
                    detail = event.get("response") or event
                    message = self._error(detail) or "provider stream failed"
                    reason = str(((detail.get("incomplete_details") or {}).get("reason")
                                  if isinstance(detail, dict) else "") or "")
                    if event.get("type") == "response.incomplete" and reason == "max_output_tokens":
                        # The model hit our own output cap: retrying the same request
                        # would truncate again, so report it as a hard error.
                        raise ProviderRequestError(message or "output truncated",
                                                   code="output_truncated", transient=False)
                    transient = any(marker in message.lower() for marker in TRANSIENT_MARKERS)
                    raise ProviderRequestError(message, code="provider_unavailable" if transient else "invalid_response",
                                               transient=transient)
        except requests.RequestException as exc:
            raise ProviderRequestError(f"provider stream failed: {exc}", code="transport", transient=True) from exc
        finally:
            response.close()
        if not isinstance(data, dict):
            raise ProviderRequestError("provider stream ended without a completed response", code="invalid_response")
        if data.get("status") not in (None, "completed"):
            raise ProviderRequestError(self._error(data) or f"provider response {data['status']}",
                                       code="invalid_response")
        content: list[str] = []
        calls: list[ToolInvocation] = []
        for item in data.get("output") or []:
            if item.get("type") == "message":
                content.extend(part.get("text") or "" for part in item.get("content") or []
                               if part.get("type") == "output_text")
            elif item.get("type") == "function_call":
                try:
                    arguments = json.loads(item.get("arguments") or "{}")
                except json.JSONDecodeError as exc:
                    raise ProviderRequestError("provider returned invalid tool arguments", code="invalid_tool_call") from exc
                if not isinstance(arguments, dict):
                    raise ProviderRequestError("tool arguments must be an object", code="invalid_tool_call")
                calls.append(ToolInvocation(id=str(item.get("call_id") or ""),
                                            name=str(item.get("name") or ""), arguments=arguments))
        usage = data.get("usage") or {}
        return ProviderResponse(text="".join(content).strip(), tool_calls=tuple(calls),
                                input_tokens=int(usage.get("input_tokens") or 0),
                                output_tokens=int(usage.get("output_tokens") or 0), raw=data)

    def generate_image(self, prompt: str, *, size: str, count: int = 1,
                       timeout: int = 300, idempotency_key: str | None = None) -> dict[str, Any]:
        if not prompt.strip():
            raise ProviderRequestError("image prompt is required", code="invalid_request")
        body = {"model": self.image_model, "prompt": prompt, "size": size, "n": count}
        from urllib.parse import urlsplit
        if urlsplit(self.image_base_url).hostname == 'api.latentide.com':
            body['response_format'] = 'url'
        data = self._read_image_result(body, timeout, idempotency_key)
        status_url = data.get("statusUrl") or data.get("status_url")
        if not status_url or data.get("data"):
            return data
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(3)
            response = self._request("GET", str(status_url), self.image_api_key, None, 35, None)
            data = self._decode(response)
            status = str(data.get("status") or "").lower()
            if data.get("data") or status in {"completed", "succeeded", "success"}:
                return data
            if status in {"failed", "cancelled", "canceled", "error"}:
                raise ProviderRequestError(self._error(data) or f"image task {status}", code="image_failed")
        raise ProviderRequestError("image task timed out", code="timeout", transient=True)

    def _read_image_result(self, body: dict[str, Any], timeout: int,
                           idempotency_key: str | None) -> dict[str, Any]:
        from ..observability import event
        started = time.monotonic()
        response = self._request('POST', self.image_base_url + '/images/generations',
                                 self.image_api_key, body, timeout, idempotency_key, stream=True)
        event('provider.image_headers', latency_ms=int((time.monotonic()-started)*1000))
        parts = []
        decoder = json.JSONDecoder()
        try:
            for chunk in response.iter_content(chunk_size=None):
                if time.monotonic() - started > timeout:
                    raise ProviderRequestError('image response exceeded total time budget', code='timeout')
                if not chunk:
                    continue
                parts.append(chunk)
                try:
                    data, _ = decoder.raw_decode(b''.join(parts).decode('utf-8').lstrip())
                except (ValueError, UnicodeDecodeError):
                    continue
                if not isinstance(data, dict):
                    raise ProviderRequestError('image response must be an object', code='invalid_response')
                event('provider.image_result_received', latency_ms=int((time.monotonic()-started)*1000),
                      bytes=sum(map(len, parts)))
                return data
            raise ProviderRequestError('image response ended without complete JSON', code='invalid_response')
        except requests.RequestException as exc:
            raise ProviderRequestError('image response connection interrupted', code='transport') from exc
        finally:
            response.close()

    def _post(self, url: str, key: str, body: dict[str, Any], timeout: int,
              idempotency_key: str | None) -> dict[str, Any]:
        return self._decode(self._request("POST", url, key, body, timeout, idempotency_key))

    def _request(self, method: str, url: str, key: str, body: dict[str, Any] | None,
                 timeout: int, idempotency_key: str | None, stream: bool = False):
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            response = self.session.request(method, url, headers=headers, json=body,
                                            timeout=timeout, verify=self.verify_ssl, stream=stream)
        except requests.RequestException as exc:
            raise ProviderRequestError(f"provider connection failed: {exc}", code="transport", transient=True) from exc
        if not response.ok:
            try:
                data = response.json()
            except ValueError:
                data = {}
            message = self._error(data) or f"provider HTTP {response.status_code}"
            if response.status_code == 403 and ("IP 不在令牌允许访问" in message or "ip is not allowed" in message.lower()):
                raise ProviderRequestError(message, code="ip_not_allowed", status_code=response.status_code)
            transient = response.status_code in {408, 409, 425, 429} or response.status_code >= 500
            raise ProviderRequestError(message,
                                       code="http_error", transient=transient, status_code=response.status_code)
        return response

    @staticmethod
    def _decode(response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderRequestError("provider returned non-JSON response", code="invalid_response") from exc
        if not isinstance(data, dict):
            raise ProviderRequestError("provider response must be an object", code="invalid_response")
        return data

    @staticmethod
    def _error(data: dict[str, Any]) -> str:
        error = data.get("error")
        return str(error.get("message") or error.get("code") or "") if isinstance(error, dict) else str(error or data.get("message") or "")
