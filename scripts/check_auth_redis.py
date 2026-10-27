"""Check Redis auth Lua atomically using isolated expiring test keys.

Run inside the app environment: python scripts/check_auth_redis.py
Only release-check:<uuid>:* keys are created and cleaned up.
"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import os, uuid, concurrent.futures
from redis import Redis
from server import auth_rate_limit as limits
os.environ['AUTH_RATE_LIMIT_ENABLED']='1'
os.environ['AUTH_LOGIN_IP_LIMIT']='60'
r=Redis.from_url(os.environ['REDIS_URL'], decode_responses=True)
assert r.ping(), 'Redis must be reachable for this integration check'
prefix='release-check:'+uuid.uuid4().hex+':'
original=limits._prefix
limits._prefix=lambda *args: tuple(prefix+k for k in original(*args))
try:
    def attempt(i):
        return limits.check_auth_attempt('login', 'test-'+str(i), 'isolated-ip', client=r).allowed
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        allowed=sum(pool.map(attempt, range(160)))
    assert allowed == 60, allowed
    for _ in range(3): limits.record_auth_result('login','backoff','other-ip',False,client=r)
    blocked=limits.check_auth_attempt('login','backoff','other-ip',client=r)
    assert not blocked.allowed and blocked.dimension=='backoff', blocked
    assert limits.check_auth_attempt('login','backoff','third-ip',client=r).allowed
    limits.record_auth_result('login','backoff','other-ip',True,client=r)
    assert limits.check_auth_attempt('login','backoff','other-ip',client=r).allowed
    assert not limits._local, 'Redis Lua failed and silently fell back to process-local limits'
    print('Redis Lua verified: concurrent 60/160 accepted; pair backoff, isolation and reset passed')
finally:
    keys=list(r.scan_iter(match=prefix+'*'))
    if keys: r.delete(*keys)
    print('Isolated release check keys removed:',len(keys))
