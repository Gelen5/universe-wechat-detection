from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


# User-facing text for an upstream failure. Operators get the status code and
# body in the log; the person using the product gets an actionable line instead
# of a credential and IP-allowlist checklist they cannot act on.
USER_UNAVAILABLE_MESSAGE = "模型服务暂时不可用，请稍后重试。本次任务未完成，不会扣除积分。"


def unavailable(status: Any) -> bool:
    """Whether a provider status is an outage rather than a request mistake."""
    try:
        code = int(status)
    except (TypeError, ValueError):
        return False
    return code == 429 or code >= 500


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
