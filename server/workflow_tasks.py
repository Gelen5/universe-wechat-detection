"""Celery tasks: one task per durable workflow node."""
from __future__ import annotations

import os

import requests
from billiard.exceptions import SoftTimeLimitExceeded

from . import accounts
from .celery_app import celery_app
from .workflow_engine import execute_node
from .workflow_events import node_lock, notify
from . import workbench
from .workflow_repository import (
    CHECKPOINTS, NODES, claim_node, complete_node, complete_workflow,
    fail_workflow, finalize_cancel, get_workflow, next_node, pause_workflow,
    queue_node, recover_stale_nodes,
)


NODE_SOFT_TIME_LIMIT = max(30, int(os.getenv("CELERY_NODE_SOFT_TIME_LIMIT", "600")))
NODE_TIME_LIMIT = max(NODE_SOFT_TIME_LIMIT + 10, int(os.getenv("CELERY_NODE_TIME_LIMIT", "660")))


def _is_transient_error(exc: Exception) -> bool:
    if isinstance(exc, (requests.RequestException, TimeoutError, ConnectionError)):
        return True
    message = str(exc).lower()
    transient_markers = (
        "http 429", "status 429", "too many requests", "rate limit",
        "http 500", "http 502", "http 503", "http 504",
        "status 500", "status 502", "status 503", "status 504",
        "temporarily unavailable", "connection reset", "connection aborted",
        "connection refused", "read timed out", "connect timeout",
    )
    return any(marker in message for marker in transient_markers)


def _fail_and_refund(workflow_id: str, node_name: str, message: str, status_code: int) -> dict:
    failed = fail_workflow(workflow_id, node_name, message)
    if failed.get("usage_id"):
        accounts.refund_usage(failed["usage_id"], status_code, 0)
    notify(workflow_id)
    return {"status": "failed", "error": message[-500:]}


def dispatch_node(workflow_id: str, node_name: str) -> str:
    node = queue_node(workflow_id, node_name)
    result = run_workflow_node.apply_async(args=[workflow_id, node_name], queue="creator")
    notify(workflow_id)
    return result.id


@celery_app.task(bind=True, name="workflow.run_node", max_retries=2,
                 autoretry_for=(), acks_late=True, reject_on_worker_lost=True,
                 soft_time_limit=NODE_SOFT_TIME_LIMIT, time_limit=NODE_TIME_LIMIT)
def run_workflow_node(self, workflow_id: str, node_name: str):
    try:
        with node_lock(workflow_id, node_name):
            claimed = claim_node(workflow_id, node_name, self.request.id)
            if not claimed:
                return {"status": "ignored", "reason": "already handled or terminal"}
            workflow, _node = claimed
            notify(workflow_id)
            with workbench.provider_overrides():
                result = execute_node(workflow, node_name)
        current = get_workflow(workflow_id)
        if current and current["cancel_requested"]:
            cancelled = finalize_cancel(workflow_id)
            if cancelled.get("usage_id"):
                accounts.refund_usage(cancelled["usage_id"], 499, 0)
            notify(workflow_id)
            return {"status": "cancelled"}
        updated = complete_node(workflow_id, node_name, result)
        notify(workflow_id)
        if node_name == NODES[-1]:
            completed = complete_workflow(workflow_id)
            if completed.get("usage_id"):
                accounts.settle_usage(completed["usage_id"], 200, 0)
            notify(workflow_id)
            return {"status": "completed"}
        if node_name in CHECKPOINTS and updated["mode"] == "interactive":
            pause_workflow(workflow_id, node_name)
            notify(workflow_id)
            return {"status": "awaiting_input", "node": node_name}
        following = next_node(node_name)
        dispatch_node(workflow_id, following)
        return {"status": "continued", "node": following}
    except SoftTimeLimitExceeded:
        return _fail_and_refund(workflow_id, node_name, "节点执行超过软超时限制", 504)
    except Exception as exc:
        if _is_transient_error(exc) and self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=min(30, 2 ** (self.request.retries + 1)))
        return _fail_and_refund(workflow_id, node_name, str(exc), 500)


@celery_app.task(name="workflow.recover_stale")
def recover_stale_workflow_nodes():
    recovered = recover_stale_nodes()
    for workflow_id, node_name in recovered:
        run_workflow_node.apply_async(args=[workflow_id, node_name], queue="creator")
        notify(workflow_id)
    return {"recovered": len(recovered)}
