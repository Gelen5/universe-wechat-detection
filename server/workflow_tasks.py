"""Celery tasks: one task per durable workflow node."""
from __future__ import annotations

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


def dispatch_node(workflow_id: str, node_name: str) -> str:
    node = queue_node(workflow_id, node_name)
    result = run_workflow_node.apply_async(args=[workflow_id, node_name], queue="creator")
    notify(workflow_id)
    return result.id


@celery_app.task(bind=True, name="workflow.run_node", max_retries=2,
                 autoretry_for=(), acks_late=True, reject_on_worker_lost=True)
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
    except Exception as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=min(30, 2 ** (self.request.retries + 1)))
        failed = fail_workflow(workflow_id, node_name, str(exc))
        if failed.get("usage_id"):
            accounts.refund_usage(failed["usage_id"], 500, 0)
        notify(workflow_id)
        return {"status": "failed", "error": str(exc)[-500:]}


@celery_app.task(name="workflow.recover_stale")
def recover_stale_workflow_nodes():
    recovered = recover_stale_nodes()
    for workflow_id, node_name in recovered:
        run_workflow_node.apply_async(args=[workflow_id, node_name], queue="creator")
        notify(workflow_id)
    return {"recovered": len(recovered)}
