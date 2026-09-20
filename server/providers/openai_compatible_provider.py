from __future__ import annotations

import json
import time
from typing import Any

import requests

from .base import ModelProvider, ProviderRequestError, ProviderResponse, ToolInvocation


class OpenAICompatibleProvider(ModelProvider):
    def __init__(self, *, api_key: str, base_url: str, text_model: str,
                 image_api_key: str | None = None, image_base_url: str | None = None,
                 image_model: str | None = None, verify_ssl: bool = True,
                 session: requests.Session | None = None):
        self.api_key = api_key
        self.base_url = self._v1(base_url)
        self.text_model = text_model
        self.image_api_key = image_api_key or api_key
        self.image_base_url = self._v1(image_base_url or base_url)
        self.image_model = image_model or "gpt-image-2"
        self.verify_ssl = verify_ssl
        self.session = session or requests.Session()
        self.session.trust_env = False

    @staticmethod
    def _v1(value: str) -> str:
        base = value.strip().rstrip("/")
        return base if base.endswith("/v1") else base + "/v1"

    def create_response(self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None,
                        timeout: int = 120, idempotency_key: str | None = None) -> ProviderResponse:
        body: dict[str, Any] = {"model": self.text_model, "messages": messages}
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

    def generate_image(self, prompt: str, *, size: str, count: int = 1,
                       timeout: int = 300, idempotency_key: str | None = None) -> dict[str, Any]:
        if not prompt.strip():
            raise ProviderRequestError("image prompt is required", code="invalid_request")
        data = self._post(self.image_base_url + "/images/generations", self.image_api_key,
                          {"model": self.image_model, "prompt": prompt, "size": size, "n": count},
                          min(timeout, 180), idempotency_key)
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

    def _post(self, url: str, key: str, body: dict[str, Any], timeout: int,
              idempotency_key: str | None) -> dict[str, Any]:
        return self._decode(self._request("POST", url, key, body, timeout, idempotency_key))

    def _request(self, method: str, url: str, key: str, body: dict[str, Any] | None,
                 timeout: int, idempotency_key: str | None):
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            response = self.session.request(method, url, headers=headers, json=body,
                                            timeout=timeout, verify=self.verify_ssl)
        except requests.RequestException as exc:
            raise ProviderRequestError(f"provider connection failed: {exc}", code="transport", transient=True) from exc
        if not response.ok:
            try:
                data = response.json()
            except ValueError:
                data = {}
            transient = response.status_code in {408, 409, 425, 429} or response.status_code >= 500
            raise ProviderRequestError(self._error(data) or f"provider HTTP {response.status_code}",
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
