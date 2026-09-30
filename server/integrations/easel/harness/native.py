from __future__ import annotations

import asyncio
from typing import Any

from ....agent.tool_loop import ExecutableTool, run_tool_loop
from ....providers import ModelService
from ..native.prompt_builder import build_messages
from ..native.skill_loader import NativeSkill
from .schemas import EaselExecutionResult, RunContext


class UniverseNativeHarness:
    """Runs Skill instructions through the existing Universe provider/tool loop."""

    def __init__(self, model_service: ModelService):
        self.model_service = model_service
        self._cancelled: set[str] = set()

    async def execute(self, *, run_context: RunContext, skill: NativeSkill,
                      input_data: str, profile: dict[str, Any],
                      attachments: list[dict[str, Any]],
                      tools: dict[str, ExecutableTool]) -> EaselExecutionResult:
        if attachments:
            raise ValueError("Native Easel attachments require an approved adapter")
        context = {"run_id": run_context.run_id, "conversation_id": run_context.conversation_id,
                   "workspace": str(run_context.workspace), "output_dir": str(run_context.output_dir)}
        messages = build_messages(skill=skill, user_text=input_data, profile=profile,
                                  run_context=context, history=run_context.history)
        answer = await asyncio.to_thread(
            run_tool_loop, model_service=self.model_service, messages=messages, tools=tools,
            run_id=run_context.run_id, user_id=run_context.user_id, skill_id=f"easel:{skill.id}",
            max_tool_calls=12, timeout_seconds=run_context.timeout_seconds,
            is_cancelled=lambda: run_context.run_id in self._cancelled or run_context.is_cancelled(),
            heartbeat=run_context.heartbeat,
        )
        return EaselExecutionResult(run_context.run_id, "completed", text=answer)

    async def cancel(self, execution_id: str) -> bool:
        self._cancelled.add(execution_id)
        return True

    async def health(self) -> dict[str, Any]:
        return {"status": "ready", "harness": "native"}
