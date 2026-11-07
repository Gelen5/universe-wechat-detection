"""Durable Celery entry point for the AI video factory."""
from __future__ import annotations

import logging
import os
import threading
import time

from celery.exceptions import SoftTimeLimitExceeded

from . import accounts
from .celery_app import celery_app
from .video_factory_pipeline import PendingTask
from .video_factory_service import run_plan


logger = logging.getLogger(__name__)
POLL_SECONDS = 10
SLOT_PREFIX = "video_factory"
SLOT_SECONDS = 1800


def _slot_limit() -> int:
    try:
        return max(1, int(os.getenv("VIDEO_FACTORY_MAX_CONCURRENT", "1")))
    except ValueError:
        return 1


@celery_app.task(bind=True, name="video_factory.run", acks_late=True,
                 max_retries=3,
                 reject_on_worker_lost=True, soft_time_limit=3600, time_limit=3660)
def run_video_factory(self, job_id: str):
    job = accounts.job(job_id)
    if not job or job.get("type") != "video_factory":
        return {"status": "ignored", "reason": "unknown job"}
    if job["status"] == "queued":
        claimed = accounts.claim_job([job.get("lane") or "image"], job_id=job_id)
        if not claimed:
            return {"status": "ignored", "reason": "already claimed"}
        job = claimed
    elif job["status"] != "running":
        return {"status": "ignored", "reason": job["status"]}
    started = time.monotonic()
    try:
        token, slot_state = accounts.acquire_job_slot(
            SLOT_PREFIX, job_id, _slot_limit(), SLOT_SECONDS
        )
    except Exception as exc:
        if self.request.retries >= 3:
            failure = "视频任务排队失败，积分已退回"
            accounts.fail_job(job_id, failure)
            if job.get("usage_id"):
                accounts.refund_usage(job["usage_id"], 503, 0)
            return {"status": "failed", "error": failure}
        # A queue publication can race the database; a database outage must
        # also fail closed rather than silently starting unbounded renders.
        raise self.retry(exc=exc, countdown=min(60, 2 ** self.request.retries * 10))
    if not token:
        if slot_state == "same_job":
            return {"status": "ignored", "reason": "already active"}
        accounts.progress_job(job_id, step="queued_for_slot")
        return {"status": "deferred", "reason": "video factory concurrency limit"}
    stopped = threading.Event()

    def renew_slot():
        while not stopped.wait(SLOT_SECONDS // 3):
            try:
                if not accounts.renew_job_slot(SLOT_PREFIX, job_id, token, SLOT_SECONDS):
                    logger.error("video factory slot lease was lost: %s", job_id)
                    stopped.set()
            except Exception:
                logger.exception("failed to renew video factory slot: %s", job_id)
                stopped.set()

    keeper = threading.Thread(target=renew_slot, name=f"video-slot-{job_id[:8]}", daemon=True)
    keeper.start()

    def progress(step: str):
        accounts.progress_job(job_id, step=step, elapsed_seconds=round(time.monotonic() - started, 1))
        current = accounts.job(job_id)
        if current and current.get("canceled_at"):
            raise RuntimeError("任务已取消")

    failure = None
    try:
        while True:
            if stopped.is_set():
                raise RuntimeError("视频任务执行锁已失效，请检查服务状态")
            try:
                result = run_plan(job, progress)
                break
            except PendingTask as exc:
                time.sleep(exc.retry_after or POLL_SECONDS)
        accounts.finish_job(job_id, result)
        if job.get("usage_id"):
            accounts.settle_usage(job["usage_id"], 200, int((time.monotonic() - started) * 1000))
    except SoftTimeLimitExceeded:
        failure = "视频生成超过时间限制，已停止"
    except Exception as exc:  # noqa: BLE001 - persist a user-safe error
        logger.exception("video factory job failed: %s", job_id)
        failure = str(exc)[-500:] or "视频生成失败"
    finally:
        stopped.set()
        keeper.join(timeout=5)
        accounts.release_job_slot(job_id, token)
    if failure:
        current = accounts.job(job_id) or job
        if current.get("canceled_at"):
            accounts.mark_job_canceled(job_id)
        else:
            accounts.fail_job(job_id, failure)
        if job.get("usage_id"):
            accounts.refund_usage(job["usage_id"], 500, int((time.monotonic() - started) * 1000))
        return {"status": "failed", "error": failure}
    return {"status": "completed", "job_id": job_id}


@celery_app.task(name="video_factory.recover")
def recover_video_factory():
    """Recover queued submissions; retry deferred jobs when a slot frees."""
    rows = accounts.list_jobs(limit=100)
    recovered = 0
    for job in rows:
        if (job.get("type") != "video_factory"
                or job.get("status") not in {"queued", "running"}):
            continue
        if (job["status"] == "running"
                and "queued_for_slot" not in (job.get("result_json") or "")):
            continue
        if job["status"] == "queued":
            claimed = accounts.claim_job(["image"], job_id=job["id"])
            if not claimed:
                continue
        run_video_factory.apply_async(args=[job["id"]], queue="video_factory")
        recovered += 1
    return {"recovered": recovered}
