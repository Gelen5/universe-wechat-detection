"""Ambient attribution for legacy provider calls made inside tool execution.

Several legacy workbench helpers (``workbench._text`` and friends) build their
own ``ModelService`` and know nothing about the Run that triggered them, so
their provider spend never lands on that Run's cost record. Rather than
rewriting every call site, the tool loop binds this context around
``tool.invoke`` and the legacy helpers read it when they build their client.

The context is also where the executor's deadline is published, so nested
provider requests can shrink their own timeout instead of outliving the Run
budget.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable

_CURRENT: ContextVar[dict[str, Any] | None] = ContextVar("provider_call_context", default=None)


def current() -> dict[str, Any]:
    """Return the active attribution context, or an empty mapping."""
    return _CURRENT.get() or {}


@contextmanager
def bind(*, run_id: str | None = None, user_id: str | None = None,
         usage_recorder: Callable[[dict[str, Any]], None] | None = None,
         cost_policy: Any = None, idempotency_key: str | None = None,
         deadline: float | None = None, is_cancelled: Callable[[], bool] | None = None):
    value = {
        "run_id": run_id,
        "user_id": user_id,
        "usage_recorder": usage_recorder,
        "cost_policy": cost_policy,
        "idempotency_key": idempotency_key,
        "deadline": deadline,
        "is_cancelled": is_cancelled,
    }
    token = _CURRENT.set(value)
    try:
        yield value
    finally:
        _CURRENT.reset(token)


def remaining_seconds(default: int | None = None) -> int | None:
    """Seconds left before the Run deadline, or ``default`` when unbound."""
    deadline = current().get("deadline")
    if deadline is None:
        return default
    return max(0, int(deadline - time.monotonic()))
