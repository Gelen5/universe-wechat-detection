"""Authenticated user-facing API for the AI video factory."""
from __future__ import annotations

import json
import os
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field

from . import accounts, storage
from .video_factory_service import enabled, points


router = APIRouter(prefix="/api/video-factory", tags=["video-factory"])
CATEGORIES = ("book", "history", "folklore", "china")
VOICES = (
    {"id": "zh-CN-XiaoxiaoNeural-Female", "label": "晓晓 · 女声"},
    {"id": "zh-CN-YunxiNeural-Male", "label": "云希 · 男声"},
    {"id": "zh-CN-YunjianNeural-Male", "label": "云健 · 男声"},
)
ASSET_NAMES = {"video", "cover", "captions", "script", "storyboard", "sources", "quality", "cost"}


class SourceInput(BaseModel):
    url: str = Field(pattern=r"^https://", max_length=300)
    summary: str = Field(min_length=20, max_length=6000)


class CreateVideoJob(BaseModel):
    category: str = Field(pattern="^(book|history|folklore|china)$")
    topic: str = Field(min_length=1, max_length=120)
    duration: Literal[30, 45, 60] = 30
    visual_style: str = Field(default="auto", pattern="^(auto|chinese|hand_drawn|photo)$")
    voice_id: str = Field(
        default="zh-CN-XiaoxiaoNeural-Female",
        pattern="^(zh-CN-XiaoxiaoNeural-Female|zh-CN-YunxiNeural-Male|zh-CN-YunjianNeural-Male)$",
    )
    sources: list[SourceInput] = Field(default_factory=list, max_length=8)
    idempotency_key: str = Field(min_length=8, max_length=120)


def _require_enabled():
    if not enabled():
        raise HTTPException(503, "AI 视频工厂尚未开放")


def _job(job_id: str, request: Request) -> dict[str, Any]:
    job = accounts.job(job_id, request.state.user["id"])
    if not job or job.get("type") != "video_factory":
        raise HTTPException(404, "任务不存在或不属于当前用户")
    return job


def _public(job: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(job.get("result_json") or "{}") if job.get("result_json") else None
    if job.get("status") == "running" and isinstance(result, dict) and result.get("progress"):
        result = {"progress": result["progress"]}
    if isinstance(result, dict):
        result = {
            key: value for key, value in result.items()
            if key not in {"assets", "video", "cover"}
        }
    return {
        "id": job["id"], "type": job["type"], "status": job["status"],
        "error": job.get("error"), "created_at": job.get("created_at"),
        "started_at": job.get("started_at"), "finished_at": job.get("finished_at"),
        "result": result,
    }


@router.get("/config")
def config():
    return {"enabled": enabled(), "points": points(), "categories": CATEGORIES, "voices": VOICES}


@router.post("/jobs", status_code=202)
def create_job(payload: CreateVideoJob, request: Request):
    _require_enabled()
    user = request.state.user
    if payload.duration > int(os.getenv("VIDEO_FACTORY_MAX_DURATION_SEC", "60")):
        raise HTTPException(422, "目标时长超过服务上限")
    price = points()
    usage_id = accounts.reserve_points(
        user["id"], {"points": price, "feature": "AI 视频工厂"}, "POST", "/api/video-factory/jobs",
    )
    try:
        job = accounts.create_job(
            user["id"], "video_factory", "image", payload.idempotency_key, usage_id,
            payload.model_dump(exclude={"idempotency_key"}),
        )
    except Exception:
        accounts.refund_usage(usage_id, 500, 0)
        raise
    if job.get("usage_id") != usage_id:
        accounts.refund_usage(usage_id, 409, 0)
    if job["status"] == "queued":
        from .video_factory_tasks import run_video_factory
        try:
            run_video_factory.apply_async(args=[job["id"]], queue="video_factory")
        except Exception as exc:
            accounts.fail_job(job["id"], "任务提交失败，请稍后重试")
            if job.get("usage_id") == usage_id:
                accounts.refund_usage(usage_id, 503, 0)
            raise HTTPException(503, "任务提交失败，请稍后重试") from exc
    return {"status": "accepted", "job": _public(job), "estimated_points": price}


@router.get("/jobs")
def list_jobs(request: Request):
    _require_enabled()
    rows = accounts.list_jobs(limit=100, user_id=request.state.user["id"])
    return {"jobs": [_public(row) for row in rows if row.get("type") == "video_factory"]}


@router.get("/jobs/{job_id}")
def job_status(job_id: str, request: Request):
    _require_enabled()
    return {"job": _public(_job(job_id, request))}


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, request: Request):
    _require_enabled()
    job = _job(job_id, request)
    if job["status"] != "queued":
        raise HTTPException(409, "任务已经开始，当前渲染器不支持中途取消")
    updated = accounts.cancel_job(job_id, request.state.user["id"])
    if updated and updated["status"] == "canceled" and updated.get("usage_id"):
        accounts.refund_usage(updated["usage_id"], 499, 0)
    return {"job": _public(updated or job)}


@router.get("/jobs/{job_id}/assets/{name}")
def asset(job_id: str, name: str, request: Request):
    _require_enabled()
    if name not in ASSET_NAMES:
        raise HTTPException(404, "成果不存在")
    job = _job(job_id, request)
    result = json.loads(job.get("result_json") or "{}")
    item = (result.get("assets") or {}).get(name)
    if not item or not item.get("key"):
        raise HTTPException(404, "成果尚未生成")
    provider = storage.get_storage()
    try:
        local = provider.local_path(item["key"])
    except (FileNotFoundError, NotImplementedError):
        local = None
    if local:
        headers = {"Cache-Control": "private, no-store"}
        if request.query_params.get("download") == "1":
            headers["Content-Disposition"] = f'attachment; filename="{name}"'
        return FileResponse(local, media_type=item.get("content_type") or "application/octet-stream",
                            headers=headers)
    return RedirectResponse(provider.get_url(item["key"]), status_code=307,
                            headers={"Cache-Control": "private, no-store"})
