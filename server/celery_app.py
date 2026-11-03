"""Celery configuration for durable creator workflow execution."""
from __future__ import annotations

import os
import sys

from celery import Celery
from celery.schedules import crontab


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
# Beat only publishes named tasks; importing the worker's task modules here
# wastes substantial memory. Workers still import and register every task.
_beat_only = len(sys.argv) > 1 and "beat" in sys.argv[1:] and "worker" not in sys.argv[1:]
_task_modules = ["server.workflow_tasks", "server.agent_tasks", "server.hotspots",
                 "server.provider_health", "server.wechat_plus_tasks",
                 "server.viral_remix_tasks", "server.lowfans_sync", "server.article_visual_tasks"]
celery_app = Celery("universe_creator", broker=REDIS_URL, backend=REDIS_URL,
                    include=[] if _beat_only else _task_modules)
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
        "viral_remix.run": {"queue": "image"},
        "article_visual.plan": {"queue": "text"},
        "article_visual.recover": {"queue": "text"},
        "market.sync": {"queue": "text"},
        "hotspot.sync": {"queue": "text"},
        "lowfans.sync": {"queue": "text"},
        "provider.health": {"queue": "text"},
    },
    worker_concurrency=max(1, int(os.getenv("CELERY_WORKER_CONCURRENCY", "4"))),
    beat_schedule={
        "recover-wechat-plus": {"task": "wechat_plus.recover", "schedule": 60.0},
        "recover-article-visual": {"task": "article_visual.recover", "schedule": 60.0},
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
        # 微小榜每日生成前一天的 7d 低粉爆文榜。
        # ⚠️ 本文件没设 timezone 且 enable_utc=True，crontab 按 UTC 解析：
        # hour=1,5,9 分钟 30 = 北京时间 09:30 / 13:30 / 17:30。
        # 跑三次是兜底：sync_daily 发现当天数据已存在会直接返回 cached，
        # 只有第一次真花钱，后两次补偿「榜单还没生成」或「部署重启错过窗口」。
        "lowfans-sync-daily": {
            "task": "lowfans.sync", "schedule": crontab(hour="1,5,9", minute=30),
        },
        # A relay can fail for hours; deploy-time probing only covers deploys.
        "provider-health": {
            "task": "provider.health",
            "schedule": max(60.0, float(os.getenv("PROVIDER_HEALTH_INTERVAL", "600"))),
        },
    },
)
