from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..providers import ModelService
from ..storage import StorageProvider
from .tool_result import ToolResult


@dataclass(frozen=True)
class ToolContext:
    user_id: str
    conversation_id: str
    run_id: str
    skill_id: str
    tool_call_id: str
    idempotency_key: str
    storage: StorageProvider
    model_service: ModelService
    emit: Callable[[str, dict[str, Any]], None]
    is_cancelled: Callable[[], bool]
    heartbeat: Callable[[], bool]
    remaining_seconds: Callable[[], int]


ToolExecutor = Callable[[dict[str, Any], ToolContext], ToolResult]
