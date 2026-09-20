"""Transactional persistence for the normalized chat and artifact core."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .database import session_scope
from .models import AgentRun, Artifact, Conversation, ConversationMessage, ProviderCall, ToolCall


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_conversation(user_id: str, *, title: str = "新对话", skill_id: str | None = None,
                        mode: str = "auto", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    if mode not in {"auto", "manual"}:
        raise ValueError("mode must be auto or manual")
    if mode == "manual" and not skill_id:
        raise ValueError("manual mode requires skill_id")
    with session_scope() as db:
        row = Conversation(id=uuid.uuid4().hex, user_id=user_id, title=title.strip() or "新对话",
                           skill_id=skill_id, mode=mode, metadata_json=metadata or {})
        db.add(row)
        db.flush()
        return _conversation_view(row)


def get_conversation(conversation_id: str, user_id: str) -> dict[str, Any] | None:
    with session_scope() as db:
        row = db.scalar(select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id,
        ))
        return _conversation_view(row) if row else None


def list_conversations(user_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    with session_scope() as db:
        rows = db.scalars(select(Conversation).where(
            Conversation.user_id == user_id,
        ).order_by(Conversation.updated_at.desc()).limit(min(max(limit, 1), 100))).all()
        return [_conversation_view(row) for row in rows]


def add_message(conversation_id: str, user_id: str, role: str, content: str, *,
                content_json: dict[str, Any] | None = None,
                metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    if role not in {"user", "assistant", "tool", "system"}:
        raise ValueError("unsupported message role")
    with session_scope() as db:
        conversation = db.scalar(select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id,
        ).with_for_update())
        if not conversation:
            raise KeyError("conversation not found")
        now = _now()
        row = ConversationMessage(id=uuid.uuid4().hex, conversation_id=conversation_id,
                                  role=role, content=content, content_json=content_json or {},
                                  metadata_json=metadata or {}, created_at=now)
        conversation.updated_at = now
        db.add(row)
        db.flush()
        return _message_view(row)


def list_messages(conversation_id: str, user_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
    with session_scope() as db:
        owner = db.scalar(select(Conversation.id).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id,
        ))
        if not owner:
            raise KeyError("conversation not found")
        rows = db.scalars(select(ConversationMessage).where(
            ConversationMessage.conversation_id == conversation_id,
        ).order_by(ConversationMessage.created_at, ConversationMessage.id).limit(min(max(limit, 1), 500))).all()
        return [_message_view(row) for row in rows]


def create_run(conversation_id: str, user_id: str, trigger_message_id: str,
               idempotency_key: str, *, skill_id: str | None = None,
               usage_id: str | None = None) -> tuple[dict[str, Any], bool]:
    try:
        with session_scope() as db:
            existing = db.scalar(select(AgentRun).where(
                AgentRun.user_id == user_id, AgentRun.idempotency_key == idempotency_key,
            ))
            if existing:
                return _run_view(existing), True
            conversation = db.scalar(select(Conversation).where(
                Conversation.id == conversation_id, Conversation.user_id == user_id,
            ))
            message = db.scalar(select(ConversationMessage).where(
                ConversationMessage.id == trigger_message_id,
                ConversationMessage.conversation_id == conversation_id,
            ))
            if not conversation or not message or message.role != "user":
                raise KeyError("conversation or trigger message not found")
            row = AgentRun(id=uuid.uuid4().hex, conversation_id=conversation_id,
                           trigger_message_id=trigger_message_id, user_id=user_id,
                           skill_id=skill_id or conversation.skill_id,
                           idempotency_key=idempotency_key, usage_id=usage_id)
            db.add(row)
            db.flush()
            return _run_view(row), False
    except IntegrityError:
        with session_scope() as db:
            row = db.scalar(select(AgentRun).where(
                AgentRun.user_id == user_id, AgentRun.idempotency_key == idempotency_key,
            ))
            if not row:
                raise
            return _run_view(row), True


def create_message_run(conversation_id: str, user_id: str, content: str,
                       idempotency_key: str, *, content_json: dict[str, Any] | None = None,
                       metadata: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any], bool]:
    """Atomically persist one user message and its Run under one idempotency key."""
    try:
        with session_scope() as db:
            existing = db.scalar(select(AgentRun).where(
                AgentRun.user_id == user_id, AgentRun.idempotency_key == idempotency_key,
            ))
            if existing:
                message = db.get(ConversationMessage, existing.trigger_message_id)
                return _message_view(message), _run_view(existing), True
            conversation = db.scalar(select(Conversation).where(
                Conversation.id == conversation_id, Conversation.user_id == user_id,
            ).with_for_update())
            if not conversation:
                raise KeyError("conversation not found")
            now = _now()
            message = ConversationMessage(id=uuid.uuid4().hex, conversation_id=conversation_id,
                role="user", content=content, content_json=content_json or {},
                metadata_json=metadata or {}, created_at=now)
            run = AgentRun(id=uuid.uuid4().hex, conversation_id=conversation_id,
                trigger_message_id=message.id, user_id=user_id, skill_id=conversation.skill_id,
                idempotency_key=idempotency_key, status="queued", created_at=now, updated_at=now)
            conversation.updated_at = now
            db.add_all((message, run))
            db.flush()
            return _message_view(message), _run_view(run), False
    except IntegrityError:
        with session_scope() as db:
            run = db.scalar(select(AgentRun).where(
                AgentRun.user_id == user_id, AgentRun.idempotency_key == idempotency_key,
            ))
            if not run:
                raise
            message = db.get(ConversationMessage, run.trigger_message_id)
            return _message_view(message), _run_view(run), True


def get_run(run_id: str, user_id: str) -> dict[str, Any] | None:
    with session_scope() as db:
        row = db.scalar(select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user_id))
        return _run_view(row) if row else None


def transition_run(run_id: str, user_id: str, status: str, *, error_code: str | None = None,
                   error_message: str | None = None, task_id: str | None = None) -> dict[str, Any]:
    allowed = {"queued", "running", "waiting_input", "completed", "failed", "cancelled"}
    if status not in allowed:
        raise ValueError("invalid run status")
    with session_scope() as db:
        row = db.scalar(select(AgentRun).where(
            AgentRun.id == run_id, AgentRun.user_id == user_id,
        ).with_for_update())
        if not row:
            raise KeyError("run not found")
        if task_id is not None and row.celery_task_id != task_id:
            raise RuntimeError("run execution lease changed")
        now = _now()
        if row.status in {"completed", "failed", "cancelled"} and row.status != status:
            raise ValueError("terminal run cannot transition")
        row.status, row.updated_at = status, now
        row.error_code, row.error_message = error_code, error_message
        if status == "running":
            row.started_at = row.started_at or now
        if status in {"completed", "failed", "cancelled"}:
            row.finished_at = row.finished_at or now
            row.heartbeat_at = now
        return _run_view(row)


def claim_run(run_id: str, task_id: str) -> dict[str, Any] | None:
    """Atomically claim a queued Run; duplicate Celery deliveries return None."""
    with session_scope() as db:
        row = db.scalar(select(AgentRun).where(AgentRun.id == run_id).with_for_update())
        if not row or row.status != "queued":
            return None
        now = _now()
        row.status, row.started_at, row.updated_at = "running", row.started_at or now, now
        row.celery_task_id, row.heartbeat_at = task_id, now
        row.attempt += 1
        return _run_view(row)


def heartbeat_run(run_id: str, task_id: str) -> bool:
    with session_scope() as db:
        row = db.scalar(select(AgentRun).where(AgentRun.id == run_id).with_for_update())
        if not row or row.status != "running" or row.celery_task_id != task_id:
            return False
        row.heartbeat_at = row.updated_at = _now()
        return True


def run_lease_owned(run_id: str, task_id: str) -> bool:
    with session_scope() as db:
        return bool(db.scalar(select(AgentRun.id).where(
            AgentRun.id == run_id, AgentRun.status == "running", AgentRun.celery_task_id == task_id,
        )))


def recover_stale_runs(stale_seconds: int = 720) -> list[str]:
    cutoff = _now() - timedelta(seconds=max(60, stale_seconds))
    recovered: list[str] = []
    with session_scope() as db:
        rows = db.scalars(select(AgentRun).where(
            AgentRun.status == "running", AgentRun.heartbeat_at < cutoff,
        ).with_for_update(skip_locked=True)).all()
        for row in rows:
            row.status, row.celery_task_id = "queued", None
            row.error_code, row.error_message = "worker_lost", "stale worker execution recovered"
            row.updated_at = _now()
            recovered.append(row.id)
    return recovered


def cancel_run(run_id: str, user_id: str) -> dict[str, Any]:
    with session_scope() as db:
        row = db.scalar(select(AgentRun).where(
            AgentRun.id == run_id, AgentRun.user_id == user_id,
        ).with_for_update())
        if not row:
            raise KeyError("run not found")
        if row.status in {"completed", "failed", "cancelled"}:
            return _run_view(row)
        now = _now()
        row.status, row.finished_at, row.updated_at, row.heartbeat_at = "cancelled", now, now, now
        row.celery_task_id = None
        return _run_view(row)


def list_artifacts(conversation_id: str, user_id: str) -> list[dict[str, Any]]:
    with session_scope() as db:
        owner = db.scalar(select(Conversation.id).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id,
        ))
        if not owner:
            raise KeyError("conversation not found")
        rows = db.scalars(select(Artifact).where(
            Artifact.conversation_id == conversation_id, Artifact.user_id == user_id,
        ).order_by(Artifact.type, Artifact.version)).all()
        return [_artifact_view(row) for row in rows]


def create_tool_call(run_id: str, user_id: str, *, call_id: str, skill_id: str | None,
                     tool_name: str, arguments: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    key = f"{run_id}:{call_id}"
    try:
        with session_scope() as db:
            run = db.scalar(select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user_id))
            if not run:
                raise KeyError("run not found")
            existing = db.scalar(select(ToolCall).where(ToolCall.idempotency_key == key))
            if existing:
                return _tool_call_view(existing), True
            row = ToolCall(id=uuid.uuid4().hex, run_id=run_id, skill_id=skill_id,
                           tool_name=tool_name, idempotency_key=key,
                           arguments_json=arguments, result_json={}, status="running", started_at=_now())
            db.add(row)
            db.flush()
            return _tool_call_view(row), False
    except IntegrityError:
        with session_scope() as db:
            row = db.scalar(select(ToolCall).where(ToolCall.idempotency_key == key))
            if not row:
                raise
            return _tool_call_view(row), True


def finish_tool_call(tool_call_id: str, run_id: str, user_id: str, *,
                     result: dict[str, Any] | None = None, error: str | None = None) -> dict[str, Any]:
    with session_scope() as db:
        row = db.scalar(select(ToolCall).join(AgentRun, AgentRun.id == ToolCall.run_id).where(
            ToolCall.id == tool_call_id, ToolCall.run_id == run_id, AgentRun.user_id == user_id,
        ).with_for_update())
        if not row:
            raise KeyError("tool call not found")
        if row.status in {"completed", "failed", "cancelled"}:
            return _tool_call_view(row)
        row.status = "failed" if error else "completed"
        row.result_json = result or {}
        row.error_message = error
        row.finished_at = _now()
        return _tool_call_view(row)


def create_artifact(run_id: str, user_id: str, artifact_type: str, *, title: str = "",
                    content: str = "", content_json: dict[str, Any] | None = None,
                    storage_key: str | None = None, storage_url: str | None = None) -> dict[str, Any]:
    with session_scope() as db:
        run = db.scalar(select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user_id).with_for_update())
        if not run:
            raise KeyError("run not found")
        version = (db.scalar(select(func.max(Artifact.version)).where(
            Artifact.conversation_id == run.conversation_id, Artifact.type == artifact_type,
        )) or 0) + 1
        row = Artifact(id=uuid.uuid4().hex, user_id=user_id, conversation_id=run.conversation_id,
                       run_id=run_id, type=artifact_type, title=title, content=content,
                       content_json=content_json or {}, storage_key=storage_key,
                       storage_url=storage_url, version=version)
        db.add(row)
        db.flush()
        return _artifact_view(row)


def record_provider_call(run_id: str, user_id: str, *, provider: str, model: str,
                         tool_call_id: str | None = None, input_tokens: int = 0,
                         output_tokens: int = 0, image_count: int = 0,
                         latency_ms: int | None = None,
                         estimated_cost_micros: int = 0) -> dict[str, Any]:
    with session_scope() as db:
        run = db.scalar(select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user_id).with_for_update())
        if not run:
            raise KeyError("run not found")
        if tool_call_id and not db.scalar(select(ToolCall.id).where(ToolCall.id == tool_call_id, ToolCall.run_id == run_id)):
            raise KeyError("tool call not found")
        row = ProviderCall(id=uuid.uuid4().hex, provider=provider, model=model,
                           input_tokens=input_tokens, output_tokens=output_tokens,
                           image_count=image_count, latency_ms=latency_ms,
                           estimated_cost_micros=estimated_cost_micros,
                           run_id=run_id, tool_call_id=tool_call_id, user_id=user_id)
        run.provider_cost_micros += estimated_cost_micros
        db.add(row)
        db.flush()
        return {"id": row.id, "run_id": run_id, "provider": provider, "model": model,
                "estimated_cost_micros": estimated_cost_micros}


def _conversation_view(row: Conversation) -> dict[str, Any]:
    return {"id": row.id, "user_id": row.user_id, "title": row.title, "skill_id": row.skill_id,
            "mode": row.mode, "status": row.status, "metadata": row.metadata_json,
            "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat()}


def _message_view(row: ConversationMessage) -> dict[str, Any]:
    return {"id": row.id, "conversation_id": row.conversation_id, "role": row.role,
            "content": row.content, "content_json": row.content_json,
            "metadata": row.metadata_json, "created_at": row.created_at.isoformat()}


def _run_view(row: AgentRun) -> dict[str, Any]:
    return {"id": row.id, "conversation_id": row.conversation_id,
            "trigger_message_id": row.trigger_message_id, "user_id": row.user_id,
            "skill_id": row.skill_id, "status": row.status, "usage_id": row.usage_id,
            "cost_points": row.cost_points, "provider_cost_micros": row.provider_cost_micros,
            "celery_task_id": row.celery_task_id, "attempt": row.attempt,
            "heartbeat_at": row.heartbeat_at.isoformat() if row.heartbeat_at else None}


def _artifact_view(row: Artifact) -> dict[str, Any]:
    return {"id": row.id, "conversation_id": row.conversation_id, "run_id": row.run_id,
            "type": row.type, "title": row.title, "content": row.content,
            "content_json": row.content_json, "storage_key": row.storage_key,
            "storage_url": row.storage_url, "version": row.version}


def _tool_call_view(row: ToolCall) -> dict[str, Any]:
    return {"id": row.id, "run_id": row.run_id, "skill_id": row.skill_id,
            "tool_name": row.tool_name, "arguments": row.arguments_json,
            "result": row.result_json, "status": row.status, "error": row.error_message}
