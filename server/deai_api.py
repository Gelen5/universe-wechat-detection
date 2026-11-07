"""HTTP interface for the standalone de-AI rewrite tool."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import accounts, deai

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/deai", tags=["deai"])


class CreateDeaiTask(BaseModel):
    content: str = Field(min_length=20, max_length=deai.MAX_CHARS)
    mode: str = Field(default="article", pattern="^(article|novel)$")
    depth: int = Field(default=5, ge=1, le=10)
    version: str = Field(default="V3.1", pattern="^(V2|V3\\.1)$")
    idempotency_key: str = Field(min_length=8, max_length=120)


def _existing(user_id: str, request_id: str) -> dict | None:
    with accounts.DB_LOCK, accounts._connect() as connection:
        row = connection.execute(
            "SELECT * FROM jobs WHERE user_id=? AND idempotency_key=?",
            (user_id, f"deai:{user_id}:{request_id}"),
        ).fetchone()
    return dict(row) if row else None


def _dispatch(job: dict) -> None:
    if job.get("status") != "queued":
        return
    try:
        deai.dispatch(job["id"])
    except Exception:
        logger.exception("deai dispatch failed: %s", job.get("id"))


def _settle_terminal(job: dict) -> dict:
    if job.get("status") in {"succeeded", "failed", "canceled"} and job.get("usage_id"):
        deai.settle(job, elapsed_ms=0, success=job.get("status") == "succeeded")
        return accounts.job(job["id"], job.get("user_id")) or job
    return job


@router.post("/tasks", status_code=202)
def create_task(payload: CreateDeaiTask, request: Request):
    user = accounts.require_user(request)
    existing = _existing(user["id"], payload.idempotency_key)
    if existing:
        _dispatch(existing)
        return {"job": deai.public(_settle_terminal(existing))}
    try:
        job = deai.submit(
            user["id"],
            request_id=payload.idempotency_key,
            content=payload.content,
            mode=payload.mode,
            depth=payload.depth,
            version=payload.version,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _dispatch(job)
    return {"job": deai.public(job)}


@router.get("/tasks")
def list_tasks(request: Request, limit: int = 30):
    user = accounts.require_user(request)
    limit = max(1, min(int(limit), 100))
    with accounts.DB_LOCK, accounts._connect() as connection:
        rows = connection.execute(
            "SELECT * FROM jobs WHERE user_id=? AND type=? "
            "ORDER BY created_at DESC,id DESC LIMIT ?",
            (user["id"], deai.TASK_TYPE, limit),
        ).fetchall()
    jobs = [_settle_terminal(dict(row)) for row in rows]
    return {"jobs": [deai.public(job) for job in jobs]}


@router.get("/tasks/{task_id}")
def get_task(task_id: str, request: Request):
    user = accounts.require_user(request)
    job = accounts.job(task_id, user["id"])
    if not job or job.get("type") != deai.TASK_TYPE:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"job": deai.public(_settle_terminal(job))}


@router.post("/tasks/{task_id}/cancel")
def cancel_task(task_id: str, request: Request):
    user = accounts.require_user(request)
    job = accounts.job(task_id, user["id"])
    if not job or job.get("type") != deai.TASK_TYPE:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.get("status") in {"succeeded", "failed", "canceled"}:
        return {"job": deai.public(_settle_terminal(job))}
    canceled = accounts.cancel_job(task_id, user["id"]) or job
    if canceled.get("status") == "canceled" and job.get("usage_id"):
        accounts.refund_usage(job["usage_id"], 499, 0)
        canceled = accounts.job(task_id, user["id"]) or canceled
    return {"job": deai.public(canceled)}
