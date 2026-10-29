"""Transactional persistence for the normalized chat and artifact core."""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import load_only

from .database import session_scope
from .models import (
    AgentRun, Artifact, Conversation, ConversationMessage, PointTransaction,
    ProviderCall, RunEvent, ToolCall, UsageRecord, Wallet,
)


class InsufficientPoints(ValueError):
    def __init__(self, required: int, balance: int):
        super().__init__(f"insufficient points: required={required}, balance={balance}")
        self.required = required
        self.balance = balance


class ArtifactVersionConflict(ValueError):
    pass


class IdempotencyConflict(ValueError):
    """The same idempotency key was reused for a different request.

    Returning the old Run in this situation would answer 202 for work the
    caller never asked to run, so the API must surface a conflict instead.
    """

    def __init__(self, message: str = "idempotency key reused for a different request"):
        super().__init__(message)


def _event(db, run: AgentRun, event_type: str, payload: dict[str, Any] | None = None) -> None:
    db.add(RunEvent(run_id=run.id, conversation_id=run.conversation_id, user_id=run.user_id,
                    event_type=event_type, payload_json=payload or {}))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso(value: datetime | None) -> str | None:
    # SQLite strips timezone metadata; all runtime dates are written in UTC.
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()


def _reserve_run_usage(db, run: AgentRun, points: int, feature: str) -> None:
    now = _now().isoformat()
    allocation: dict[str, int] = {}
    if points:
        wallet = db.scalar(select(Wallet).where(Wallet.user_id == run.user_id).with_for_update())
        balance = wallet.balance if wallet else 0
        if not wallet or balance < points:
            raise InsufficientPoints(points, balance)
        remaining = points
        for label, attribute in (("trial", "trial_balance"), ("bonus", "bonus_balance"),
                                 ("paid", "paid_balance")):
            available = int(getattr(wallet, attribute))
            used = min(available, remaining)
            if used:
                setattr(wallet, attribute, available - used)
                allocation[label] = used
                remaining -= used
            if not remaining:
                break
        before = wallet.balance
        wallet.balance -= points
        wallet.updated_at = now
        db.add(PointTransaction(
            id=uuid.uuid4().hex, user_id=run.user_id, amount=-points,
            balance_before=before, balance_after=wallet.balance, bucket="mixed",
            kind="consume", source="usage", feature=feature, request_id=run.usage_id,
            note=f"预扣 {feature}", allocation_json=json.dumps(allocation, ensure_ascii=False),
            created_at=now,
        ))
    db.add(UsageRecord(
        request_id=run.usage_id, user_id=run.user_id, method="POST",
        path="/api/conversations/{id}/messages", feature=feature, points=points,
        status="reserved", estimated_cost_micros=0,
        allocation_json=json.dumps(allocation, ensure_ascii=False), created_at=now,
        conversation_id=run.conversation_id, run_id=run.id, skill_id=run.skill_id,
        actual_cost_micros=0,
    ))


def _settle_usage_locked(db, run: AgentRun) -> None:
    if not run.usage_id:
        return
    usage = db.scalar(select(UsageRecord).where(
        UsageRecord.request_id == run.usage_id,
    ).with_for_update())
    if usage and usage.status == "reserved":
        usage.status = "completed"
        usage.http_status = 200
        usage.actual_cost_micros = run.provider_cost_micros
        usage.finished_at = _now().isoformat()


def _refund_usage_locked(db, run: AgentRun, http_status: int = 500) -> None:
    if not run.usage_id:
        return
    usage = db.scalar(select(UsageRecord).where(
        UsageRecord.request_id == run.usage_id,
    ).with_for_update())
    if not usage or usage.status != "reserved":
        return
    allocation = json.loads(usage.allocation_json or "{}")
    points = int(usage.points or 0)
    if points:
        wallet = db.scalar(select(Wallet).where(Wallet.user_id == run.user_id).with_for_update())
        if not wallet:
            raise RuntimeError("wallet missing during refund")
        before = wallet.balance
        wallet.trial_balance += int(allocation.get("trial", 0))
        wallet.bonus_balance += int(allocation.get("bonus", 0))
        wallet.paid_balance += int(allocation.get("paid", 0))
        wallet.balance += points
        wallet.updated_at = _now().isoformat()
        db.add(PointTransaction(
            id=uuid.uuid4().hex, user_id=run.user_id, amount=points,
            balance_before=before, balance_after=wallet.balance, bucket="mixed",
            kind="refund", source="usage", feature=usage.feature,
            request_id=usage.request_id, note=f"退还 {usage.feature}",
            allocation_json=usage.allocation_json, created_at=wallet.updated_at,
        ))
    usage.status = "refunded"
    usage.http_status = http_status
    usage.actual_cost_micros = run.provider_cost_micros
    usage.finished_at = _now().isoformat()
    run.cost_points = 0


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


def count_active_runs(user_id: str) -> int:
    """Runs this user currently has executing on a worker.

    Only ``running`` counts: queued messages are normal (a user may line up the
    next instruction while the current one executes) and must not trip the cap.
    The cap exists so one user cannot occupy every worker slot.
    """
    with session_scope() as db:
        total = db.scalar(select(func.count(AgentRun.id)).where(
            AgentRun.user_id == user_id,
            AgentRun.status == "running",
        ))
    return int(total or 0)


