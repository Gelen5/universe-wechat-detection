from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class ProviderRequestError(RuntimeError):
    def __init__(self, message: str, *, code: str = "provider_error", transient: bool = False,
                 status_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.transient = transient
        self.status_code = status_code


@dataclass(frozen=True)
class ToolInvocation:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ProviderResponse:
    text: str = ""
    tool_calls: tuple[ToolInvocation, ...] = ()
    input_tokens: int = 0
    output_tokens: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


class ModelProvider(ABC):
    @abstractmethod
    def create_response(self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None,
                        timeout: int = 120, idempotency_key: str | None = None) -> ProviderResponse:
        raise NotImplementedError

    @abstractmethod
    def generate_image(self, prompt: str, *, size: str, count: int = 1,
                       timeout: int = 300, idempotency_key: str | None = None) -> dict[str, Any]:
        raise NotImplementedError
