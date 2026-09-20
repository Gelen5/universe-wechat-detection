from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import conversation_repository
from .agent_tasks import dispatch_run
from .agent_events import async_client, channel, notify
from .skills.registry import get_registry


router = APIRouter(tags=["conversations"])


class ConversationCreate(BaseModel):
    title: str = Field(default="新对话", max_length=240)
    skill_id: str | None = Field(default=None, max_length=120)
    mode: str = Field(default="auto", pattern="^(auto|manual)$")
    metadata: dict[str, Any] = Field(default_factory=dict)


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=30000)
    content_json: dict[str, Any] = Field(default_factory=dict)


class ArtifactRevisionCreate(BaseModel):
    title: str | None = Field(default=None, max_length=240)
    content: str | None = Field(default=None, max_length=500000)
    content_json: dict[str, Any] | None = None


def _not_found(exc: Exception):
    raise HTTPException(status_code=404, detail="资源不存在或不属于当前用户") from exc


@router.post("/api/conversations", status_code=201)
def create_conversation(payload: ConversationCreate, request: Request):
    if payload.skill_id:
        try:
            get_registry().get(payload.skill_id)
        except KeyError as exc:
            raise HTTPException(status_code=422, detail="未知 Skill") from exc
    if payload.mode == "manual" and not payload.skill_id:
        raise HTTPException(status_code=422, detail="手动模式必须选择 Skill")
    row = conversation_repository.create_conversation(
        request.state.user["id"], title=payload.title, skill_id=payload.skill_id,
        mode=payload.mode, metadata=payload.metadata,
    )
    return {"conversation": row}


@router.get("/api/conversations")
def conversations(request: Request, limit: int = Query(default=50, ge=1, le=100)):
    return {"conversations": conversation_repository.list_conversations(request.state.user["id"], limit=limit)}


@router.get("/api/conversations/{conversation_id}")
def conversation(conversation_id: str, request: Request):
    row = conversation_repository.get_conversation(conversation_id, request.state.user["id"])
    if not row:
        raise HTTPException(status_code=404, detail="对话不存在或不属于当前用户")
    return {"conversation": row}


@router.get("/api/conversations/{conversation_id}/messages")
def messages(conversation_id: str, request: Request, limit: int = Query(default=200, ge=1, le=500)):
    try:
        return {"messages": conversation_repository.list_messages(
            conversation_id, request.state.user["id"], limit=limit)}
    except KeyError as exc:
        _not_found(exc)


@router.post("/api/conversations/{conversation_id}/messages", status_code=202)
def send_message(conversation_id: str, payload: MessageCreate, request: Request,
                 idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    if not idempotency_key or not 8 <= len(idempotency_key) <= 160:
        raise HTTPException(status_code=400, detail="需要 8 到 160 字符的 Idempotency-Key")
    user_id = request.state.user["id"]
    try:
        message, run, replay = conversation_repository.create_message_run(
            conversation_id, user_id, payload.content.strip(), idempotency_key,
            content_json=payload.content_json)
        if not replay:
            dispatch_run(run["id"])
        notify(run["id"])
        return {"message_id": message["id"], "run_id": run["id"],
                "status": run["status"], "idempotent_replay": replay}
    except KeyError as exc:
        _not_found(exc)
    except Exception as exc:
        if "run" in locals() and not replay:
            conversation_repository.transition_run(run["id"], user_id, "failed",
                                                   error_code="enqueue_failed", error_message=str(exc))
        raise HTTPException(status_code=503, detail="任务暂时无法进入队列") from exc


@router.get("/api/runs/{run_id}")
def run_snapshot(run_id: str, request: Request):
    row = conversation_repository.get_run(run_id, request.state.user["id"])
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在或不属于当前用户")
    return {"run": row}


@router.post("/api/runs/{run_id}/cancel", status_code=202)
def cancel(run_id: str, request: Request):
    try:
        row = conversation_repository.cancel_run(run_id, request.state.user["id"])
        notify(run_id)
        return {"run": row}
    except KeyError as exc:
        _not_found(exc)


@router.get("/api/conversations/{conversation_id}/artifacts")
def artifacts(conversation_id: str, request: Request):
    try:
        return {"artifacts": conversation_repository.list_artifacts(conversation_id, request.state.user["id"])}
    except KeyError as exc:
        _not_found(exc)


@router.get("/api/artifacts/{artifact_id}")
def artifact(artifact_id: str, request: Request):
    row = conversation_repository.get_artifact(artifact_id, request.state.user["id"])
    if not row:
        raise HTTPException(status_code=404, detail="作品不存在或不属于当前用户")
    return {"artifact": row}


@router.get("/api/artifacts/{artifact_id}/versions")
def artifact_versions(artifact_id: str, request: Request):
    try:
        return {"artifacts": conversation_repository.list_artifact_versions(
            artifact_id, request.state.user["id"])}
    except KeyError as exc:
        _not_found(exc)


@router.post("/api/artifacts/{artifact_id}/versions", status_code=201)
def create_artifact_version(artifact_id: str, payload: ArtifactRevisionCreate, request: Request):
    if payload.title is None and payload.content is None and payload.content_json is None:
        raise HTTPException(status_code=422, detail="至少提供一项修改内容")
    try:
        row = conversation_repository.create_artifact_version(
            artifact_id, request.state.user["id"], title=payload.title,
            content=payload.content, content_json=payload.content_json,
        )
        notify(row["run_id"])
        return {"artifact": row}
    except KeyError as exc:
        _not_found(exc)


@router.get("/api/runs/{run_id}/events")
async def run_events(run_id: str, request: Request,
                     last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
                     after: int = Query(default=0, ge=0)):
    user_id = request.state.user["id"]
    if not conversation_repository.get_run(run_id, user_id):
        raise HTTPException(status_code=404, detail="任务不存在或不属于当前用户")
    try:
        cursor = max(after, int(last_event_id or 0))
    except ValueError:
        cursor = after

    async def generate():
        nonlocal cursor
        redis = async_client()
        pubsub = redis.pubsub()
        subscribed = False
        try:
            yield "retry: 2000\n\n"
            while not await request.is_disconnected():
                rows = await asyncio.to_thread(conversation_repository.events_after,
                                               run_id, user_id, cursor, 200)
                for event in rows:
                    cursor = event["id"]
                    payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                    yield f"id: {cursor}\nevent: {event['type']}\ndata: {payload}\n\n"
                run = await asyncio.to_thread(conversation_repository.get_run, run_id, user_id)
                if run and run["status"] in {"completed", "failed", "cancelled"} and len(rows) < 200:
                    break
                if not subscribed:
                    try:
                        await asyncio.wait_for(pubsub.subscribe(channel(run_id)), timeout=1)
                        subscribed = True
                    except Exception:
                        subscribed = False
                if subscribed:
                    try:
                        await pubsub.get_message(ignore_subscribe_messages=True, timeout=10)
                    except Exception:
                        subscribed = False
                else:
                    await asyncio.sleep(1)
                yield ": heartbeat\n\n"
        finally:
            try:
                if subscribed:
                    await pubsub.unsubscribe(channel(run_id))
                await pubsub.aclose()
                await redis.aclose()
            except Exception:
                pass

    return StreamingResponse(generate(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    })
