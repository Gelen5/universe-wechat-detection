"""Deprecation gate for the creator workbench APIs replaced by conversations.

The browser already speaks only to ``/api/conversations``: the normalized
workbench client captures every workbench control in the capture phase and
cancels propagation, and the legacy controls ``app.js`` binds (``#open-preview``,
``#run-next``, ``#publish-draft``) no longer exist in ``index.html``. The legacy
routes therefore stay reachable only so an old cached page cannot break.

``LEGACY_WORKBENCH_MODE`` decides what they do:

- ``open`` (default) answers normally and emits ``legacy.route_hit`` so
  production logs can prove whether anything still calls them.
- ``gone`` answers 410 and emits ``legacy.route_blocked``; no points are
  reserved because the gate runs before the billing rule lookup.

An unrecognised value falls back to ``open``: a typo must not silently disable
a route that a stale client might still need.
"""
from __future__ import annotations

import os

MODES = ("open", "gone")
DEFAULT_MODE = "open"

# Prefixes cover every route mounted by main.py and workflow_api; the exact
# entry is the collection POST that carries no trailing slash.
PREFIXES = ("/api/workbench/", "/api/workflows/")
EXACT = ("/api/workflows",)


def mode() -> str:
    """Current gate mode; read per request so tests and ops can flip it."""
    value = (os.getenv("LEGACY_WORKBENCH_MODE") or DEFAULT_MODE).strip().lower()
    return value if value in MODES else DEFAULT_MODE


def matches(path: str) -> bool:
    """Whether this request path belongs to a superseded workbench API."""
    return path in EXACT or path.startswith(PREFIXES)
