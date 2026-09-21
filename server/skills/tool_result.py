from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ArtifactOutput:
    type: str
    title: str = ""
    content: str = ""
    content_json: dict[str, Any] = field(default_factory=dict)
    storage_url: str | None = None


@dataclass(frozen=True)
class ToolResult:
    data: dict[str, Any]
    artifacts: tuple[ArtifactOutput, ...] = ()
    usage: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def coerce(cls, value: Any) -> "ToolResult":
        if isinstance(value, cls):
            return value
        if isinstance(value, dict):
            return cls(data=value)
        return cls(data={"value": value})