def get_skill_state(conversation_id: str, user_id: str) -> dict[str, Any] | None:
    """The vendored workflow's ArticleState for this conversation, if any."""
    with session_scope() as db:
        row = db.scalar(select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id,
        ))
        if not row:
            return None
        return (row.metadata_json or {}).get("skill_state")


def set_skill_state(conversation_id: str, user_id: str, payload: dict[str, Any] | None) -> None:
    """Persist the workflow state, or drop it when payload is None."""
    with session_scope() as db:
        row = db.scalar(select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id,
        ).with_for_update(key_share=True))
        if not row:
            return
        metadata = dict(row.metadata_json or {})
        if payload is None:
            metadata.pop("skill_state", None)
        else:
            metadata["skill_state"] = payload
        row.metadata_json = metadata
        row.updated_at = _now()


def get_conversation(conversation_id: str, user_id: str) -> dict[str, Any] | None:
    with session_scope() as db:
        row = db.scalar(select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id,
        ))
        if not row:
            return None
        result = _conversation_view(row)
        active = db.scalar(select(AgentRun).where(
            AgentRun.conversation_id == conversation_id, AgentRun.user_id == user_id,
            AgentRun.status.in_(("queued", "running", "waiting_input")),
        ).order_by(AgentRun.created_at.desc()).limit(1))
        result["active_run"] = _run_view(active) if active else None
        return result


def list_conversations(user_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    with session_scope() as db:
        rows = db.scalars(select(Conversation).where(
            Conversation.user_id == user_id,
        ).order_by(Conversation.updated_at.desc()).limit(min(max(limit, 1), 100))).all()
        return [_conversation_view(row) for row in rows]


def bind_conversation_skill(conversation_id: str, user_id: str, skill_id: str) -> dict[str, Any]:
    with session_scope() as db:
        row = db.scalar(select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id,
        ).with_for_update(key_share=True))
        if not row:
            raise KeyError("conversation not found")
        row.skill_id = skill_id
        row.updated_at = _now()
        return _conversation_view(row)


def add_message(conversation_id: str, user_id: str, role: str, content: str, *,
                content_json: dict[str, Any] | None = None,
                metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    if role not in {"user", "assistant", "tool", "system"}:
        raise ValueError("unsupported message role")
    with session_scope() as db:
        conversation = db.scalar(select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id,
        ).with_for_update(key_share=True))
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
        ).order_by(ConversationMessage.created_at.desc(), ConversationMessage.id.desc())
          .limit(min(max(limit, 1), 500))).all()
        return [_message_view(row) for row in reversed(rows)]


def get_message(conversation_id: str, user_id: str, message_id: str) -> dict[str, Any] | None:
    with session_scope() as db:
        row = db.scalar(select(ConversationMessage).join(
            Conversation, Conversation.id == ConversationMessage.conversation_id,
        ).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
            ConversationMessage.id == message_id,
        ))
        return _message_view(row) if row else None


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


def _ensure_same_request(db, run: AgentRun, conversation_id: str, content: str,
                         content_json: dict[str, Any] | None) -> None:
    """Reject a replayed idempotency key that carries a different request.

    Key uniqueness alone only scopes a key to a user. Without this check a
    client that reuses a key for another conversation, or another body, gets a
    silent 202 pointing at the old Run: the new message is never accepted and
    the caller has no way to notice.
    """
    if run.conversation_id != conversation_id:
        raise IdempotencyConflict("idempotency key reused for a different conversation")
    previous = db.get(ConversationMessage, run.trigger_message_id)
    if previous is None:
        return
    if (previous.content or "") != (content or ""):
        raise IdempotencyConflict("idempotency key reused for a different message body")
    if (previous.content_json or {}) != (content_json or {}):
        raise IdempotencyConflict("idempotency key reused for a different message payload")


def conversation_points_charged(conversation_id: str, user_id: str) -> int:
    """Points this conversation has actually cost, ignoring refunded runs.

    A conversation is billed per message, so one article that takes four messages
    used to cost four times its headline price. The cap needs the charged total
    to know when to stop; refunded runs must not consume the budget, or a user
    who hit a provider outage would lose the message they never got.
    """
    with session_scope() as db:
        total = db.scalar(select(func.coalesce(func.sum(UsageRecord.points), 0)).where(
            UsageRecord.conversation_id == conversation_id,
            UsageRecord.user_id == user_id,
            UsageRecord.status != "refunded",
        ))
    return int(total or 0)


