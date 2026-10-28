"""Scheduled text-provider health check.

The relay serving every writing node answered 502 for hours and nothing
noticed: the only probe ran during deployment. This task probes the configured
text model on a beat schedule and logs one structured event per run, so an
outage is visible in the logs (and alertable) instead of surfacing as user
complaints.

It reuses ``scripts/node_model_probe.py`` because that script already knows how
the app resolves the stored provider settings.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .celery_app import celery_app
from .observability import event as log_event

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "scripts" / "node_model_probe.py"


def probe_text_provider(timeout: int = 240) -> dict:
    """Run the configured-model probe and return a small, speakable result."""
    try:
        done = subprocess.run([sys.executable, str(PROBE)], cwd=str(ROOT),
                              capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "detail": f"probe timed out after {timeout}s"}
    except OSError as exc:
        return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"[:300]}
    detail = ((done.stdout or "") + (done.stderr or "")).strip()
    return {"ok": done.returncode == 0, "detail": detail[-800:]}


@celery_app.task(name="provider.health")
def provider_health() -> dict:
    result = probe_text_provider()
    log_event("provider.health", ok=result["ok"], detail=result["detail"])
    if not result["ok"]:
        # A separate event name so an alert rule can target outages only.
        log_event("provider.outage", detail=result["detail"])
    return result


def interval_seconds() -> float:
    try:
        return max(60.0, float(os.getenv("PROVIDER_HEALTH_INTERVAL", "600")))
    except (TypeError, ValueError):
        return 600.0
