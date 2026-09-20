from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ToolManifest:
    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SkillManifest:
    id: str
    name: str
    version: str
    description: str
    capabilities: tuple[str, ...]
    tools: tuple[ToolManifest, ...]
    root: Path
    manifest_path: Path
    pricing: dict[str, Any] = field(default_factory=dict)
    model_policy: dict[str, Any] = field(default_factory=dict)
    limits: dict[str, Any] = field(default_factory=dict)
    trusted: bool = True

    def router_summary(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "description": self.description,
                "capabilities": list(self.capabilities)}
