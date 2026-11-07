"""Celery entry point for standalone de-AI rewrite jobs."""
from __future__ import annotations

import json
import logging
import time

from .celery_app import celery_app
from . import accounts, deai, workbench


@celery_app.task(
    bind=True,
    name="deai.run",
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=900,
    time_limit=960,
)
def run(self, job_id: str):
    existing = accounts.job(job_id)
    if not existing or existing.get("type") != deai.TASK_TYPE:
        return {"status": "ignored"}
    if existing.get("status") in {"succeeded", "failed", "canceled"}:
        deai.settle(existing, elapsed_ms=0, success=existing.get("status") == "succeeded")
        return {"status": existing.get("status")}
    job = accounts.claim_job([deai.LANE], job_id)
    if not job:
        return {"status": "ignored"}
    started = time.monotonic()
    try:
        payload = json.loads(job.get("payload_json") or "{}")
        with workbench.provider_overrides():
            result = deai.run_job(job_id, payload)
    except Exception as exc:  # noqa: BLE001 - worker must settle and refund
        logging.getLogger(__name__).exception("deai job failed: %s", job_id)
        accounts.fail_job(job_id, str(exc)[:300] or "去 AI 味失败")
        current = accounts.job(job_id) or job
        deai.settle(current, elapsed_ms=int((time.monotonic() - started) * 1000), success=False)
        return {"status": "failed"}
    accounts.finish_job(job_id, result)
    current = accounts.job(job_id) or job
    deai.settle(
        current,
        elapsed_ms=int((time.monotonic() - started) * 1000),
        success=current.get("status") == "succeeded",
    )
    return {"status": current.get("status")}
