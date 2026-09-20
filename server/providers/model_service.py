from __future__ import annotations

from typing import Any

from .base import ModelProvider, ProviderResponse


class ModelService:
    def __init__(self, text_provider: ModelProvider, image_provider: ModelProvider | None = None):
        self.text_provider = text_provider
        self.image_provider = image_provider or text_provider

    def create_response(self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None,
                        timeout: int = 120, idempotency_key: str | None = None) -> ProviderResponse:
        return self.text_provider.create_response(messages, tools=tools, timeout=timeout,
                                                  idempotency_key=idempotency_key)

    def generate_image(self, prompt: str, *, size: str, count: int = 1,
                       timeout: int = 300, idempotency_key: str | None = None) -> dict[str, Any]:
        return self.image_provider.generate_image(prompt, size=size, count=count, timeout=timeout,
                                                  idempotency_key=idempotency_key)