def create_message_run(conversation_id: str, user_id: str, content: str,
                       idempotency_key: str, *, content_json: dict[str, Any] | None = None,
                       metadata: dict[str, Any] | None = None, reserve_points: int = 0,
                       feature: str = "AI 创作") -> tuple[dict[str, Any], dict[str, Any], bool]:
    """Atomically persist one user message and its Run under one idempotency key."""
    try:
        with session_scope() as db:
            existing = db.scalar(select(AgentRun).where(
                AgentRun.user_id == user_id, AgentRun.idempotency_key == idempotency_key,
            ))
            if existing:
                _ensure_same_request(db, existing, conversation_id, content, content_json)
                message = db.get(ConversationMessage, existing.trigger_message_id)
                return _message_view(message), _run_view(existing), True
            conversation = db.scalar(select(Conversation).where(
                Conversation.id == conversation_id, Conversation.user_id == user_id,
            ).with_for_update(key_share=True))
            if not conversation:
                raise KeyError("conversation not found")
            existing = db.scalar(select(AgentRun).where(
                AgentRun.user_id == user_id, AgentRun.idempotency_key == idempotency_key,
            ))
            if existing:
                _ensure_same_request(db, existing, conversation_id, content, content_json)
                message = db.get(ConversationMessage, existing.trigger_message_id)
                return _message_view(message), _run_view(existing), True
            now = _now()
            waiting_runs = db.scalars(select(AgentRun).where(
                AgentRun.conversation_id == conversation_id,
                AgentRun.user_id == user_id,
                AgentRun.status == "waiting_input",
            ).with_for_update()).all()
            for waiting in waiting_runs:
                waiting.status = "cancelled"
                waiting.finished_at = waiting.updated_at = waiting.heartbeat_at = now
                waiting.celery_task_id = None
                waiting.error_code = "superseded_by_input"
                waiting.error_message = "continued by a newer user message"
                _refund_usage_locked(db, waiting, 499)
                _event(db, waiting, "run.cancelled", {
                    "reason": "superseded_by_input",
                })
            ranks = select(Artifact.id.label('id'), func.row_number().over(
                partition_by=Artifact.type, order_by=Artifact.version.desc()).label('rank')).where(
                Artifact.conversation_id == conversation_id, Artifact.user_id == user_id).subquery()
            input_artifacts = list(db.scalars(select(ranks.c.id).where(ranks.c.rank == 1)))
            image_ids = db.scalars(select(Artifact.id).where(
                Artifact.conversation_id == conversation_id, Artifact.user_id == user_id,
                Artifact.type == 'image').order_by(Artifact.created_at.desc(), Artifact.id.desc()).limit(8)).all()
            input_artifacts = list(dict.fromkeys([*input_artifacts, *image_ids]))
            history_ids = db.scalars(select(ConversationMessage.id).where(
                ConversationMessage.conversation_id == conversation_id).order_by(
                ConversationMessage.created_at.desc(), ConversationMessage.id.desc()).limit(39)).all()
            message = ConversationMessage(id=uuid.uuid4().hex, conversation_id=conversation_id,
                role="user", content=content, content_json=content_json or {},
                metadata_json={**(metadata or {}), '_input_snapshot_v': 1,
                    '_input_artifact_ids': input_artifacts,
                    '_input_message_ids': [*reversed(history_ids), None]}, created_at=now)
            message.metadata_json['_input_message_ids'][-1] = message.id
            db.add(message)
            # PostgreSQL checks this FK when each statement executes. Flush the
            # referenced message before adding a Run that points at it.
            db.flush()
            run = AgentRun(id=uuid.uuid4().hex, conversation_id=conversation_id,
                trigger_message_id=message.id, user_id=user_id,
                skill_id=conversation.skill_id if conversation.mode == "manual" else None,
                idempotency_key=idempotency_key, status="queued", usage_id=uuid.uuid4().hex,
                cost_points=max(0, reserve_points), created_at=now, updated_at=now)
            conversation.updated_at = now
            db.add(run)
            db.flush()
            _reserve_run_usage(db, run, max(0, reserve_points), feature)
            _event(db, run, "run.created", {"message_id": message.id})
            _event(db, run, "run.queued", {})
            db.flush()
            return _message_view(message), _run_view(run), False
    except IntegrityError:
        with session_scope() as db:
            run = db.scalar(select(AgentRun).where(
                AgentRun.user_id == user_id, AgentRun.idempotency_key == idempotency_key,
            ))
            if not run:
                raise
            _ensure_same_request(db, run, conversation_id, content, content_json)
            message = db.get(ConversationMessage, run.trigger_message_id)
            return _message_view(message), _run_view(run), True


def get_run(run_id: str, user_id: str) -> dict[str, Any] | None:
    with session_scope() as db:
        row = db.scalar(select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user_id))
        return _run_view(row) if row else None


def run_inputs(run_id: str, user_id: str, *, artifacts: bool = True,
               messages: bool = True) -> dict[str, Any]:
    """Frozen submission inputs plus genuine worker outputs from this same Run.

    Human revisions use artifact.updated and must not enter a running worker's
    inputs through an inherited run_id. Legacy Runs without a snapshot keep
    their pre-upgrade read contract until drained.
    """
    with session_scope() as db:
        run = db.scalar(select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user_id))
        if not run:
            raise KeyError('run not found')
        trigger = db.get(ConversationMessage, run.trigger_message_id)
        snapshot = trigger.metadata_json if trigger else {}
        if not snapshot or snapshot.get('_input_snapshot_v') != 1:
            return {'artifacts': list_artifacts(run.conversation_id, user_id) if artifacts else [],
                    'messages': list_messages(run.conversation_id, user_id, limit=40) if messages else []}
        result = {'artifacts': [], 'messages': []}
        if artifacts:
            ids = snapshot.get('_input_artifact_ids')
            if not isinstance(ids, list):
                raise RuntimeError('invalid input snapshot')
            owned = list(db.scalars(select(Artifact).where(
                Artifact.id.in_(ids), Artifact.user_id == user_id, Artifact.conversation_id == run.conversation_id)))
            if len(owned) != len(set(ids)):
                raise RuntimeError('input artifact snapshot is unavailable')
            output_ids = [payload.get('artifact_id') for payload in db.scalars(select(RunEvent.payload_json).where(
                RunEvent.run_id == run_id, RunEvent.event_type == 'artifact.created'))]
            outputs = list(db.scalars(select(Artifact).where(
                Artifact.id.in_(output_ids), Artifact.user_id == user_id, Artifact.run_id == run_id)))
            completed_tools = set(db.scalars(select(ToolCall.id).where(
                ToolCall.run_id == run_id, ToolCall.status == 'completed')))
            outputs = [item for item in outputs if item.source_key
                       and item.source_key.split(':', 1)[0] in completed_tools]
            unique = {item.id: item for item in [*owned, *outputs]}
            result['artifacts'] = [_artifact_view(item) for item in sorted(unique.values(), key=lambda item: (item.created_at, item.version))]
        if messages:
            ids = snapshot.get('_input_message_ids')
            if not isinstance(ids, list):
                raise RuntimeError('invalid message snapshot')
            rows = db.scalars(select(ConversationMessage).where(
                ConversationMessage.id.in_(ids), ConversationMessage.conversation_id == run.conversation_id)).all()
            by_id = {row.id: row for row in rows}
            if set(ids) != set(by_id):
                raise RuntimeError('input message snapshot is unavailable')
            result['messages'] = [_message_view(by_id[message_id]) for message_id in ids]
        return result


