"""爆文复刻的 Celery 任务入口。

抓取、重写、去 AI 味和结算都在 viral_article 中完成；这里只负责把
queued 任务原子地 claim 成 running，并把最终状态落库。
"""
from __future__ import annotations

import json
import logging
import time

from .celery_app import celery_app
from . import accounts, viral_article, workbench


@celery_app.task(
    bind=True,
    name="viral_article.run",
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=900,
    time_limit=960,
)
def run(self, job_id: str):
    existing = accounts.job(job_id)
    if not existing or existing.get("type") != viral_article.TASK_TYPE:
        return {"status": "ignored"}
    # A duplicate delivery must not reserve or settle twice.  If a previous
    # delivery wrote a terminal status but crashed before settlement, settle
    # here; both settle paths are idempotent on usage_records.status.
    if existing.get("status") in {"succeeded", "failed", "canceled"}:
        viral_article.settle(
            existing,
            elapsed_ms=0,
            success=existing.get("status") == "succeeded",
        )
        return {"status": existing.get("status")}
    job = accounts.claim_job([viral_article.LANE], job_id)
    if not job:
        return {"status": "ignored"}

    started = time.monotonic()
    try:
        payload = json.loads(job.get("payload_json") or "{}")
        with workbench.provider_overrides():
            result = viral_article.run_job(job_id, payload)
    except viral_article.JobCancelled:
        accounts.mark_job_canceled(job_id)
        current = accounts.job(job_id) or job
        viral_article.settle(
            current,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            success=False,
        )
        return {"status": "canceled"}
    except Exception as exc:  # noqa: BLE001 - worker must always settle
        logging.getLogger(__name__).exception("viral article job failed: %s", job_id)
        error = str(exc)[:300] or "爆文复刻失败"
        accounts.fail_job(job_id, error)
        current = accounts.job(job_id) or job
        viral_article.settle(
            current,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            success=False,
        )
        return {"status": "failed"}

    accounts.finish_job(job_id, result)
    # cancel_job can set canceled_at while the last provider call is returning.
    # Re-read before settling so a canceled job is never charged as success.
    current = accounts.job(job_id) or job
    if current.get("status") == "succeeded":
        viral_article.settle(
            current,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            success=True,
        )
        return {"status": "succeeded"}
    accounts.mark_job_canceled(job_id)
    current = accounts.job(job_id) or current
    viral_article.settle(
        current,
        elapsed_ms=int((time.monotonic() - started) * 1000),
        success=False,
    )
    return {"status": "canceled"}
