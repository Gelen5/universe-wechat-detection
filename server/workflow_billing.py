"""Atomic wallet reservation plus workflow creation."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from .accounts import utc_now
from . import database
from .database import session_scope
from .models import WorkflowEvent, WorkflowSession
from .workflow_repository import NODES, _queue_node_locked, _session_view


@dataclass
class InsufficientPoints(Exception):
    required: int
    balance: int


def _create_once(user_id: str, idempotency_key: str, mode: str,
                 input_data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    with session_scope() as db:
        existing = db.scalar(select(WorkflowSession).where(
            WorkflowSession.user_id == user_id,
            WorkflowSession.idempotency_key == idempotency_key,
        ))
        if existing:
            return _session_view(existing), True
        rule = db.execute(text(
            "SELECT feature,points,estimated_cost_micros FROM pricing_rules "
            "WHERE method='POST' AND path='/api/workbench/sessions' AND active=1"
        )).mappings().first()
        if not rule:
            raise RuntimeError("公众号完整工作流计费规则未启用")
        lock = " FOR UPDATE" if database.ENGINE.dialect.name == "postgresql" else ""
        wallet = db.execute(text("SELECT * FROM wallets WHERE user_id=:user_id" + lock),
                            {"user_id": user_id}).mappings().first()
        points = int(rule["points"])
        balance = int(wallet["balance"]) if wallet else 0
        if not wallet or balance < points:
            raise InsufficientPoints(points, balance)
        remaining = points
        allocation: dict[str, int] = {}
        buckets = {name: int(wallet[f"{name}_balance"]) for name in ("trial", "bonus", "paid")}
        for name in ("trial", "bonus", "paid"):
            used = min(buckets[name], remaining)
            if used:
                buckets[name] -= used
                allocation[name] = used
                remaining -= used
            if not remaining:
                break
        request_id, now = uuid.uuid4().hex, utc_now()
        db.execute(text(
            "UPDATE wallets SET balance=:balance,trial_balance=:trial,bonus_balance=:bonus,"
            "paid_balance=:paid,updated_at=:now WHERE user_id=:user_id"
        ), {"balance": balance - points, **buckets, "now": now, "user_id": user_id})
        allocation_json = json.dumps(allocation, ensure_ascii=False)
        db.execute(text(
            "INSERT INTO point_transactions "
            "(id,user_id,amount,balance_before,balance_after,bucket,kind,source,feature,request_id,note,allocation_json,created_at) "
            "VALUES (:id,:user_id,:amount,:before,:after,'mixed','consume','usage',:feature,:request_id,:note,:allocation,:now)"
        ), {"id": uuid.uuid4().hex, "user_id": user_id, "amount": -points, "before": balance,
            "after": balance - points, "feature": rule["feature"], "request_id": request_id,
            "note": f"预扣 {rule['feature']}", "allocation": allocation_json, "now": now})
        db.execute(text(
            "INSERT INTO usage_records "
            "(request_id,user_id,method,path,feature,points,status,estimated_cost_micros,allocation_json,created_at) "
            "VALUES (:request_id,:user_id,'POST','/api/workbench/sessions',:feature,:points,'reserved',:cost,:allocation,:now)"
        ), {"request_id": request_id, "user_id": user_id, "feature": rule["feature"], "points": points,
            "cost": int(rule["estimated_cost_micros"] or 0), "allocation": allocation_json, "now": now})
        workflow = WorkflowSession(
            id=uuid.uuid4().hex, user_id=user_id, idempotency_key=idempotency_key,
            mode=mode, status="queued", current_node=NODES[0], input_json=input_data,
            state_json={"completed_nodes": []}, usage_id=request_id,
        )
        db.add(workflow)
        db.flush()
        db.add(WorkflowEvent(workflow_id=workflow.id, user_id=user_id, event_type="workflow.created",
                             node_name=NODES[0], payload_json={"mode": mode, "version": 1}))
        _queue_node_locked(db, workflow, NODES[0])
        return _session_view(workflow), False


def create_billed_workflow(user_id: str, idempotency_key: str, mode: str,
                           input_data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    try:
        return _create_once(user_id, idempotency_key, mode, input_data)
    except IntegrityError:
        # A concurrent winner commits; the losing transaction, including its
        # reservation, is rolled back in full.
        with session_scope() as db:
            existing = db.scalar(select(WorkflowSession).where(
                WorkflowSession.user_id == user_id,
                WorkflowSession.idempotency_key == idempotency_key,
            ))
            if not existing:
                raise
            return _session_view(existing), True