def list_active_runs(user_id: str, *, limit: int = 50, before: str | None = None) -> list[dict[str, Any]]:
    with session_scope() as db:
        query = select(AgentRun, Conversation.title).join(
            Conversation, Conversation.id == AgentRun.conversation_id).where(
            AgentRun.user_id == user_id, Conversation.user_id == user_id,
            AgentRun.status.in_(('queued', 'running', 'waiting_input')),
        )
        if before:
            cursor = db.scalar(select(AgentRun).where(AgentRun.id == before, AgentRun.user_id == user_id))
            if not cursor:
                raise ValueError('invalid task cursor')
            query = query.where((AgentRun.created_at < cursor.created_at) |
                ((AgentRun.created_at == cursor.created_at) & (AgentRun.id < cursor.id)))
        rows = db.execute(query.order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
                          .limit(min(max(limit, 1), 101))).all()
        return [{**_run_view(run), 'conversation_title': title} for run, title in rows]


def find_request_run(conversation_id: str, user_id: str, key: str) -> dict[str, Any] | None:
    with session_scope() as db:
        row = db.scalar(select(AgentRun).where(
            AgentRun.conversation_id == conversation_id, AgentRun.user_id == user_id,
            AgentRun.idempotency_key == key))
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
        if row.status in {"completed", "failed", "cancelled"}:
            # A terminal run is final: re-entering the same status would issue a
            # second refund and a second run.failed event.
            raise ValueError("terminal run cannot transition")
        row.status, row.updated_at = status, now
        row.error_code, row.error_message = error_code, error_message
        if status == "running":
            row.started_at = row.started_at or now
        if status in {"completed", "failed", "cancelled"}:
            row.finished_at = row.finished_at or now
            row.heartbeat_at = now
        if status in {"completed", "failed", "cancelled"}:
            # A recovered attempt can leave earlier tool rows running. Close
            # every unfinished row in the same transaction as its parent run.
            for tool in db.scalars(select(ToolCall).where(
                    ToolCall.run_id == row.id, ToolCall.status.in_(["queued", "running"]))):
                tool.status = "cancelled" if status == "cancelled" else "failed"
                tool.finished_at = now
                tool.error_message = error_message or "run ended before tool completion"
        if status == "completed":
            _settle_usage_locked(db, row)
        elif status in {"failed", "cancelled"}:
            _refund_usage_locked(db, row, 499 if status == "cancelled" else 500)
        view = _run_view(row)
        # Event payloads travel to the browser over SSE: expose the bounded code
        # only. The raw provider message stays in runs.error_message for operators.
        payload = {"error_code": error_code, "error_kind": view["error_kind"]} \
            if (error_code or error_message) else {}
        _event(db, row, f"run.{status}", payload)
        return view


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
        _event(db, row, "run.started", {"attempt": row.attempt})
        return _run_view(row)


def heartbeat_run(run_id: str, task_id: str) -> bool:
    with session_scope() as db:
        row = db.scalar(select(AgentRun).where(AgentRun.id == run_id).with_for_update())
        if not row or row.status != "running" or row.celery_task_id != task_id:
            return False
        row.heartbeat_at = row.updated_at = _now()
        return True


def bind_run_skill(run_id: str, user_id: str, skill_id: str, *, task_id: str | None = None) -> dict[str, Any]:
    """Persist an auto-routed Skill on both Run and Usage attribution."""
    with session_scope() as db:
        row = db.scalar(select(AgentRun).where(
            AgentRun.id == run_id, AgentRun.user_id == user_id,
        ).with_for_update())
        if not row:
            raise KeyError("run not found")
        if task_id is not None and row.celery_task_id != task_id:
            raise RuntimeError("run execution lease changed")
        if row.skill_id and row.skill_id != skill_id:
            raise RuntimeError("run Skill is already bound")
        row.skill_id = skill_id
        row.updated_at = _now()
        if row.usage_id:
            usage = db.get(UsageRecord, row.usage_id)
            if usage:
                usage.skill_id = skill_id
        return _run_view(row)


