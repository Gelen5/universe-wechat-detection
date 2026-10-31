"""Celery configuration for durable creator workflow execution."""
from __future__ import annotations

import os

from celery import Celery
from celery.schedules import crontab


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
celery_app = Celery("universe_creator", broker=REDIS_URL, backend=REDIS_URL,
                    include=["server.workflow_tasks", "server.agent_tasks", "server.hotspots",
                             "server.provider_health", "server.wechat_plus_tasks"])
celery_app.conf.update(
    task_serializer="json", result_serializer="json", accept_content=["json"],
    task_acks_late=True, task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1, broker_connection_retry_on_startup=True,
    task_track_started=True, result_expires=86400,
    task_always_eager=os.getenv("CELERY_TASK_ALWAYS_EAGER", "0") == "1",
    task_eager_propagates=True,
    task_routes={
        "workflow.run_node": {"queue": "workflow"},
        "workflow.recover_stale": {"queue": "workflow"},
        "agent.run": {"queue": "chat"},
        "agent.recover_stale": {"queue": "chat"},
        "wechat_plus.run": {"queue": "chat"},
        "wechat_plus.recover": {"queue": "chat"},
        "market.sync": {"queue": "text"},
        "hotspot.sync": {"queue": "text"},
        "provider.health": {"queue": "text"},
    },
    worker_concurrency=max(1, int(os.getenv("CELERY_WORKER_CONCURRENCY", "4"))),
    beat_schedule={
        "recover-wechat-plus": {"task": "wechat_plus.recover", "schedule": 60.0},
        "recover-stale-workflow-nodes": {
            "task": "workflow.recover_stale", "schedule": 60.0,
        },
        "recover-stale-agent-runs": {
            "task": "agent.recover_stale", "schedule": 60.0,
        },
        "market-sync-daily": {
            "task": "market.sync", "schedule": crontab(hour=4, minute=10),
        },
        "hotspot-sync": {
            "task": "hotspot.sync", "schedule": 600.0,
        },
        # A relay can fail for hours; deploy-time probing only covers deploys.
        "provider-health": {
            "task": "provider.health",
            "schedule": max(60.0, float(os.getenv("PROVIDER_HEALTH_INTERVAL", "600"))),
        },
    },
)
