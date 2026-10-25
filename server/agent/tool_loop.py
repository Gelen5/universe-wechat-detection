from __future__ import annotations

import json
import hashlib
import inspect
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from jsonschema import Draft202012Validator

from .. import conversation_repository
from ..agent_events import notify
from ..providers import ModelService
from ..providers import call_context
from ..skills.executor import ToolContext, ToolExecutor
from ..skills.tool_result import ToolResult
from ..storage import get_storage


def _heartbeat_interval() -> float:
    """How often the lease supervisor renews a run while a tool blocks.

    The stale-run scan default is 720s, so renewing every 60s by default keeps
    a healthy but slow tool far away from being mistaken for a dead worker.
    """
    try:
        return max(5.0, float(os.getenv("AGENT_HEARTBEAT_INTERVAL", "60") or 60))
    except ValueError:
        return 60.0


class _HeartbeatSupervisor:
    """Renew the run lease on its own thread while a blocking tool runs.

    Heartbeating only before and after ``tool.invoke`` means a tool that spends
    minutes inside provider calls looks identical to a crashed worker. The
    recovery scan then re-dispatches the same Run, and both attempts can reach
    the provider, so the work is paid for twice. A worker-owned renewal loop
    keeps the lease truthful regardless of what the tool is doing.
    """

    def __init__(self, heartbeat: Callable[[], bool], interval: float | None = None):
        self._heartbeat = heartbeat
        self._interval = _heartbeat_interval() if interval is None else interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.lost = False

    def __enter__(self) -> "_HeartbeatSupervisor":
        if self._interval > 0:
            self._thread = threading.Thread(
                target=self._run, name="run-heartbeat", daemon=True)
            self._thread.start()
        return self

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                if not self._heartbeat():
                    self.lost = True
                    return
            except Exception:  # a failing renewal must not kill the tool
                self.lost = True
                return

    def __exit__(self, *exc_info) -> bool:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        return False


