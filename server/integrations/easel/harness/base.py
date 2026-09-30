from __future__ import annotations

from typing import Any, Protocol

from ..native.skill_loader import NativeSkill
from .schemas import EaselExecutionResult, RunContext


class EaselHarness(Protocol):
    async def execute(self, *, run_context: RunContext, skill: NativeSkill,
                      input_data: str, profile: dict[str, Any],
                      attachments: list[dict[str, Any]], tools: dict[str, Any]) -> EaselExecutionResult: ...

    async def cancel(self, execution_id: str) -> bool: ...

    async def health(self) -> dict[str, Any]: ...
