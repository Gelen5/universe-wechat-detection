from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .base import ModelProvider, ProviderResponse


@dataclass(frozen=True)
class ProviderCostPolicy:
    input_micros_per_million_tokens: int = 0
    output_micros_per_million_tokens: int = 0
    image_micros_each: int = 0

    def text_cost(self, input_tokens: int, output_tokens: int) -> int:
        return max(0, (
            input_tokens * self.input_micros_per_million_tokens
            + output_tokens * self.output_micros_per_million_tokens
        ) // 1_000_000)


class ModelService:
    def __init__(self, text_provider: ModelProvider, image_provider: ModelProvider | None = None,
                 usage_recorder=None, cost_policy: ProviderCostPolicy | None = None):
        self.text_provider = text_provider
        self.image_provider = image_provider or text_provider
        self.usage_recorder = usage_recorder
        self.cost_policy = cost_policy or ProviderCostPolicy()

    def create_response(self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None,
                        timeout: int = 120, idempotency_key: str | None = None,
                        run_id: str | None = None, user_id: str | None = None) -> ProviderResponse:
        started = time.monotonic()
        response = self.text_provider.create_response(
            messages, tools=tools, timeout=timeout, idempotency_key=idempotency_key)
        if self.usage_recorder and run_id and user_id:
            self.usage_recorder({
                "run_id": run_id, "user_id": user_id,
                "provider": type(self.text_provider).__name__,
                "model": getattr(self.text_provider, "text_model", "unknown"),
                "input_tokens": response.input_tokens, "output_tokens": response.output_tokens,
                "image_count": 0, "latency_ms": int((time.monotonic() - started) * 1000),
                "estimated_cost_micros": self.cost_policy.text_cost(
                    response.input_tokens, response.output_tokens,
                ),
            })
        return response

    def generate_image(self, prompt: str, *, size: str, count: int = 1,
                       timeout: int = 300, idempotency_key: str | None = None,
                       run_id: str | None = None, user_id: str | None = None) -> dict[str, Any]:
        started = time.monotonic()
        result = self.image_provider.generate_image(
            prompt, size=size, count=count, timeout=timeout, idempotency_key=idempotency_key)
        if self.usage_recorder and run_id and user_id:
            self.usage_recorder({
                "run_id": run_id, "user_id": user_id,
                "provider": type(self.image_provider).__name__,
                "model": getattr(self.image_provider, "image_model", "unknown"),
                "input_tokens": 0, "output_tokens": 0, "image_count": count,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "estimated_cost_micros": max(0, count * self.cost_policy.image_micros_each),
            })
        return result
