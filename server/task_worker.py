"""Persistent, lane-limited worker for the creator workbench beta queue."""
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from . import accounts, creator_tools, workbench


LANES = {"diagnose": 1, "text": 2, "image": 1, "light": 3}


def _payload(job: dict[str, Any]) -> dict[str, Any]:
    return json.loads(job.get("payload_json") or "{}")


def execute(job: dict[str, Any]) -> dict[str, Any]:
    """Run a task with explicit payload and ContextVar-scoped provider settings."""
    payload = _payload(job)
    kind = job["type"]
    if kind == "xiaohongshu":
        with workbench.provider_overrides():
            package = creator_tools.xiaohongshu_package(**payload)
            package["precheck"] = creator_tools.xiaohongshu_precheck(package.get("selected_title") or payload["topic"], package.get("body") or "")
            return {"status": "success", "package": package}
    if kind == "tie_tu":
        with workbench.provider_overrides():
            return {"status": "success", "plan": creator_tools.tie_tu_plan(**payload)}
    if kind == "hit_detect":
        return {"status": "success", "report": creator_tools.detect_article(**payload)}
    if kind == "hit_rewrite":
        with workbench.provider_overrides():
            return {"status": "success", "article": creator_tools.rewrite_article(**payload)}
    if kind == "creator_image":
        with workbench.provider_overrides():
            return {"status": "success", "image": creator_tools.generate_card_image(**payload)}
    if kind == "workbench":
        with workbench.provider_overrides():
            session = workbench.create(payload["topic"], payload["mode"], payload["persona"], payload["theme"], user_id=job["user_id"], session_id=payload["session_id"])
            return {"status": "success", "session": session}
    raise ValueError(f"未知任务类型：{kind}")


def _run(job: dict[str, Any]) -> None:
    started = time.perf_counter()
    try:
        result = execute(job)
        accounts.finish_job(job["id"], result)
        if job.get("usage_id"):
            accounts.settle_usage(job["usage_id"], 200, int((time.perf_counter() - started) * 1000))
    except Exception as exc:
        accounts.fail_job(job["id"], str(exc))
        if job.get("usage_id"):
            accounts.refund_usage(job["usage_id"], 500, int((time.perf_counter() - started) * 1000))


def serve(poll_seconds: float = 0.5) -> None:
    accounts.init_db()
    accounts.recover_interrupted_jobs()
    executors = {lane: ThreadPoolExecutor(max_workers=count, thread_name_prefix=f"creator-{lane}") for lane, count in LANES.items()}
    active: dict[str, set] = {lane: set() for lane in LANES}
    while True:
        for lane, executor in executors.items():
            active[lane] = {future for future in active[lane] if not future.done()}
            while len(active[lane]) < LANES[lane]:
                job = accounts.claim_job([lane])
                if not job:
                    break
                active[lane].add(executor.submit(_run, job))
        time.sleep(poll_seconds)


if __name__ == "__main__":
    serve(float(os.getenv("CREATOR_WORKER_POLL_SECONDS", "0.5")))
