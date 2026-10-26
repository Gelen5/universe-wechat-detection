"""Bounded login/registration attempts with distributed, expiring backoff.

Backoff is scoped to an account AND source IP, never a global account lock.
Redis outages use a bounded process-local fallback rather than disabling limits.
"""
from __future__ import annotations

import hashlib
import os
import threading
import time
from collections import OrderedDict

from redis import Redis
from .rate_limit import LimitResult

_CHECK = '''
local blocked = redis.call('TTL', KEYS[1])
if blocked > 0 then return {0, 1, blocked} end
for i = 2, 3 do
  if tonumber(redis.call('GET', KEYS[i]) or '0') >= tonumber(ARGV[i-1]) then
    return {0, i, math.max(1, redis.call('TTL', KEYS[i]))}
  end
end
for i = 2, 3 do
  if redis.call('INCR', KEYS[i]) == 1 then redis.call('EXPIRE', KEYS[i], ARGV[3]) end
end
return {1, 0, 0}
'''
_RESULT = '''
if ARGV[1] == '1' then
  redis.call('DEL', KEYS[1], KEYS[2])
  return 0
end
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], 900) end
if count >= 3 then
  local delay = math.min(60, math.pow(2, math.min(6, count - 3)))
  redis.call('SET', KEYS[2], '1', 'EX', delay)
  return delay
end
return 0
'''
_local = OrderedDict()
_lock = threading.RLock()


def _enabled():
    return os.getenv('AUTH_RATE_LIMIT_ENABLED', '1') != '0'


def _limit_setting(name, default):
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def client_ip(request) -> str:
    # Uvicorn resolves forwarded headers only from its trusted proxy allowlist.
    # Never trust a user-supplied X-Forwarded-For again at the application layer.
    return request.client.host if request.client else 'unknown'


def _prefix(action: str, identity: str, ip: str):
    digest = lambda value: hashlib.sha256(value.encode('utf-8')).hexdigest()[:32]
    return f'auth:{action}:ip:{digest(ip)}', f'auth:{action}:pair:{digest(ip + chr(0) + identity.strip().lower())}'


def _connection():
    return Redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379/0'),
                          socket_timeout=.15, socket_connect_timeout=.1, decode_responses=True)


def _get(key, now):
    value, expires = _local.get(key, (0, 0))
    if expires <= now:
        _local.pop(key, None)
        return 0, 0
    _local.move_to_end(key)
    return value, expires


def _set(key, value, expires):
    _local[key] = (value, expires)
    _local.move_to_end(key)
    while len(_local) > 4096:
        _local.popitem(last=False)


def check_auth_attempt(action: str, identity: str, ip: str, *, client=None, now=None) -> LimitResult:
    if not _enabled():
        return LimitResult(True)
    clock = time.time() if now is None else now
    window = 60 if action == 'login' else 900
    ip_limit = _limit_setting('AUTH_LOGIN_IP_LIMIT' if action == 'login' else 'AUTH_REGISTER_IP_LIMIT',
                             60 if action == 'login' else 20)
    pair_limit = 10
    ip_key, pair = _prefix(action, identity, ip)
    keys = [pair + ':blocked', ip_key + f':{int(clock) // window}', pair + f':{int(clock) // window}']
    owned = client is None
    redis = client
    try:
        if redis is None:
            redis = _connection()
        allowed, dimension, ttl = map(int, redis.eval(_CHECK, 3, *keys, ip_limit, pair_limit, window))
        return LimitResult(bool(allowed), '' if allowed else ('backoff', 'ip', 'account_ip')[dimension - 1],
                           0 if allowed else max(1, ttl))
    except Exception:
        with _lock:
            _, until = _get(keys[0], clock)
            if until:
                return LimitResult(False, 'backoff', max(1, int(until - clock + .999)))
            for key, limit in zip(keys[1:], (ip_limit, pair_limit)):
                count, until = _get(key, clock)
                if count >= limit:
                    return LimitResult(False, 'ip' if key == keys[1] else 'account_ip', max(1, int(until - clock + .999)))
            for key in keys[1:]:
                count, until = _get(key, clock)
                _set(key, count + 1, until or clock + window)
            return LimitResult(True)
    finally:
        if owned:
            try: redis.close()
            except Exception: pass


def record_auth_result(action: str, identity: str, ip: str, success: bool, *, client=None, now=None):
    if not _enabled():
        return
    clock = time.time() if now is None else now
    _, pair = _prefix(action, identity, ip)
    keys = [pair + ':failures', pair + ':blocked']
    owned = client is None
    redis = client
    try:
        if redis is None:
            redis = _connection()
        redis.eval(_RESULT, 2, *keys, int(success))
    except Exception:
        with _lock:
            if success:
                for key in keys: _local.pop(key, None)
            else:
                count, until = _get(keys[0], clock)
                count += 1
                _set(keys[0], count, until or clock + 900)
                if count >= 3:
                    _set(keys[1], 1, clock + min(60, 2 ** min(6, count - 3)))
    finally:
        if owned:
            try: redis.close()
            except Exception: pass
