"""Celery entry point for normalized conversation Runs."""
from __future__ import annotations

from typing import Callable

from . import conversation_repository
from .agent.orchestrator import AgentOrchestrator
from .agent.runtime import build_orchestrator
from .agent_events import notify
from .celery_app import celery_app
from .providers import ProviderRequestError


_orchestrator_factory: Callable[[], AgentOrchestrator] | None = build_orchestrator


def configure_orchestrator(factory: Callable[[], AgentOrchestrator]) -> None:
    global _orchestrator_factory
    _orchestrator_factory = factory


def dispatch_run(run_id: str) -> str:
    result = execute_agent_run.apply_async(args=[run_id], queue="chat")
    return result.id


@celery_app.task(bind=True, name="agent.run", max_retries=4, acks_late=True,
                 reject_on_worker_lost=True, soft_time_limit=600, time_limit=660)
def execute_agent_run(self, run_id: str):
    claimed = conversation_repository.claim_run(run_id, self.request.id)
    if not claimed:
        return {"status": "ignored", "reason": "already claimed or terminal"}
    notify(run_id)
    if _orchestrator_factory is None:
        conversation_repository.transition_run(run_id, claimed["user_id"], "failed",
                                               error_code="orchestrator_unconfigured",
                                               error_message="agent orchestrator is not configured")
        return {"status": "failed", "error": "orchestrator_unconfigured"}
    try:
        return _orchestrator_factory().execute(run_id, claimed["user_id"], task_id=self.request.id)
    except ProviderRequestError as exc:
        if exc.transient and self.request.retries < self.max_retries:
            # Return the persistent Run to queued before Celery redelivery.
            conversation_repository.transition_run(run_id, claimed["user_id"], "queued",
                                                   error_code=exc.code, error_message=str(exc), task_id=self.request.id)
            raise self.retry(exc=exc, countdown=min(30, 2 ** (self.request.retries + 1)))
        raise


@celery_app.task(name="agent.recover_stale")
def recover_stale_agent_runs():
    recovered = conversation_repository.recover_stale_runs()
    for run_id in recovered:
        execute_agent_run.apply_async(args=[run_id], queue="chat")
    return {"recovered": len(recovered)}