@dataclass(frozen=True)
class ExecutableTool:
    definition: dict[str, Any]
    execute: ToolExecutor
    side_effect: str = "none"
    requires_confirmation: bool = False

    def invoke(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        parameters = inspect.signature(self.execute).parameters
        value = self.execute(arguments, context) if len(parameters) >= 2 else self.execute(arguments)
        return ToolResult.coerce(value)


def run_tool_loop(*, model_service: ModelService, messages: list[dict[str, Any]], tools: dict[str, ExecutableTool],
                  run_id: str, user_id: str, skill_id: str, max_tool_calls: int,
                  timeout_seconds: int, is_cancelled: Callable[[], bool] = lambda: False,
                  heartbeat: Callable[[], bool] = lambda: True,
                  on_tool_result: Callable[[ToolResult, str], dict[str, Any] | None] | None = None,
                  required_tool: str | None = None) -> str:
    started = time.monotonic()
    deadline = started + timeout_seconds
    definitions = [tool.definition for tool in tools.values()]
    calls = 0
    validation_failures = 0
    required_attempts = 0
    required_called = False
    while True:
        if is_cancelled():
            raise RuntimeError("run cancelled")
        if time.monotonic() - started > timeout_seconds:
            raise TimeoutError("agent tool loop timed out")
        if not heartbeat():
            raise RuntimeError("run execution lease changed")
        remaining = max(1, int(timeout_seconds - (time.monotonic() - started)))
        request_hash = hashlib.sha256(json.dumps(
            {"messages": messages, "tools": definitions}, ensure_ascii=False,
            sort_keys=True, separators=(",", ":"), default=str,
        ).encode()).hexdigest()[:24]
        model_key = f"{run_id}:model:{calls + 1}:{request_hash}"
        provider_timeout = max(10, int(os.getenv("AGENT_PROVIDER_REQUEST_TIMEOUT", "240") or 240))
        response = model_service.create_response(messages, tools=definitions,
                                                 timeout=min(provider_timeout, remaining), idempotency_key=model_key,
                                                 run_id=run_id, user_id=user_id)
        if not heartbeat():
            raise RuntimeError("run execution lease changed")
        if not response.tool_calls:
            if required_tool and not required_called:
                required_attempts += 1
                if required_attempts > 1:
                    raise RuntimeError(f"required stage tool was not called: {required_tool}")
                messages.append({"role": "system", "content":
                    f"本阶段尚未执行。必须先调用 {required_tool} 工具，不能直接回复。"})
                continue
            return response.text
        for call in response.tool_calls:
            calls += 1
            if calls > max_tool_calls:
                raise RuntimeError("maximum tool calls exceeded")
            tool = tools.get(call.name)
            if not tool:
                validation_failures += 1
                messages.append({"role": "assistant", "content": "", "tool_calls": [{
                    "id": call.id, "type": "function", "function": {"name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=False)}}]})
                messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps({
                    "error": "unknown_tool", "allowed_tools": sorted(tools),
                }, ensure_ascii=False)})
                if validation_failures > 2:
                    raise ValueError(f"Skill attempted unknown tool repeatedly: {call.name}")
                continue
            schema = tool.definition.get("parameters") or {"type": "object"}
            errors = sorted(Draft202012Validator(schema).iter_errors(call.arguments),
                            key=lambda item: list(item.absolute_path))
            if errors:
                validation_failures += 1
                details = [{"path": ".".join(map(str, error.absolute_path)),
                            "message": error.message} for error in errors]
                messages.append({"role": "assistant", "content": "", "tool_calls": [{
                    "id": call.id, "type": "function", "function": {"name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=False)}}]})
                messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps({
                    "error": "validation_error", "details": details,
                }, ensure_ascii=False)})
                if validation_failures > 2:
                    raise ValueError(f"tool arguments remain invalid after correction: {details}")
                continue
            canonical = json.dumps(call.arguments, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":"), default=str)
            argument_hash = hashlib.sha256(canonical.encode()).hexdigest()[:24]
            logical_key = f"{run_id}:tool:{calls}:{call.name}:{argument_hash}"
            record, replay = conversation_repository.create_tool_call(
                run_id, user_id, call_id=call.id, skill_id=skill_id,
                tool_name=call.name, arguments=call.arguments, idempotency_key=logical_key,
            )
            notify(run_id)
            if replay and record["status"] == "completed":
                result = record["result"]
            else:
                try:
                    if is_cancelled():
                        raise RuntimeError("run cancelled")
                    run = conversation_repository.get_run(run_id, user_id)
                    context = ToolContext(
                        user_id=user_id, conversation_id=run["conversation_id"], run_id=run_id,
                        skill_id=skill_id, tool_call_id=record["id"], idempotency_key=logical_key,
                        storage=get_storage(), model_service=model_service,
                        emit=lambda event, payload: conversation_repository.record_run_event(
                            run_id, user_id, event, payload),
                        is_cancelled=is_cancelled,
                        heartbeat=heartbeat,
                        remaining_seconds=lambda: max(0, int(
                            timeout_seconds - (time.monotonic() - started))),
                    )
                    if time.monotonic() >= deadline:
                        raise TimeoutError("agent tool loop deadline exceeded before tool start")
                    if not heartbeat():
                        raise RuntimeError("run execution lease changed")
                    with call_context.bind(
                        run_id=run_id, user_id=user_id,
                        usage_recorder=getattr(model_service, "usage_recorder", None),
                        cost_policy=getattr(model_service, "cost_policy", None),
                        idempotency_key=logical_key, deadline=deadline,
                    ):
                        with _HeartbeatSupervisor(heartbeat) as supervisor:
                            structured = tool.invoke(call.arguments, context)
                    if supervisor.lost:
                        raise RuntimeError("run execution lease changed")
                    result = structured.data
                    if is_cancelled():
                        raise RuntimeError("run cancelled")
                    if not heartbeat():
                        raise RuntimeError("run execution lease changed")
                    if on_tool_result:
                        replacement = on_tool_result(structured, record["id"])
                        if replacement is not None:
                            result = replacement
                    conversation_repository.finish_tool_call(record["id"], run_id, user_id, result=result)
                    notify(run_id)
                except Exception as exc:
                    conversation_repository.finish_tool_call(record["id"], run_id, user_id, error=str(exc))
                    notify(run_id)
                    raise
            if call.name == required_tool:
                if time.monotonic() > deadline:
                    raise TimeoutError("agent tool loop timed out after required tool")
                required_called = True
                return "当前阶段已完成，请查看作品区。"
            messages.append({"role": "assistant", "content": "", "tool_calls": [{
                "id": call.id, "type": "function", "function": {"name": call.name,
                "arguments": json.dumps(call.arguments, ensure_ascii=False)}}]})
            messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, ensure_ascii=False)})
