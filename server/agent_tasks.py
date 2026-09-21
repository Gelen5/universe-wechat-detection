"""Celery entry point for normalized conversation Runs."""
from __future__ import annotations

from typing import Callable

from . import conversation_repository
from .agent.orchestrator import AgentOrchestrator
from .agent.runtime import build_orchestrator
from .agent_events import notify
from .celery_app import celery_app
from .providers import ProviderRequestError
from .observability import event as log_event


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
        log_event("agent.run.ignored", run_id=run_id, task_id=self.request.id,
                  status="ignored", error_code="not_claimed")
        return {"status": "ignored", "reason": "already claimed or terminal"}
    log_event("agent.run.started", run_id=run_id, user_id=claimed["user_id"],
              conversation_id=claimed["conversation_id"], skill_id=claimed.get("skill_id"),
              task_id=self.request.id, status="running")
    notify(run_id)
    try:
        if _orchestrator_factory is None:
            raise RuntimeError("agent orchestrator is not configured")
        result = _orchestrator_factory().execute(run_id, claimed["user_id"], task_id=self.request.id)
        log_event("agent.run.finished", run_id=run_id, user_id=claimed["user_id"],
                  conversation_id=claimed["conversation_id"], skill_id=claimed.get("skill_id"),
                  task_id=self.request.id, status=result.get("status", "completed"))
        return result
    except ProviderRequestError as exc:
        log_event("agent.run.provider_error", run_id=run_id, user_id=claimed["user_id"],
                  conversation_id=claimed["conversation_id"], skill_id=claimed.get("skill_id"),
                  task_id=self.request.id, provider=getattr(exc, "provider", None),
                  status="retrying" if exc.transient else "failed", error_code=exc.code)
        if exc.transient and self.request.retries < self.max_retries:
            # Return the persistent Run to queued before Celery redelivery.
            conversation_repository.transition_run(run_id, claimed["user_id"], "queued",
                                                   error_code=exc.code, error_message=str(exc), task_id=self.request.id)
            raise self.retry(exc=exc, countdown=min(30, 2 ** (self.request.retries + 1)))
        current = conversation_repository.get_run(run_id, claimed["user_id"])
        if current and current["status"] not in {"completed", "failed", "cancelled"}:
            conversation_repository.transition_run(
                run_id, claimed["user_id"], "failed", error_code=exc.code,
                error_message=str(exc), task_id=self.request.id,
            )
        raise
    except Exception as exc:
        log_event("agent.run.failed", run_id=run_id, user_id=claimed["user_id"],
                  conversation_id=claimed["conversation_id"], skill_id=claimed.get("skill_id"),
                  task_id=self.request.id, status="failed", error_code=type(exc).__name__)
        current = conversation_repository.get_run(run_id, claimed["user_id"])
        if current and current["status"] not in {"completed", "failed", "cancelled"}:
            conversation_repository.transition_run(
                run_id, claimed["user_id"], "failed", error_code=type(exc).__name__,
                error_message=str(exc), task_id=self.request.id,
            )
        raise


@celery_app.task(name="agent.recover_stale")
def recover_stale_agent_runs():
    recovered = conversation_repository.recover_stale_runs()
    for run_id in recovered:
        execute_agent_run.apply_async(args=[run_id], queue="chat")
    return {"recovered": len(recovered)}
