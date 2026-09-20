"""Redis wakeups for the PostgreSQL Run event log."""
from __future__ import annotations

import os

from redis import Redis
from redis.asyncio import Redis as AsyncRedis


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


def channel(run_id: str) -> str:
    return f"run:{run_id}:events"


def notify(run_id: str) -> None:
    try:
        client = Redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=1)
        client.publish(channel(run_id), "changed")
        client.close()
    except Exception:
        return


def async_client() -> AsyncRedis:
    return AsyncRedis.from_url(REDIS_URL, decode_responses=True, socket_timeout=5,
                               socket_connect_timeout=1)
