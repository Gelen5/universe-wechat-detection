"""Redis notification channel for the PostgreSQL workflow event log."""
from __future__ import annotations

import os
from contextlib import contextmanager

from redis import Redis
from redis.asyncio import Redis as AsyncRedis


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


def channel(workflow_id: str) -> str:
    return f"workflow:{workflow_id}:events"


def notify(workflow_id: str) -> None:
    try:
        client = Redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=1)
        client.publish(channel(workflow_id), "changed")
        client.close()
    except Exception:
        # PostgreSQL is authoritative. SSE polling closes any Pub/Sub gap.
        return


def async_client() -> AsyncRedis:
    return AsyncRedis.from_url(REDIS_URL, decode_responses=True, socket_timeout=5,
                               socket_connect_timeout=1)


def redis_ready() -> bool:
    try:
        client = Redis.from_url(REDIS_URL, socket_timeout=1)
        ready = bool(client.ping())
        client.close()
        return ready
    except Exception:
        return False


@contextmanager
def node_lock(workflow_id: str, node_name: str, timeout: int = 1800):
    client = Redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=2)
    lock = client.lock(f"workflow:{workflow_id}:node:{node_name}", timeout=timeout, blocking_timeout=1)
    acquired = False
    try:
        try:
            acquired = bool(lock.acquire())
        except Exception:
            # Database claiming remains the correctness boundary.
            acquired = True
        if not acquired:
            raise RuntimeError("workflow node is already executing")
        yield
    finally:
        if acquired:
            try:
                lock.release()
            except Exception:
                pass
        client.close()


def allow_user_request(user_id: str, limit: int = 30, window_seconds: int = 60) -> bool:
    """Best-effort distributed admission control; billing/idempotency remain durable."""
    try:
        client = Redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=1)
        key = f"rate:workflow:{user_id}"
        with client.pipeline() as pipe:
            pipe.incr(key)
            pipe.expire(key, window_seconds, nx=True)
            count, _ = pipe.execute()
        client.close()
        return int(count) <= limit
    except Exception:
        return True
