"""Transactional persistence for creator workflows."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from .database import session_scope
from .models import WorkflowDecision, WorkflowEvent, WorkflowNode, WorkflowSession


NODES = ("intent", "topic", "research", "strategy", "draft", "review", "visual", "delivery")
CHECKPOINTS = frozenset({"topic", "strategy", "visual"})
TERMINAL = frozenset({"completed", "failed", "cancelled"})


class StaleNodeExecution(RuntimeError):
    pass


class WorkflowCancellationRequested(RuntimeError):
    pass


def _queue_node_locked(db, workflow: WorkflowSession, node_name: str,
                       now: datetime | None = None) -> WorkflowNode:
    """Create the durable outbox row while the workflow row is locked."""
    latest_attempt = db.scalar(select(func.max(WorkflowNode.attempt)).where(
        WorkflowNode.workflow_id == workflow.id, WorkflowNode.node_name == node_name,
    )) or 0
    existing = db.scalar(select(WorkflowNode).where(
        WorkflowNode.workflow_id == workflow.id, WorkflowNode.node_name == node_name,
        WorkflowNode.status.in_(("queued", "running", "completed", "awaiting_input")),
    ).order_by(WorkflowNode.attempt.desc()))
    if existing:
        return existing
    now = now or datetime.now(timezone.utc)
    node = WorkflowNode(
        id=uuid.uuid4().hex, workflow_id=workflow.id, node_name=node_name,
        attempt=latest_attempt + 1, status="queued",
        idempotency_key=f"{workflow.id}:{node_name}:{latest_attempt + 1}",
        input_json={"workflow_version": workflow.version}, result_json={}, queued_at=now,
    )
    workflow.status, workflow.current_node, workflow.updated_at = "queued", node_name, now
    db.add(node)
    db.flush()
    db.add(WorkflowEvent(
        workflow_id=workflow.id, user_id=workflow.user_id, event_type="node.queued",
        node_name=node_name, payload_json={"attempt": node.attempt, "version": workflow.version},
    ))
    return node


def _session_view(row: WorkflowSession) -> dict[str, Any]:
    return {
        "id": row.id, "user_id": row.user_id, "mode": row.mode, "status": row.status,
        "current_node": row.current_node, "version": row.version, "input": row.input_json,
        "state": row.state_json, "usage_id": row.usage_id,
        "cancel_requested": row.cancel_requested, "error": row.error,
        "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat(),
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
    }


def create_workflow(user_id: str, idempotency_key: str, mode: str,
                    input_data: dict[str, Any], usage_id: str | None = None) -> tuple[dict[str, Any], bool]:
    if mode not in {"auto", "interactive"}:
        raise ValueError("mode must be auto or interactive")
    try:
        with session_scope() as db:
            existing = db.scalar(select(WorkflowSession).where(
                WorkflowSession.user_id == user_id,
                WorkflowSession.idempotency_key == idempotency_key,
            ))
            if existing:
                return _session_view(existing), True
            row = WorkflowSession(
                id=uuid.uuid4().hex, user_id=user_id, idempotency_key=idempotency_key,
                mode=mode, status="queued", current_node=NODES[0], input_json=input_data,
                state_json={"completed_nodes": []}, usage_id=usage_id,
            )
            db.add(row)
            db.flush()
            db.add(WorkflowEvent(workflow_id=row.id, user_id=user_id, event_type="workflow.created",
                                 node_name=NODES[0], payload_json={"mode": mode, "version": 1}))
            _queue_node_locked(db, row, NODES[0])
            return _session_view(row), False
    except IntegrityError:
        # A concurrent request may win the unique key between SELECT and INSERT.
        with session_scope() as db:
            existing = db.scalar(select(WorkflowSession).where(
                WorkflowSession.user_id == user_id,
                WorkflowSession.idempotency_key == idempotency_key,
            ))
            if not existing:
                raise
            return _session_view(existing), True


def get_workflow(workflow_id: str, user_id: str | None = None, *, lock: bool = False) -> dict[str, Any] | None:
    with session_scope() as db:
        query = select(WorkflowSession).where(WorkflowSession.id == workflow_id)
        if user_id is not None:
            query = query.where(WorkflowSession.user_id == user_id)
        if lock:
            query = query.with_for_update()
        row = db.scalar(query)
        return _session_view(row) if row else None


def queue_node(workflow_id: str, node_name: str) -> dict[str, Any]:
    if node_name not in NODES:
        raise ValueError(f"unknown workflow node: {node_name}")
    with session_scope() as db:
        workflow = db.scalar(select(WorkflowSession).where(WorkflowSession.id == workflow_id).with_for_update())
        if not workflow:
            raise KeyError("workflow not found")
        if workflow.status in TERMINAL or workflow.cancel_requested:
            raise ValueError("workflow is terminal or cancelling")
        node = _queue_node_locked(db, workflow, node_name)
        return {"id": node.id, "status": node.status, "attempt": node.attempt}


def claim_node(workflow_id: str, node_name: str, task_id: str | None) -> tuple[dict[str, Any], dict[str, Any]] | None:
    with session_scope() as db:
        workflow = db.scalar(select(WorkflowSession).where(WorkflowSession.id == workflow_id).with_for_update())
        if not workflow or workflow.status in TERMINAL or workflow.cancel_requested:
            return None
        node = db.scalar(select(WorkflowNode).where(
            WorkflowNode.workflow_id == workflow_id, WorkflowNode.node_name == node_name,
        ).order_by(WorkflowNode.attempt.desc()).with_for_update())
        if not node or node.status != "queued":
            return None
        now = datetime.now(timezone.utc)
        node.status = "running"
        node.celery_task_id = task_id
        node.started_at = node.started_at or now
        node.heartbeat_at = now
        workflow.status = "running"
        workflow.current_node = node_name
        workflow.updated_at = now
        db.add(WorkflowEvent(workflow_id=workflow_id, user_id=workflow.user_id,
                             event_type="node.started", node_name=node_name,
                             payload_json={"attempt": node.attempt}))
        return _session_view(workflow), {"id": node.id, "attempt": node.attempt}


def complete_node(workflow_id: str, node_name: str, result: dict[str, Any], *,
                  task_id: str | None = None, attempt: int | None = None,
                  pause_after: bool = False, finish_workflow: bool = False) -> dict[str, Any]:
    with session_scope() as db:
        workflow = db.scalar(select(WorkflowSession).where(WorkflowSession.id == workflow_id).with_for_update())
        node = db.scalar(select(WorkflowNode).where(
            WorkflowNode.workflow_id == workflow_id, WorkflowNode.node_name == node_name,
        ).order_by(WorkflowNode.attempt.desc()).with_for_update())
        if not workflow or not node:
            raise KeyError("workflow node not found")
        if workflow.cancel_requested or workflow.status == "cancelled":
            raise WorkflowCancellationRequested("workflow cancellation was requested")
        if workflow.status in {"completed", "failed"}:
            raise StaleNodeExecution("workflow is already terminal")
        if node.status != "running":
            raise StaleNodeExecution("node is no longer running")
        if task_id is not None and node.celery_task_id != task_id:
            raise StaleNodeExecution("node execution lease changed")
        if attempt is not None and node.attempt != attempt:
            raise StaleNodeExecution("node attempt changed")
        now = datetime.now(timezone.utc)
        node.status = "completed"
        node.result_json = result
        node.finished_at = now
        state = dict(workflow.state_json or {})
        completed = list(state.get("completed_nodes") or [])
        if node_name not in completed:
            completed.append(node_name)
        state.update(result)
        state["completed_nodes"] = completed
        workflow.state_json = state
        workflow.version += 1
        workflow.updated_at = now
        db.add(WorkflowEvent(workflow_id=workflow_id, user_id=workflow.user_id,
                             event_type="node.completed", node_name=node_name,
                             payload_json={"attempt": node.attempt, "version": workflow.version}))
        if finish_workflow:
            workflow.status, workflow.current_node = "completed", NODES[-1]
            workflow.finished_at = now
            workflow.version += 1
            db.add(WorkflowEvent(workflow_id=workflow_id, user_id=workflow.user_id,
                                 event_type="workflow.completed", node_name=NODES[-1],
                                 payload_json={"version": workflow.version}))
        elif pause_after:
            workflow.status, workflow.current_node = "awaiting_input", node_name
            db.add(WorkflowEvent(workflow_id=workflow_id, user_id=workflow.user_id,
                                 event_type="workflow.awaiting_input", node_name=node_name,
                                 payload_json={"version": workflow.version}))
        else:
            following = next_node(node_name)
            if following:
                _queue_node_locked(db, workflow, following, now)
        return _session_view(workflow)


def release_node_for_retry(workflow_id: str, node_name: str, task_id: str | None,
                           attempt: int, error: str) -> bool:
    """Release only the execution lease owned by this Celery delivery."""
    with session_scope() as db:
        workflow = db.scalar(select(WorkflowSession).where(
            WorkflowSession.id == workflow_id,
        ).with_for_update())
        node = db.scalar(select(WorkflowNode).where(
            WorkflowNode.workflow_id == workflow_id, WorkflowNode.node_name == node_name,
            WorkflowNode.attempt == attempt,
        ).with_for_update())
        if not workflow or not node or workflow.cancel_requested or workflow.status in TERMINAL:
            return False
        if node.status != "running" or node.celery_task_id != task_id:
            return False
        now = datetime.now(timezone.utc)
        node.status, node.celery_task_id, node.queued_at = "queued", None, now
        node.error, node.heartbeat_at = error[-2000:], now
        workflow.status, workflow.current_node, workflow.updated_at = "queued", node_name, now
        db.add(WorkflowEvent(workflow_id=workflow_id, user_id=workflow.user_id,
                             event_type="node.retry_queued", node_name=node_name,
                             payload_json={"attempt": attempt}))
        return True


def pause_workflow(workflow_id: str, node_name: str) -> dict[str, Any]:
    with session_scope() as db:
        workflow = db.scalar(select(WorkflowSession).where(WorkflowSession.id == workflow_id).with_for_update())
        if not workflow:
            raise KeyError("workflow not found")
        workflow.status = "awaiting_input"
        workflow.current_node = node_name
        workflow.updated_at = datetime.now(timezone.utc)
        db.add(WorkflowEvent(workflow_id=workflow_id, user_id=workflow.user_id,
                             event_type="workflow.awaiting_input", node_name=node_name,
                             payload_json={"version": workflow.version}))
        return _session_view(workflow)


def record_decision(workflow_id: str, user_id: str, node_name: str, expected_version: int,
                    decision: dict[str, Any], actor: str = "user") -> dict[str, Any]:
    with session_scope() as db:
        workflow = db.scalar(select(WorkflowSession).where(
            WorkflowSession.id == workflow_id, WorkflowSession.user_id == user_id,
        ).with_for_update())
        if not workflow:
            raise KeyError("workflow not found")
        if workflow.status != "awaiting_input" or workflow.current_node != node_name:
            raise ValueError("workflow is not awaiting this decision")
        if workflow.version != expected_version:
            raise RuntimeError("workflow version changed; refresh before deciding")
        db.add(WorkflowDecision(id=uuid.uuid4().hex, workflow_id=workflow_id,
                                node_name=node_name, actor=actor, expected_version=expected_version,
                                decision_json=decision))
        state = dict(workflow.state_json or {})
        decisions = dict(state.get("decisions") or {})
        decisions[node_name] = decision
        state["decisions"] = decisions
        workflow.state_json = state
        workflow.version += 1
        workflow.updated_at = datetime.now(timezone.utc)
        db.add(WorkflowEvent(workflow_id=workflow_id, user_id=user_id,
                             event_type="workflow.decision", node_name=node_name,
                             payload_json={"actor": actor, "version": workflow.version}))
        following = next_node(node_name)
        if following:
            _queue_node_locked(db, workflow, following)
        return _session_view(workflow)


def request_cancel(workflow_id: str, user_id: str) -> dict[str, Any]:
    with session_scope() as db:
        workflow = db.scalar(select(WorkflowSession).where(
            WorkflowSession.id == workflow_id, WorkflowSession.user_id == user_id,
        ).with_for_update())
        if not workflow:
            raise KeyError("workflow not found")
        if workflow.status in TERMINAL:
            return _session_view(workflow)
        now = datetime.now(timezone.utc)
        workflow.cancel_requested = True
        workflow.status, workflow.finished_at, workflow.updated_at = "cancelled", now, now
        workflow.version += 1
        nodes = db.scalars(select(WorkflowNode).where(
            WorkflowNode.workflow_id == workflow_id,
            WorkflowNode.status.in_(("queued", "running")),
        ).with_for_update()).all()
        for node in nodes:
            node.status, node.finished_at = "cancelled", now
        db.add(WorkflowEvent(workflow_id=workflow_id, user_id=user_id,
                             event_type="workflow.cancel_requested", node_name=workflow.current_node,
                             payload_json={"version": workflow.version}))
        return _session_view(workflow)


def finalize_cancel(workflow_id: str) -> dict[str, Any]:
    with session_scope() as db:
        workflow = db.scalar(select(WorkflowSession).where(WorkflowSession.id == workflow_id).with_for_update())
        if not workflow:
            raise KeyError("workflow not found")
        if workflow.status in TERMINAL:
            return _session_view(workflow)
        now = datetime.now(timezone.utc)
        workflow.status, workflow.finished_at, workflow.updated_at = "cancelled", now, now
        workflow.version += 1
        node = db.scalar(select(WorkflowNode).where(
            WorkflowNode.workflow_id == workflow_id, WorkflowNode.status == "running",
        ).order_by(WorkflowNode.attempt.desc()).with_for_update())
        if node:
            node.status, node.finished_at = "cancelled", now
        db.add(WorkflowEvent(workflow_id=workflow_id, user_id=workflow.user_id,
                             event_type="workflow.cancelled", node_name=workflow.current_node,
                             payload_json={"version": workflow.version}))
        return _session_view(workflow)


def change_mode(workflow_id: str, user_id: str, mode: str, expected_version: int) -> dict[str, Any]:
    if mode not in {"auto", "interactive"}:
        raise ValueError("mode must be auto or interactive")
    with session_scope() as db:
        workflow = db.scalar(select(WorkflowSession).where(
            WorkflowSession.id == workflow_id, WorkflowSession.user_id == user_id,
        ).with_for_update())
        if not workflow:
            raise KeyError("workflow not found")
        if workflow.version != expected_version:
            raise RuntimeError("workflow version changed; refresh before switching mode")
        workflow.mode = mode
        workflow.version += 1
        workflow.updated_at = datetime.now(timezone.utc)
        db.add(WorkflowEvent(workflow_id=workflow_id, user_id=user_id,
                             event_type="workflow.mode_changed", node_name=workflow.current_node,
                             payload_json={"mode": mode, "version": workflow.version}))
        return _session_view(workflow)


def retry_failed(workflow_id: str, user_id: str) -> tuple[dict[str, Any], str]:
    with session_scope() as db:
        workflow = db.scalar(select(WorkflowSession).where(
            WorkflowSession.id == workflow_id, WorkflowSession.user_id == user_id,
        ).with_for_update())
        if not workflow:
            raise KeyError("workflow not found")
        if workflow.status != "failed":
            raise ValueError("only a failed workflow can be retried")
        node_name = workflow.current_node
        workflow.status, workflow.error, workflow.finished_at = "queued", None, None
        workflow.cancel_requested = False
        workflow.version += 1
        workflow.updated_at = datetime.now(timezone.utc)
        db.add(WorkflowEvent(workflow_id=workflow_id, user_id=user_id,
                             event_type="workflow.retry_requested", node_name=node_name,
                             payload_json={"version": workflow.version}))
        _queue_node_locked(db, workflow, node_name)
        return _session_view(workflow), node_name


def invalidate_from(workflow_id: str, user_id: str, node_name: str,
                    state_patch: dict[str, Any], expected_version: int) -> dict[str, Any]:
    if node_name not in NODES:
        raise ValueError("unknown workflow node")
    with session_scope() as db:
        workflow = db.scalar(select(WorkflowSession).where(
            WorkflowSession.id == workflow_id, WorkflowSession.user_id == user_id,
        ).with_for_update())
        if not workflow:
            raise KeyError("workflow not found")
        if workflow.version != expected_version:
            raise RuntimeError("workflow version changed; refresh before editing")
        if workflow.status in {"running", "queued"}:
            raise ValueError("wait for the current node before editing upstream content")
        start = NODES.index(node_name)
        downstream = NODES[start:]
        nodes = db.scalars(select(WorkflowNode).where(
            WorkflowNode.workflow_id == workflow_id,
            WorkflowNode.node_name.in_(downstream),
            WorkflowNode.status.in_(("completed", "awaiting_input", "failed")),
        ).with_for_update()).all()
        now = datetime.now(timezone.utc)
        for node in nodes:
            node.status, node.finished_at = "invalidated", now
        state = dict(workflow.state_json or {})
        state.update(state_patch)
        state["completed_nodes"] = [name for name in state.get("completed_nodes", []) if NODES.index(name) < start]
        workflow.state_json = state
        workflow.status, workflow.current_node, workflow.error, workflow.finished_at = "queued", node_name, None, None
        workflow.version += 1
        workflow.updated_at = now
        db.add(WorkflowEvent(workflow_id=workflow_id, user_id=user_id,
                             event_type="workflow.invalidated", node_name=node_name,
                             payload_json={"nodes": list(downstream), "version": workflow.version}))
        _queue_node_locked(db, workflow, node_name, now)
        return _session_view(workflow)


def recover_stale_nodes(stale_seconds: int = 900, queued_seconds: int = 60) -> list[tuple[str, str]]:
    now = datetime.now(timezone.utc)
    running_cutoff = now - timedelta(seconds=max(60, stale_seconds))
    queued_cutoff = now - timedelta(seconds=max(30, queued_seconds))
    recovered: list[tuple[str, str]] = []
    with session_scope() as db:
        nodes = db.scalars(select(WorkflowNode).where(
            ((WorkflowNode.status == "running") & (WorkflowNode.heartbeat_at < running_cutoff)) |
            ((WorkflowNode.status == "queued") & (WorkflowNode.queued_at < queued_cutoff)),
        ).with_for_update(skip_locked=True)).all()
        for node in nodes:
            workflow = db.get(WorkflowSession, node.workflow_id)
            if not workflow or workflow.cancel_requested or workflow.status in TERMINAL:
                continue
            if node.status == "running":
                node.status, node.celery_task_id = "queued", None
            node.queued_at = now
            workflow.status, workflow.current_node = "queued", node.node_name
            db.add(WorkflowEvent(workflow_id=workflow.id, user_id=workflow.user_id,
                                 event_type="node.recovered", node_name=node.node_name,
                                 payload_json={"attempt": node.attempt}))
            recovered.append((workflow.id, node.node_name))
    return recovered


def fail_workflow(workflow_id: str, node_name: str, error: str, *,
                  task_id: str | None = None, attempt: int | None = None) -> dict[str, Any]:
    with session_scope() as db:
        workflow = db.scalar(select(WorkflowSession).where(WorkflowSession.id == workflow_id).with_for_update())
        node = db.scalar(select(WorkflowNode).where(
            WorkflowNode.workflow_id == workflow_id, WorkflowNode.node_name == node_name,
        ).order_by(WorkflowNode.attempt.desc()).with_for_update())
        if not workflow:
            raise KeyError("workflow not found")
        if workflow.status in TERMINAL:
            raise StaleNodeExecution("workflow is already terminal")
        if node and task_id is not None and (node.status != "running" or node.celery_task_id != task_id):
            raise StaleNodeExecution("node execution lease changed")
        if node and attempt is not None and node.attempt != attempt:
            raise StaleNodeExecution("node attempt changed")
        now = datetime.now(timezone.utc)
        if node:
            node.status, node.error, node.finished_at = "failed", error[-2000:], now
        workflow.status, workflow.error, workflow.finished_at = "failed", error[-2000:], now
        workflow.version += 1
        db.add(WorkflowEvent(workflow_id=workflow_id, user_id=workflow.user_id,
                             event_type="workflow.failed", node_name=node_name,
                             payload_json={"error": error[-500:], "version": workflow.version}))
        return _session_view(workflow)


def complete_workflow(workflow_id: str) -> dict[str, Any]:
    with session_scope() as db:
        workflow = db.scalar(select(WorkflowSession).where(WorkflowSession.id == workflow_id).with_for_update())
        if not workflow:
            raise KeyError("workflow not found")
        if workflow.status == "completed":
            return _session_view(workflow)
        if workflow.status in {"failed", "cancelled"}:
            raise StaleNodeExecution("workflow is already terminal")
        now = datetime.now(timezone.utc)
        workflow.status, workflow.current_node = "completed", NODES[-1]
        workflow.finished_at, workflow.updated_at = now, now
        workflow.version += 1
        db.add(WorkflowEvent(workflow_id=workflow_id, user_id=workflow.user_id,
                             event_type="workflow.completed", node_name=NODES[-1],
                             payload_json={"version": workflow.version}))
        return _session_view(workflow)


def terminal_usage_actions(limit: int = 200) -> list[tuple[str, str]]:
    """Return terminal workflow charges that still need settlement or refund."""
    with session_scope() as db:
        rows = db.execute(text(
            "SELECT w.usage_id, w.status FROM workflow_sessions w "
            "JOIN usage_records u ON u.request_id = w.usage_id "
            "WHERE w.usage_id IS NOT NULL "
            "AND w.status IN ('completed','failed','cancelled') "
            "AND u.status = 'reserved' "
            "ORDER BY w.updated_at ASC LIMIT :limit"
        ), {"limit": max(1, min(limit, 1000))}).all()
        return [(str(usage_id), str(status)) for usage_id, status in rows]


def events_after(workflow_id: str, user_id: str, last_id: int = 0, limit: int = 200) -> list[dict[str, Any]]:
    with session_scope() as db:
        owner = db.scalar(select(WorkflowSession.id).where(
            WorkflowSession.id == workflow_id, WorkflowSession.user_id == user_id,
        ))
        if not owner:
            raise KeyError("workflow not found")
        rows = db.scalars(select(WorkflowEvent).where(
            WorkflowEvent.workflow_id == workflow_id, WorkflowEvent.id > last_id,
        ).order_by(WorkflowEvent.id).limit(max(1, min(limit, 1000)))).all()
        return [{"id": row.id, "type": row.event_type, "node": row.node_name,
                 "payload": row.payload_json, "created_at": row.created_at.isoformat()} for row in rows]


def next_node(node_name: str) -> str | None:
    index = NODES.index(node_name)
    return NODES[index + 1] if index + 1 < len(NODES) else None
