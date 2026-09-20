"""Redis-backed distributed limits for expensive Agent submissions."""
from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass

from redis import Redis


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
_SCRIPT = """
for i, key in ipairs(KEYS) do
  local current = tonumber(redis.call('GET', key) or '0')
  local limit = tonumber(ARGV[i])
  if current >= limit then
    return {0, i, redis.call('TTL', key)}
  end
end
for i, key in ipairs(KEYS) do
  local current = redis.call('INCR', key)
  if current == 1 then redis.call('EXPIRE', key, tonumber(ARGV[#KEYS + 1])) end
end
return {1, 0, tonumber(ARGV[#KEYS + 1])}
"""


@dataclass(frozen=True)
class LimitResult:
    allowed: bool
    dimension: str = ""
    retry_after: int = 0


def _token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def check_agent_submission(*, user_id: str, ip: str, skill_id: str,
                           client=None, now: int | None = None) -> LimitResult:
    """Consume one request from user, IP and Skill windows atomically.

    Redis is an availability control, not durable business state. A Redis
    outage therefore fails open; wallet reservation and idempotency remain the
    authoritative abuse and duplicate-charge safeguards.
    """
    window = max(10, int(os.getenv("AGENT_RATE_WINDOW_SECONDS", "60")))
    epoch = int(now or time.time()) // window
    dimensions = ("user", "ip", "skill")
    keys = [
        f"rate:agent:{epoch}:user:{_token(user_id)}",
        f"rate:agent:{epoch}:ip:{_token(ip or 'unknown')}",
        f"rate:agent:{epoch}:skill:{_token(user_id + ':' + (skill_id or 'auto'))}",
    ]
    limits = [
        max(1, int(os.getenv("AGENT_RATE_USER_PER_MINUTE", "10"))),
        max(1, int(os.getenv("AGENT_RATE_IP_PER_MINUTE", "30"))),
        max(1, int(os.getenv("AGENT_RATE_SKILL_PER_MINUTE", "8"))),
    ]
    owned = client is None
    redis = client or Redis.from_url(
        REDIS_URL, decode_responses=True, socket_timeout=0.25, socket_connect_timeout=0.15,
    )
    try:
        result = redis.eval(_SCRIPT, len(keys), *keys, *limits, window)
        allowed, index, ttl = int(result[0]), int(result[1]), int(result[2])
        return LimitResult(bool(allowed), "" if allowed else dimensions[index - 1],
                           max(1, ttl) if not allowed else 0)
    except Exception:
        return LimitResult(True)
    finally:
        if owned:
            try:
                redis.close()
            except Exception:
                pass
