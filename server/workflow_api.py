"""Authenticated workflow API and resumable SSE stream."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import accounts
from .workflow_events import allow_user_request, async_client, channel, notify
from .workflow_repository import (
    change_mode, events_after, fail_workflow, get_workflow, invalidate_from, next_node,
    record_decision, request_cancel, retry_failed,
)
from .workflow_tasks import dispatch_node
from .workflow_billing import InsufficientPoints, create_billed_workflow


router = APIRouter(prefix="/api/workflows", tags=["workflows"])


class WorkflowCreate(BaseModel):
    topic: str = Field(default="", max_length=240)
    mode: str = Field(default="interactive", pattern="^(auto|interactive)$")
    persona: str = Field(default="深度观察者", max_length=80)
    theme: str = Field(default="default", max_length=80)
    idempotency_key: str = Field(min_length=8, max_length=120)


class WorkflowDecisionBody(BaseModel):
    node: str = Field(pattern="^(topic|strategy|visual)$")
    expected_version: int = Field(ge=1)
    decision: dict[str, Any] = Field(default_factory=dict)


class WorkflowModeBody(BaseModel):
    mode: str = Field(pattern="^(auto|interactive)$")
    expected_version: int = Field(ge=1)


class WorkflowEditBody(BaseModel):
    restart_from: str = Field(pattern="^(topic|research|strategy|draft|review|visual|delivery)$")
    expected_version: int = Field(ge=1)
    state_patch: dict[str, Any] = Field(default_factory=dict)


def _not_found(exc: Exception):
    raise HTTPException(status_code=404, detail="任务不存在或不属于当前用户") from exc


@router.post("", status_code=202)
def start_workflow(payload: WorkflowCreate, request: Request):
    user_id = request.state.user["id"]
    if not allow_user_request(user_id):
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")
    try:
        existing, replay = create_billed_workflow(
            user_id, payload.idempotency_key, payload.mode,
            {"topic": payload.topic, "persona": payload.persona, "theme": payload.theme},
        )
        if replay:
            return {"status": "accepted", "workflow": existing, "idempotent_replay": True}
        dispatch_node(existing["id"], "intent")
        notify(existing["id"])
    except InsufficientPoints as exc:
        raise HTTPException(status_code=402, detail=f"积分不足：需要 {exc.required} 积分，当前剩余 {exc.balance} 积分") from exc
    except HTTPException:
        raise
    except Exception as exc:
        if 'existing' in locals() and existing and not replay:
            failed = fail_workflow(existing["id"], "intent", f"任务调度失败：{exc}")
            if failed.get("usage_id"):
                accounts.refund_usage(failed["usage_id"], 503, 0)
        raise HTTPException(status_code=503, detail="任务暂时无法调度，积分已退还") from exc
    current = get_workflow(existing["id"], user_id)
    return {"status": "accepted", "workflow": current, "idempotent_replay": False}


@router.get("/{workflow_id}")
def workflow_snapshot(workflow_id: str, request: Request):
    workflow = get_workflow(workflow_id, request.state.user["id"])
    if not workflow:
        raise HTTPException(status_code=404, detail="任务不存在或不属于当前用户")
    return {"status": "success", "workflow": workflow}


@router.post("/{workflow_id}/decisions", status_code=202)
def decide_workflow(workflow_id: str, payload: WorkflowDecisionBody, request: Request):
    try:
        workflow = record_decision(workflow_id, request.state.user["id"], payload.node,
                                   payload.expected_version, payload.decision)
        following = next_node(payload.node)
        if following:
            dispatch_node(workflow_id, following)
        notify(workflow_id)
        return {"status": "accepted", "workflow": workflow}
    except KeyError as exc:
        _not_found(exc)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{workflow_id}/cancel", status_code=202)
def cancel_workflow(workflow_id: str, request: Request):
    try:
        workflow = request_cancel(workflow_id, request.state.user["id"])
        if workflow["status"] == "cancelled" and workflow.get("usage_id"):
            accounts.refund_usage(workflow["usage_id"], 499, 0)
        notify(workflow_id)
        return {"status": "accepted", "workflow": workflow}
    except KeyError as exc:
        _not_found(exc)


@router.post("/{workflow_id}/retry", status_code=202)
def retry_workflow(workflow_id: str, request: Request):
    try:
        workflow, node = retry_failed(workflow_id, request.state.user["id"])
        dispatch_node(workflow_id, node)
        notify(workflow_id)
        return {"status": "accepted", "workflow": workflow}
    except KeyError as exc:
        _not_found(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{workflow_id}/mode")
def switch_mode(workflow_id: str, payload: WorkflowModeBody, request: Request):
    try:
        workflow = change_mode(workflow_id, request.state.user["id"], payload.mode, payload.expected_version)
        if payload.mode == "auto" and workflow["status"] == "awaiting_input":
            checkpoint = workflow["current_node"]
            workflow = record_decision(workflow_id, request.state.user["id"], checkpoint,
                                       workflow["version"], {}, actor="auto")
            following = next_node(checkpoint)
            if following:
                dispatch_node(workflow_id, following)
        notify(workflow_id)
        return {"status": "success", "workflow": workflow}
    except KeyError as exc:
        _not_found(exc)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{workflow_id}/edit", status_code=202)
def edit_workflow(workflow_id: str, payload: WorkflowEditBody, request: Request):
    try:
        workflow = invalidate_from(workflow_id, request.state.user["id"], payload.restart_from,
                                   payload.state_patch, payload.expected_version)
        dispatch_node(workflow_id, payload.restart_from)
        notify(workflow_id)
        return {"status": "accepted", "workflow": workflow}
    except KeyError as exc:
        _not_found(exc)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{workflow_id}/events")
async def stream_events(workflow_id: str, request: Request,
                        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
                        after: int = Query(default=0, ge=0)):
    user_id = request.state.user["id"]
    if not get_workflow(workflow_id, user_id):
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
            rows = await asyncio.to_thread(events_after, workflow_id, user_id, cursor, 200)
            for event in rows:
                cursor = event["id"]
                payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                yield f"id: {cursor}\nevent: {event['type']}\ndata: {payload}\n\n"
            try:
                await asyncio.wait_for(pubsub.subscribe(channel(workflow_id)), timeout=1)
                subscribed = True
            except Exception:
                subscribed = False
            while not await request.is_disconnected():
                rows = await asyncio.to_thread(events_after, workflow_id, user_id, cursor, 200)
                for event in rows:
                    cursor = event["id"]
                    payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                    yield f"id: {cursor}\nevent: {event['type']}\ndata: {payload}\n\n"
                if subscribed:
                    try:
                        await pubsub.get_message(ignore_subscribe_messages=True, timeout=10)
                    except Exception:
                        subscribed = False
                else:
                    await asyncio.sleep(1)
                yield ": heartbeat\n\n"
        finally:
            if subscribed:
                await pubsub.unsubscribe(channel(workflow_id))
            await pubsub.close()
            await redis.close()

    return StreamingResponse(generate(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    })
