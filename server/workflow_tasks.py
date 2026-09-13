"""Celery tasks: one task per durable workflow node."""
from __future__ import annotations

import os

import requests
from billiard.exceptions import SoftTimeLimitExceeded

from . import accounts
from .celery_app import celery_app
from .workflow_engine import execute_node
from .workflow_events import NodeLockBusy, node_lock, notify
from . import workbench
from .workflow_repository import (
    CHECKPOINTS, NODES, StaleNodeExecution, WorkflowCancellationRequested,
    claim_node, complete_node, fail_workflow, finalize_cancel, get_workflow,
    next_node, queue_node, recover_stale_nodes, release_node_for_retry,
    terminal_usage_actions,
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


def _fail_and_refund(workflow_id: str, node_name: str, message: str, status_code: int,
                     task_id: str | None = None, attempt: int | None = None) -> dict:
    try:
        failed = fail_workflow(
            workflow_id, node_name, message, task_id=task_id, attempt=attempt,
        )
    except StaleNodeExecution:
        return {"status": "ignored", "reason": "execution lease changed"}
    if failed.get("usage_id"):
        accounts.refund_usage(failed["usage_id"], status_code, 0)
    notify(workflow_id)
    return {"status": "failed", "error": message[-500:]}


def dispatch_node(workflow_id: str, node_name: str) -> str:
    queue_node(workflow_id, node_name)
    try:
        result = run_workflow_node.apply_async(args=[workflow_id, node_name], queue="creator")
    except Exception:
        # The queued PostgreSQL row is the durable outbox. Beat will redeliver it.
        notify(workflow_id)
        return ""
    notify(workflow_id)
    return result.id


# External model providers occasionally reset a TLS connection after accepting a
# request. Keep retries bounded, but give the durable node outbox enough time to
# recover without treating a transient transport failure as a user failure.
@celery_app.task(bind=True, name="workflow.run_node", max_retries=4,
                 autoretry_for=(), acks_late=True, reject_on_worker_lost=True,
                 soft_time_limit=NODE_SOFT_TIME_LIMIT, time_limit=NODE_TIME_LIMIT)
def run_workflow_node(self, workflow_id: str, node_name: str):
    attempt = None
    try:
        with node_lock(workflow_id, node_name, timeout=NODE_TIME_LIMIT + 30):
            claimed = claim_node(workflow_id, node_name, self.request.id)
            if not claimed:
                return {"status": "ignored", "reason": "already handled or terminal"}
            workflow, _node = claimed
            attempt = _node["attempt"]
            notify(workflow_id)
            with workbench.provider_overrides(
                request_idempotency_key=f"{workflow_id}:{node_name}:{attempt}",
            ):
                result = execute_node(workflow, node_name)
        current = get_workflow(workflow_id)
        if current and current["cancel_requested"]:
            cancelled = finalize_cancel(workflow_id)
            if cancelled.get("usage_id"):
                accounts.refund_usage(cancelled["usage_id"], 499, 0)
            notify(workflow_id)
            return {"status": "cancelled"}
        pause_after = node_name in CHECKPOINTS and workflow["mode"] == "interactive"
        finish_workflow = node_name == NODES[-1]
        updated = complete_node(
            workflow_id, node_name, result, task_id=self.request.id, attempt=attempt,
            pause_after=pause_after, finish_workflow=finish_workflow,
        )
        notify(workflow_id)
        if finish_workflow:
            if updated.get("usage_id"):
                accounts.settle_usage(updated["usage_id"], 200, 0)
            notify(workflow_id)
            return {"status": "completed"}
        if pause_after:
            return {"status": "awaiting_input", "node": node_name}
        following = next_node(node_name)
        dispatch_node(workflow_id, following)
        return {"status": "continued", "node": following}
    except NodeLockBusy:
        return {"status": "ignored", "reason": "another worker owns the Redis lease"}
    except StaleNodeExecution:
        return {"status": "ignored", "reason": "execution lease changed"}
    except WorkflowCancellationRequested:
        cancelled = finalize_cancel(workflow_id)
        if cancelled.get("usage_id"):
            accounts.refund_usage(cancelled["usage_id"], 499, 0)
        notify(workflow_id)
        return {"status": "cancelled"}
    except SoftTimeLimitExceeded:
        return _fail_and_refund(
            workflow_id, node_name, "节点执行超过软超时限制", 504,
            self.request.id, attempt,
        )
    except Exception as exc:
        if (attempt is not None and _is_transient_error(exc)
                and self.request.retries < self.max_retries
                and release_node_for_retry(workflow_id, node_name, self.request.id, attempt, str(exc))):
            raise self.retry(exc=exc, countdown=min(30, 2 ** (self.request.retries + 1)))
        current = get_workflow(workflow_id)
        if current and current["cancel_requested"]:
            cancelled = finalize_cancel(workflow_id)
            if cancelled.get("usage_id"):
                accounts.refund_usage(cancelled["usage_id"], 499, 0)
            notify(workflow_id)
            return {"status": "cancelled"}
        return _fail_and_refund(
            workflow_id, node_name, str(exc), 500, self.request.id, attempt,
        )


@celery_app.task(name="workflow.recover_stale")
def recover_stale_workflow_nodes():
    recovered = recover_stale_nodes(stale_seconds=NODE_TIME_LIMIT + 60)
    for workflow_id, node_name in recovered:
        run_workflow_node.apply_async(args=[workflow_id, node_name], queue="creator")
        notify(workflow_id)
    reconciled = 0
    for usage_id, status in terminal_usage_actions():
        if status == "completed":
            accounts.settle_usage(usage_id, 200, 0)
        else:
            accounts.refund_usage(usage_id, 500 if status == "failed" else 499, 0)
        reconciled += 1
    return {"recovered": len(recovered), "billing_reconciled": reconciled}