def set_run_stage(run_id: str, user_id: str, stage: str | None, *,
                  task_id: str | None = None) -> dict[str, Any]:
    """Persist the stage this run resolved to (model routing, not the tab hint)."""
    with session_scope() as db:
        row = db.scalar(select(AgentRun).where(
            AgentRun.id == run_id, AgentRun.user_id == user_id,
        ).with_for_update())
        if not row:
            raise KeyError("run not found")
        if task_id is not None and row.celery_task_id != task_id:
            raise RuntimeError("run execution lease changed")
        row.stage = stage
        row.updated_at = _now()
        return _run_view(row)


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
            _event(db, row, "run.recovered", {"reason": "worker_lost"})
            _event(db, row, "run.queued", {"recovered": True})
            recovered.append(row.id)
    return recovered


def recover_orphaned_queued_runs(queued_seconds: int = 600) -> list[str]:
    """Re-dispatch Runs that were committed but never reached the broker.

    ``create_message_run`` commits the Run as ``queued`` and the API publishes
    it afterwards. A crash, a broker outage or a killed worker between those
    two steps leaves the Run queued forever while its points stay reserved, and
    ``recover_stale_runs`` only scans ``running`` rows, so nothing ever picks it
    up. Bumping ``updated_at`` here also throttles redelivery: the next pass
    cannot select the same row until another window has elapsed.

    The window is deliberately long. A run waiting behind a congested queue
    looks identical to an orphan, and a short window would keep republishing it,
    multiplying load exactly when the queue is already full.
    """
    cutoff = _now() - timedelta(seconds=max(30, queued_seconds))
    recovered: list[str] = []
    with session_scope() as db:
        rows = db.scalars(select(AgentRun).where(
            AgentRun.status == "queued",
            AgentRun.celery_task_id.is_(None),
            AgentRun.updated_at < cutoff,
        ).with_for_update(skip_locked=True)).all()
        for row in rows:
            row.updated_at = _now()
            row.error_code = "redelivered"
            row.error_message = "queued run re-dispatched by reconciler"
            _event(db, row, "run.queued", {"recovered": True, "reason": "orphaned_queued"})
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
        _refund_usage_locked(db, row, 499)
        for tool in db.scalars(select(ToolCall).where(ToolCall.run_id == row.id, ToolCall.status.in_(['queued', 'running']))):
            tool.status, tool.finished_at, tool.error_message = 'cancelled', now, 'run cancelled'
        _event(db, row, "run.cancelled", {})
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


def get_artifact(artifact_id: str, user_id: str) -> dict[str, Any] | None:
    with session_scope() as db:
        row = db.scalar(select(Artifact).where(Artifact.id == artifact_id, Artifact.user_id == user_id))
        return _artifact_view(row) if row else None


def artifact_workspace(conversation_id: str, user_id: str, *, limit: int = 50,
                       before: str | None = None) -> dict[str, Any]:
    """Current stage bodies plus a paged, body-free history. Legacy API is unchanged."""
    with session_scope() as db:
        owner = db.scalar(select(Conversation.id).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id))
        if not owner:
            raise KeyError('conversation not found')
        scope = (Artifact.conversation_id == conversation_id, Artifact.user_id == user_id)
        ranks = select(Artifact.id.label('id'), func.row_number().over(
            partition_by=Artifact.type, order_by=Artifact.version.desc()).label('rank')
        ).where(*scope).subquery()
        current = list(db.scalars(select(Artifact).where(Artifact.id.in_(
            select(ranks.c.id).where(ranks.c.rank == 1)))).all())
        # A review has its own revised article. Keep both that version and the
        # pre-review writing stage available without loading every old body.
        report = next((item for item in current if item.type == 'report'), None)
        if report:
            for same_run in (True, False):
                article = db.scalar(select(Artifact).where(*scope, Artifact.type == 'article',
                    (Artifact.run_id == report.run_id) if same_run else (Artifact.run_id != report.run_id)
                ).order_by(Artifact.version.desc()).limit(1))
                if article and article.id not in {item.id for item in current}:
                    current.append(article)
        query = select(Artifact).where(*scope)
        if before:
            cursor = db.scalar(select(Artifact).where(*scope, Artifact.id == before))
            if not cursor:
                raise ValueError('invalid history cursor')
            query = query.where((Artifact.created_at < cursor.created_at) |
                ((Artifact.created_at == cursor.created_at) & (Artifact.id < cursor.id)))
        size = min(max(limit, 1), 100)
        rows = list(db.scalars(query.options(load_only(
            Artifact.id, Artifact.conversation_id, Artifact.run_id, Artifact.type,
            Artifact.title, Artifact.version, Artifact.storage_url, Artifact.created_at, Artifact.updated_at,
        )).order_by(Artifact.created_at.desc(), Artifact.id.desc()).limit(size + 1)).all())
        page = rows[:size]
        summaries = {item.id: {
            'id': item.id, 'conversation_id': item.conversation_id, 'run_id': item.run_id,
            'type': item.type, 'title': item.title, 'version': item.version,
            'storage_url': item.storage_url, 'created_at': item.created_at.isoformat(),
            'updated_at': item.updated_at.isoformat(), 'content_loaded': False,
        } for item in page}
        summaries.update({item.id: {**_artifact_view(item), 'content_loaded': True} for item in current})
        return {'artifacts': list(summaries.values()),
                'total': db.scalar(select(func.count(Artifact.id)).where(*scope)),
                'next_cursor': page[-1].id if len(rows) > size else None}


