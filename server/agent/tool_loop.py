from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable

from .. import conversation_repository
from ..agent_events import notify
from ..providers import ModelService


@dataclass(frozen=True)
class ExecutableTool:
    definition: dict[str, Any]
    execute: Callable[[dict[str, Any]], dict[str, Any]]


def run_tool_loop(*, model_service: ModelService, messages: list[dict[str, Any]], tools: dict[str, ExecutableTool],
                  run_id: str, user_id: str, skill_id: str, max_tool_calls: int,
                  timeout_seconds: int, is_cancelled: Callable[[], bool] = lambda: False,
                  on_tool_result: Callable[[str, dict[str, Any], str], dict[str, Any] | None] | None = None) -> str:
    started = time.monotonic()
    definitions = [tool.definition for tool in tools.values()]
    calls = 0
    while True:
        if is_cancelled():
            raise RuntimeError("run cancelled")
        if time.monotonic() - started > timeout_seconds:
            raise TimeoutError("agent tool loop timed out")
        response = model_service.create_response(messages, tools=definitions,
                                                 timeout=min(120, timeout_seconds), idempotency_key=run_id,
                                                 run_id=run_id, user_id=user_id)
        if not response.tool_calls:
            return response.text
        for call in response.tool_calls:
            calls += 1
            if calls > max_tool_calls:
                raise RuntimeError("maximum tool calls exceeded")
            tool = tools.get(call.name)
            if not tool:
                raise ValueError(f"Skill attempted unknown tool: {call.name}")
            record, replay = conversation_repository.create_tool_call(
                run_id, user_id, call_id=call.id, skill_id=skill_id,
                tool_name=call.name, arguments=call.arguments,
            )
            notify(run_id)
            if replay and record["status"] == "completed":
                result = record["result"]
            else:
                try:
                    result = tool.execute(call.arguments)
                    conversation_repository.finish_tool_call(record["id"], run_id, user_id, result=result)
                    notify(run_id)
                except Exception as exc:
                    conversation_repository.finish_tool_call(record["id"], run_id, user_id, error=str(exc))
                    notify(run_id)
                    raise
            if on_tool_result:
                replacement = on_tool_result(call.name, result, record["id"])
                if replacement is not None and replacement != result:
                    result = replacement
                    conversation_repository.replace_tool_call_result(
                        record["id"], run_id, user_id, result,
                    )
            messages.append({"role": "assistant", "content": "", "tool_calls": [{
                "id": call.id, "type": "function", "function": {"name": call.name,
                "arguments": json.dumps(call.arguments, ensure_ascii=False)}}]})
            messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, ensure_ascii=False)})
