"""Transactional persistence for creator workflows."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .database import session_scope
from .models import WorkflowDecision, WorkflowEvent, WorkflowNode, WorkflowSession


NODES = ("intent", "topic", "research", "strategy", "draft", "review", "visual", "delivery")
CHECKPOINTS = frozenset({"topic", "strategy", "visual"})
TERMINAL = frozenset({"completed", "failed", "cancelled"})


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
        latest_attempt = db.scalar(select(func.max(WorkflowNode.attempt)).where(
            WorkflowNode.workflow_id == workflow_id, WorkflowNode.node_name == node_name,
        )) or 0
        existing = db.scalar(select(WorkflowNode).where(
            WorkflowNode.workflow_id == workflow_id, WorkflowNode.node_name == node_name,
            WorkflowNode.status.in_(("queued", "running", "completed", "awaiting_input")),
        ).order_by(WorkflowNode.attempt.desc()))
        if existing:
            return {"id": existing.id, "status": existing.status, "attempt": existing.attempt}
        attempt = latest_attempt + 1
        now = datetime.now(timezone.utc)
        node = WorkflowNode(
            id=uuid.uuid4().hex, workflow_id=workflow_id, node_name=node_name, attempt=attempt,
            status="queued", idempotency_key=f"{workflow_id}:{node_name}:{attempt}",
            input_json={"workflow_version": workflow.version}, result_json={}, queued_at=now,
        )
        workflow.status = "queued"
        workflow.current_node = node_name
        workflow.updated_at = now
        db.add(node)
        db.flush()
        db.add(WorkflowEvent(workflow_id=workflow_id, user_id=workflow.user_id,
                             event_type="node.queued", node_name=node_name,
                             payload_json={"attempt": attempt, "version": workflow.version}))
        return {"id": node.id, "status": node.status, "attempt": attempt}


def claim_node(workflow_id: str, node_name: str, task_id: str | None) -> tuple[dict[str, Any], dict[str, Any]] | None:
    with session_scope() as db:
        workflow = db.scalar(select(WorkflowSession).where(WorkflowSession.id == workflow_id).with_for_update())
        if not workflow or workflow.status in TERMINAL or workflow.cancel_requested:
            return None
        node = db.scalar(select(WorkflowNode).where(
            WorkflowNode.workflow_id == workflow_id, WorkflowNode.node_name == node_name,
        ).order_by(WorkflowNode.attempt.desc()).with_for_update())
        if not node or node.status == "completed":
            return None
        if node.status == "running" and node.celery_task_id != task_id:
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


def complete_node(workflow_id: str, node_name: str, result: dict[str, Any]) -> dict[str, Any]:
    with session_scope() as db:
        workflow = db.scalar(select(WorkflowSession).where(WorkflowSession.id == workflow_id).with_for_update())
        node = db.scalar(select(WorkflowNode).where(
            WorkflowNode.workflow_id == workflow_id, WorkflowNode.node_name == node_name,
        ).order_by(WorkflowNode.attempt.desc()).with_for_update())
        if not workflow or not node:
            raise KeyError("workflow node not found")
        if node.status == "completed":
            return _session_view(workflow)
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
        return _session_view(workflow)


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
        workflow.status = "queued"
        workflow.updated_at = datetime.now(timezone.utc)
        db.add(WorkflowEvent(workflow_id=workflow_id, user_id=user_id,
                             event_type="workflow.decision", node_name=node_name,
                             payload_json={"actor": actor, "version": workflow.version}))
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
        workflow.cancel_requested = True
        workflow.status = "cancelled" if workflow.status in {"queued", "awaiting_input"} else workflow.status
        workflow.finished_at = datetime.now(timezone.utc) if workflow.status == "cancelled" else None
        workflow.version += 1
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
        return _session_view(workflow)


def recover_stale_nodes(stale_seconds: int = 7200) -> list[tuple[str, str]]:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(300, stale_seconds))
    recovered: list[tuple[str, str]] = []
    with session_scope() as db:
        nodes = db.scalars(select(WorkflowNode).where(
            WorkflowNode.status == "running",
            WorkflowNode.heartbeat_at < cutoff,
        ).with_for_update(skip_locked=True)).all()
        for node in nodes:
            workflow = db.get(WorkflowSession, node.workflow_id)
            if not workflow or workflow.cancel_requested or workflow.status in TERMINAL:
                continue
            node.status, node.celery_task_id, node.queued_at = "queued", None, datetime.now(timezone.utc)
            workflow.status, workflow.current_node = "queued", node.node_name
            db.add(WorkflowEvent(workflow_id=workflow.id, user_id=workflow.user_id,
                                 event_type="node.recovered", node_name=node.node_name,
                                 payload_json={"attempt": node.attempt}))
            recovered.append((workflow.id, node.node_name))
    return recovered


def fail_workflow(workflow_id: str, node_name: str, error: str) -> dict[str, Any]:
    with session_scope() as db:
        workflow = db.scalar(select(WorkflowSession).where(WorkflowSession.id == workflow_id).with_for_update())
        node = db.scalar(select(WorkflowNode).where(
            WorkflowNode.workflow_id == workflow_id, WorkflowNode.node_name == node_name,
        ).order_by(WorkflowNode.attempt.desc()).with_for_update())
        if not workflow:
            raise KeyError("workflow not found")
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
        now = datetime.now(timezone.utc)
        workflow.status, workflow.current_node = "completed", NODES[-1]
        workflow.finished_at, workflow.updated_at = now, now
        workflow.version += 1
        db.add(WorkflowEvent(workflow_id=workflow_id, user_id=workflow.user_id,
                             event_type="workflow.completed", node_name=NODES[-1],
                             payload_json={"version": workflow.version}))
        return _session_view(workflow)


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