def get_artifact_by_storage_key(storage_key: str, user_id: str) -> dict[str, Any] | None:
    with session_scope() as db:
        row = db.scalar(select(Artifact).where(
            Artifact.storage_key == storage_key, Artifact.user_id == user_id,
        ).order_by(Artifact.version.desc()))
        return _artifact_view(row) if row else None


def list_artifact_versions(artifact_id: str, user_id: str) -> list[dict[str, Any]]:
    with session_scope() as db:
        source = db.scalar(select(Artifact).where(
            Artifact.id == artifact_id, Artifact.user_id == user_id,
        ))
        if not source:
            raise KeyError("artifact not found")
        rows = db.scalars(select(Artifact).where(
            Artifact.conversation_id == source.conversation_id,
            Artifact.type == source.type,
            Artifact.user_id == user_id,
        ).order_by(Artifact.version)).all()
        return [_artifact_view(row) for row in rows]


def create_tool_call(run_id: str, user_id: str, *, call_id: str, skill_id: str | None,
                     tool_name: str, arguments: dict[str, Any],
                     idempotency_key: str | None = None) -> tuple[dict[str, Any], bool]:
    key = idempotency_key or f"{run_id}:{call_id}"
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
            _event(db, run, "tool.started", {"tool_call_id": row.id, "tool_name": tool_name})
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
        # cancel_run locks run before updating tools; use the same order.
        run = db.scalar(select(AgentRun).where(
            AgentRun.id == run_id, AgentRun.user_id == user_id).with_for_update())
        if not run:
            raise KeyError('run not found')
        row = db.scalar(select(ToolCall).where(
            ToolCall.id == tool_call_id, ToolCall.run_id == run_id,
        ).with_for_update())
        if not row:
            raise KeyError("tool call not found")
        # A Run that already reached a terminal state must not accept fresh
        # output from a worker that lost its lease (cancel/refund race).
        if not error and run is not None and run.status in {"cancelled", "failed"}:
            return _tool_call_view(row)
        if row.status in {"completed", "cancelled"}:
            return _tool_call_view(row)
        if row.status == "failed" and error:
            return _tool_call_view(row)
        # A transient failure can be retried with the same logical key. When the
        # retry succeeds the row is still "failed", and returning early would
        # throw the successful result away: the Run completes with an empty
        # ToolCall that can never be replayed. Repair the row instead and keep
        # the failed attempt in the event stream.
        retry_repaired = row.status == "failed" and not error
        row.status = "failed" if error else "completed"
        row.result_json = result or {}
        row.error_message = error
        row.finished_at = _now()
        _event(db, run, "tool.failed" if error else "tool.completed", {
            "tool_call_id": row.id, "tool_name": row.tool_name,
            **({"error": error} if error else {}),
        })
        if retry_repaired:
            _event(db, run, "tool.retry_succeeded", {
                "tool_call_id": row.id, "tool_name": row.tool_name,
            })
        return _tool_call_view(row)


def replace_tool_call_result(tool_call_id: str, run_id: str, user_id: str,
                             result: dict[str, Any]) -> dict[str, Any]:
    with session_scope() as db:
        run = db.scalar(select(AgentRun).where(
            AgentRun.id == run_id, AgentRun.user_id == user_id).with_for_update())
        if not run:
            raise KeyError('run not found')
        row = db.scalar(select(ToolCall).where(
            ToolCall.id == tool_call_id, ToolCall.run_id == run_id,
        ).with_for_update())
        if not row:
            raise KeyError("tool call not found")
        if row.status != "completed":
            raise ValueError("only completed tool results can be replaced")
        row.result_json = result
        return _tool_call_view(row)


def create_artifact(run_id: str, user_id: str, artifact_type: str, *, title: str = "",
                    content: str = "", content_json: dict[str, Any] | None = None,
                    storage_key: str | None = None, storage_url: str | None = None,
                    source_key: str | None = None, task_id: str | None = None) -> dict[str, Any]:
    with session_scope() as db:
        conversation_id = db.scalar(select(AgentRun.conversation_id).where(
            AgentRun.id == run_id, AgentRun.user_id == user_id))
        if not conversation_id:
            raise KeyError("run not found")
        # All conversation writes acquire conversation before run. Reversing
        # these locks can deadlock with revision event FK checks in PostgreSQL.
        # NO KEY UPDATE still serializes conversation writes, while permitting
        # FK KEY SHARE checks from a concurrent Run cancellation.
        conversation = db.scalar(select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id,
        ).with_for_update(key_share=True))
        if not conversation:
            raise KeyError("conversation not found")
        run = db.scalar(select(AgentRun).where(
            AgentRun.id == run_id, AgentRun.user_id == user_id).with_for_update())
        if not run:
            raise KeyError('run not found')
        if task_id is not None and (run.status != 'running' or run.celery_task_id != task_id):
            raise RuntimeError('run execution lease changed')
        # Artifact writes are the last thing a worker does, well after its final
        # heartbeat. A cancel/refund or a newer attempt can win that window, and
        # the stale worker must not leave fresh output on a dead Run.
        if run.status in {"cancelled", "failed"}:
            raise RuntimeError(
                f"run {run_id} is {run.status}; refusing to persist new artifacts")
        if source_key:
            existing = db.scalar(select(Artifact).where(
                Artifact.source_key == source_key, Artifact.user_id == user_id,
            ))
            if existing:
                return _artifact_view(existing)
        version = (db.scalar(select(func.max(Artifact.version)).where(
            Artifact.conversation_id == run.conversation_id, Artifact.type == artifact_type,
        )) or 0) + 1
        row = Artifact(id=uuid.uuid4().hex, user_id=user_id, conversation_id=run.conversation_id,
                       run_id=run_id, type=artifact_type, title=title, content=content,
                       content_json=content_json or {}, storage_key=storage_key,
                       storage_url=storage_url, source_key=source_key, version=version)
        db.add(row)
        _event(db, run, "artifact.created", {"artifact_id": row.id, "type": artifact_type, "version": version})
        db.flush()
        return _artifact_view(row)


