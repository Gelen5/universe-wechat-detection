"""爆文复刻 HTTP 接口。

接口层只负责鉴权、参数校验、幂等重放和取消；积分预扣、失败退款由
viral_article.submit/settle 在后台任务生命周期内完成，避免与全局计费
中间件重复扣费。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import accounts, viral_article

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/viral-article", tags=["viral-article"])


class CreateViralArticleTask(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=viral_article.MAX_URLS)
    remove_ai_flavor: bool = True
    new_angle: str = Field(default="", max_length=300)
    target_characters: int | None = Field(default=None, ge=200, le=10000)
    idempotency_key: str = Field(min_length=8, max_length=120)


def _existing_job(user_id: str, request_id: str) -> dict | None:
    key = f"viral-article:{user_id}:{request_id}"
    with accounts.DB_LOCK, accounts._connect() as connection:
        row = connection.execute(
            "SELECT * FROM jobs WHERE user_id=? AND idempotency_key=?",
            (user_id, key),
        ).fetchone()
    return dict(row) if row else None


def _same_payload(job: dict, *, urls: list[str], remove_ai_flavor: bool,
                  new_angle: str, target_characters: int | None) -> bool:
    import json

    try:
        prior = json.loads(job.get("payload_json") or "{}")
    except (TypeError, ValueError):
        return False
    return (
        prior.get("urls") == urls
        and bool(prior.get("remove_ai_flavor", True)) == bool(remove_ai_flavor)
        and str(prior.get("new_angle") or "") == new_angle
        and prior.get("target_characters") == target_characters
    )


def _dispatch(job: dict) -> None:
    if job.get("status") != "queued":
        return
    try:
        viral_article.dispatch(job["id"])
    except Exception:
        # Keep the queued job visible; a later duplicate submit can redispatch.
        logger.exception("viral article dispatch failed: %s", job.get("id"))


def _settle_terminal(job: dict) -> dict:
    """Repair a terminal job whose worker died before settling its usage row."""
    if job.get("status") in {"succeeded", "failed", "canceled"} and job.get("usage_id"):
        viral_article.settle(
            job,
            elapsed_ms=0,
            success=job.get("status") == "succeeded",
        )
        return accounts.job(job["id"], job.get("user_id")) or job
    return job


@router.post("/tasks", status_code=202)
def create_task(payload: CreateViralArticleTask, request: Request):
    user = accounts.require_user(request)
    try:
        urls = viral_article.extract_urls(payload.urls)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    new_angle = payload.new_angle.strip()
    existing = _existing_job(user["id"], payload.idempotency_key)
    if existing:
        if existing.get("type") != viral_article.TASK_TYPE or not _same_payload(
            existing,
            urls=urls,
            remove_ai_flavor=payload.remove_ai_flavor,
            new_angle=new_angle,
            target_characters=payload.target_characters,
        ):
            raise HTTPException(status_code=409, detail="任务编号与提交内容不匹配")
        _dispatch(existing)
        return {"job": viral_article.public(_settle_terminal(existing))}

    try:
        job = viral_article.submit(
            user["id"],
            request_id=payload.idempotency_key,
            urls=urls,
            remove_ai_flavor=payload.remove_ai_flavor,
            new_angle=new_angle,
            target_characters=payload.target_characters,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _dispatch(job)
    return {"job": viral_article.public(job)}


@router.get("/tasks")
def list_tasks(request: Request, limit: int = 30):
    user = accounts.require_user(request)
    limit = max(1, min(int(limit), 100))
    with accounts.DB_LOCK, accounts._connect() as connection:
        rows = connection.execute(
            "SELECT * FROM jobs WHERE user_id=? AND type=? "
            "ORDER BY created_at DESC,id DESC LIMIT ?",
            (user["id"], viral_article.TASK_TYPE, limit),
        ).fetchall()
    jobs = [_settle_terminal(dict(row)) for row in rows]
    return {"jobs": [viral_article.public(job) for job in jobs]}


@router.get("/tasks/{task_id}")
def get_task(task_id: str, request: Request):
    user = accounts.require_user(request)
    job = accounts.job(task_id, user["id"])
    if not job or job.get("type") != viral_article.TASK_TYPE:
        raise HTTPException(status_code=404, detail="任务不存在")
    job = _settle_terminal(job)
    return {"job": viral_article.public(job)}


@router.post("/tasks/{task_id}/cancel")
def cancel_task(task_id: str, request: Request):
    user = accounts.require_user(request)
    job = accounts.job(task_id, user["id"])
    if not job or job.get("type") != viral_article.TASK_TYPE:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.get("status") in {"succeeded", "failed", "canceled"}:
        return {"job": viral_article.public(_settle_terminal(job))}
    if job.get("status") == "running" and job.get("canceled_at"):
        return {"job": viral_article.public(job)}
    canceled = accounts.cancel_job(task_id, user["id"]) or job
    # A queued job never entered the worker, so it can be refunded immediately.
    if canceled.get("status") == "canceled" and job.get("usage_id"):
        accounts.refund_usage(job["usage_id"], 499, 0)
        canceled = accounts.job(task_id, user["id"]) or canceled
    return {"job": viral_article.public(canceled)}


class UpdateResultBody(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=100000)


@router.put("/tasks/{task_id}/result")
def update_result(task_id: str, payload: UpdateResultBody, request: Request):
    """Save a manual edit without charging again or discarding source evidence."""
    import json

    user = accounts.require_user(request)
    job = accounts.job(task_id, user["id"])
    if not job or job.get("type") != viral_article.TASK_TYPE:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.get("status") != "succeeded":
        raise HTTPException(status_code=409, detail="任务尚未完成，不能保存修改")
    try:
        result = json.loads(job.get("result_json") or "{}")
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="任务结果不可编辑") from exc
    result["title"] = payload.title.strip()
    result["content"] = payload.content.strip()
    result["results"] = [{"content": result["content"]}]
    result["edited_at"] = accounts.utc_now()
    with accounts.DB_LOCK, accounts._connect() as connection:
        connection.execute(
            "UPDATE jobs SET result_json=? WHERE id=? AND user_id=? AND status='succeeded'",
            (json.dumps(result, ensure_ascii=False), task_id, user["id"]),
        )
    current = accounts.job(task_id, user["id"]) or job
    return {"job": viral_article.public(current)}
