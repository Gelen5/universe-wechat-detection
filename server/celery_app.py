"""Celery configuration for durable creator workflow execution."""
from __future__ import annotations

import os

from celery import Celery


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
celery_app = Celery("universe_creator", broker=REDIS_URL, backend=REDIS_URL,
                    include=["server.workflow_tasks"])
celery_app.conf.update(
    task_serializer="json", result_serializer="json", accept_content=["json"],
    task_acks_late=True, task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1, broker_connection_retry_on_startup=True,
    task_track_started=True, result_expires=86400,
    task_always_eager=os.getenv("CELERY_TASK_ALWAYS_EAGER", "0") == "1",
    task_eager_propagates=True,
    task_routes={"workflow.run_node": {"queue": "creator"}},
    worker_concurrency=max(1, int(os.getenv("CELERY_WORKER_CONCURRENCY", "4"))),
    beat_schedule={
        "recover-stale-workflow-nodes": {
            "task": "workflow.recover_stale", "schedule": 60.0,
        },
    },
)