def create_artifact_version(artifact_id: str, user_id: str, *, title: str | None = None,
                            content: str | None = None,
                            content_json: dict[str, Any] | None = None,
                            storage_key: str | None = None,
                            storage_url: str | None = None,
                            expected_current_id: str | None = None) -> dict[str, Any]:
    with session_scope() as db:
        source = db.scalar(select(Artifact).where(
            Artifact.id == artifact_id, Artifact.user_id == user_id,
        ))
        if not source:
            raise KeyError("artifact not found")
        conversation = db.scalar(select(Conversation).where(
            Conversation.id == source.conversation_id, Conversation.user_id == user_id,
        ).with_for_update(key_share=True))
        if not conversation:
            raise KeyError("conversation not found")
        if expected_current_id is not None:
            latest = db.scalar(select(Artifact).where(
                Artifact.conversation_id == source.conversation_id, Artifact.type == source.type,
                Artifact.user_id == user_id).order_by(Artifact.version.desc()).limit(1))
            if latest and latest.id != expected_current_id:
                # A response can be lost after committing a content-only save.
                # Accept its exact replay rather than creating another version.
                if (content is not None and latest.content == content and title is None
                        and content_json is None and storage_key is None and storage_url is None):
                    return _artifact_view(latest)
                raise ArtifactVersionConflict('a newer artifact version exists')
        version = (db.scalar(select(func.max(Artifact.version)).where(
            Artifact.conversation_id == source.conversation_id, Artifact.type == source.type,
        )) or 0) + 1
        row = Artifact(
            id=uuid.uuid4().hex, user_id=user_id, conversation_id=source.conversation_id,
            run_id=source.run_id, type=source.type,
            title=source.title if title is None else title,
            content=source.content if content is None else content,
            content_json=source.content_json if content_json is None else content_json,
            storage_key=storage_key if storage_key is not None else source.storage_key,
            storage_url=storage_url if storage_url is not None else source.storage_url,
            version=version,
        )
        db.add(row)
        run = db.get(AgentRun, source.run_id)
        _event(db, run, "artifact.updated", {
            "artifact_id": row.id, "previous_artifact_id": source.id,
            "type": row.type, "version": version,
        })
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
        if run.usage_id:
            usage = db.get(UsageRecord, run.usage_id)
            if usage:
                usage.actual_cost_micros = run.provider_cost_micros
                usage.provider = provider
                usage.model = model
                usage.tool_call_id = tool_call_id
        db.add(row)
        db.flush()
        return {"id": row.id, "run_id": run_id, "provider": provider, "model": model,
                "estimated_cost_micros": estimated_cost_micros}


def record_run_event(run_id: str, user_id: str, event_type: str,
                     payload: dict[str, Any] | None = None) -> dict[str, Any]:
    with session_scope() as db:
        run = db.scalar(select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user_id))
        if not run:
            raise KeyError("run not found")
        row = RunEvent(run_id=run.id, conversation_id=run.conversation_id, user_id=user_id,
                       event_type=event_type, payload_json=payload or {})
        db.add(row)
        db.flush()
        return _event_view(row)


def agent_metrics(*, since_hours: int = 24) -> dict[str, Any]:
    """Return bounded operational and cost metrics for the admin surface."""
    cutoff = _now() - timedelta(hours=max(1, min(since_hours, 24 * 90)))
    with session_scope() as db:
        runs = db.scalars(select(AgentRun).where(AgentRun.created_at >= cutoff)).all()
        provider_calls = db.scalars(select(ProviderCall).where(ProviderCall.created_at >= cutoff)).all()
        usage = db.scalars(select(UsageRecord).where(UsageRecord.created_at >= cutoff.isoformat())).all()
        conversations = db.scalars(select(Conversation).where(Conversation.updated_at >= cutoff)).all()
    terminal = [row for row in runs if row.status in {"completed", "failed", "cancelled"}]
    durations = sorted(
        max(0, int((row.finished_at - row.started_at).total_seconds() * 1000))
        for row in terminal if row.started_at and row.finished_at
    )

    def percentile(values: list[int], fraction: float) -> int | None:
        if not values:
            return None
        return values[min(len(values) - 1, max(0, int((len(values) - 1) * fraction)))]

    by_skill: dict[str, dict[str, int]] = {}
    for row in runs:
        key = row.skill_id or "unresolved"
        item = by_skill.setdefault(key, {"runs": 0, "completed": 0, "failed": 0})
        item["runs"] += 1
        if row.status in {"completed", "failed"}:
            item[row.status] += 1
    completed = sum(row.status == "completed" for row in runs)
    failed = sum(row.status == "failed" for row in runs)
    refunded = sum(row.status == "refunded" for row in usage)
    return {
        "window_hours": max(1, min(since_hours, 24 * 90)),
        "dau": len({row.user_id for row in conversations}),
        "conversations": len(conversations), "runs": len(runs),
        "completed_runs": completed, "failed_runs": failed,
        "success_rate": round(completed / max(1, completed + failed), 4),
        "latency_ms": {
            "average": round(sum(durations) / len(durations)) if durations else None,
            "p50": percentile(durations, 0.50), "p95": percentile(durations, 0.95),
        },
        "skills": by_skill,
        "provider": {
            "calls": len(provider_calls),
            "input_tokens": sum(row.input_tokens for row in provider_calls),
            "output_tokens": sum(row.output_tokens for row in provider_calls),
            "images": sum(row.image_count for row in provider_calls),
            "estimated_cost_micros": sum(row.estimated_cost_micros for row in provider_calls),
        },
        "billing": {
            "points_reserved_or_spent": sum(row.points for row in usage),
            "refunds": refunded,
            "refund_rate": round(refunded / max(1, len(usage)), 4),
        },
    }


