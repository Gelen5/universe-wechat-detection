from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class RunContext:
    user_id: str
    run_id: str
    conversation_id: str
    workspace: Path
    output_dir: Path
    timeout_seconds: int = 300
    history: list[dict[str, Any]] = field(default_factory=list)
    is_cancelled: Callable[[], bool] = lambda: False
    heartbeat: Callable[[], bool] = lambda: True


@dataclass(frozen=True)
class EaselExecutionResult:
    execution_id: str
    status: str
    text: str = ""
    artifacts: tuple[dict[str, Any], ...] = ()
    error: str | None = None