def events_after(run_id: str, user_id: str, after_id: int = 0, limit: int = 200) -> list[dict[str, Any]]:
    with session_scope() as db:
        owned = db.scalar(select(AgentRun.id).where(AgentRun.id == run_id, AgentRun.user_id == user_id))
        if not owned:
            raise KeyError("run not found")
        rows = db.scalars(select(RunEvent).where(
            RunEvent.run_id == run_id, RunEvent.id > max(0, after_id),
        ).order_by(RunEvent.id).limit(min(max(limit, 1), 500))).all()
        return [_event_view(row) for row in rows]


def _conversation_view(row: Conversation) -> dict[str, Any]:
    return {"id": row.id, "user_id": row.user_id, "title": row.title, "skill_id": row.skill_id,
            "mode": row.mode, "status": row.status, "metadata": row.metadata_json,
            "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat()}


def _message_view(row: ConversationMessage) -> dict[str, Any]:
    return {"id": row.id, "conversation_id": row.conversation_id, "role": row.role,
            "content": row.content, "content_json": row.content_json,
            "metadata": row.metadata_json, "created_at": row.created_at.isoformat()}


_SECRET_PATTERN = re.compile(r"\b(?:sk|ak)-[A-Za-z0-9_\-]{6,}", re.I)

# Failure codes written by server.agent.failures.describe(); surfaced verbatim so
# the client can pick a precise message instead of the generic fallback.
FAILURE_KINDS = {
    "provider_access", "provider_balance", "provider_connection", "queue",
    "skill_missing", "stage_tool_missing", "topic_source", "topic_schema",
    "provider", "timeout", "tool_limit", "tool_missing_call", "tool_error",
}


def _redact(value: str | None, limit: int = 400) -> str | None:
    if not value:
        return None
    return _SECRET_PATTERN.sub("[已隐藏凭据]", str(value)).strip()[:limit]


def _run_view(row: AgentRun) -> dict[str, Any]:
    error_text = row.error_message or ""
    if row.error_code in FAILURE_KINDS:
        error_kind = row.error_code
    elif row.error_code == "ip_not_allowed" or "ip 不在令牌允许访问" in error_text:
        error_kind = "provider_access"
    elif any(marker in error_text for marker in ("额度不足", "余额不足", "insufficient balance", "insufficient_quota")):
        error_kind = "provider_balance"
    elif any(marker in error_text for marker in ("provider connection failed", "remote end closed", "connection reset")):
        error_kind = "provider_connection"
    elif row.error_code == "enqueue_failed":
        error_kind = "queue"
    elif row.error_code:
        error_kind = "tool_error"
    else:
        error_kind = None
    # Only the bounded code leaves the server: raw provider messages can carry
    # request ids and account hints. Operators read runs.error_message instead.
    return {"id": row.id, "conversation_id": row.conversation_id,
            "trigger_message_id": row.trigger_message_id, "user_id": row.user_id,
            "skill_id": row.skill_id, "status": row.status, "usage_id": row.usage_id,
            "cost_points": row.cost_points, "provider_cost_micros": row.provider_cost_micros,
            "celery_task_id": row.celery_task_id, "attempt": row.attempt,
            "heartbeat_at": row.heartbeat_at.isoformat() if row.heartbeat_at else None,
            "stage": row.stage,
            "created_at": _utc_iso(row.created_at), "updated_at": _utc_iso(row.updated_at),
            "started_at": _utc_iso(row.started_at), "finished_at": _utc_iso(row.finished_at),
            "error_kind": error_kind, "error_code": row.error_code}


def _artifact_view(row: Artifact) -> dict[str, Any]:
    return {"id": row.id, "conversation_id": row.conversation_id, "run_id": row.run_id,
            "type": row.type, "title": row.title, "content": row.content,
            "content_json": row.content_json, "storage_key": row.storage_key,
            "storage_url": row.storage_url, "source_key": row.source_key, "version": row.version,
            "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat()}


def _tool_call_view(row: ToolCall) -> dict[str, Any]:
    return {"id": row.id, "run_id": row.run_id, "skill_id": row.skill_id,
            "tool_name": row.tool_name, "arguments": row.arguments_json,
            "result": row.result_json, "status": row.status, "error": row.error_message}


def _event_view(row: RunEvent) -> dict[str, Any]:
    return {"id": row.id, "run_id": row.run_id, "conversation_id": row.conversation_id,
            "type": row.event_type, "payload": row.payload_json,
            "created_at": _utc_iso(row.created_at)}
