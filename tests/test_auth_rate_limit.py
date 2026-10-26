from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from server import auth_rate_limit as limits


class Down:
    def eval(self, *args):
        raise ConnectionError('redis unavailable')


@pytest.fixture(autouse=True)
def isolated_limits(monkeypatch):
    monkeypatch.setenv('AUTH_RATE_LIMIT_ENABLED', '1')
    monkeypatch.setattr(limits, '_local', OrderedDict())


def test_progressive_backoff_expires_and_does_not_lock_an_account_globally():
    client = Down()
    for _ in range(3):
        limits.record_auth_result('login', 'a@example.test', 'ip-a', False, client=client, now=100)
    blocked = limits.check_auth_attempt('login', 'a@example.test', 'ip-a', client=client, now=100)
    assert not blocked.allowed and blocked.retry_after == 1
    assert limits.check_auth_attempt('login', 'a@example.test', 'ip-b', client=client, now=100).allowed
    assert limits.check_auth_attempt('login', 'b@example.test', 'ip-a', client=client, now=100).allowed
    assert limits.check_auth_attempt('login', 'a@example.test', 'ip-a', client=client, now=102).allowed
    for _ in range(30):
        limits.record_auth_result('login', 'a@example.test', 'ip-a', False, client=client, now=102)
    blocked = limits.check_auth_attempt('login', 'a@example.test', 'ip-a', client=client, now=102)
    assert blocked.retry_after == 60
    assert limits.check_auth_attempt('login', 'a@example.test', 'ip-a', client=client, now=163).allowed
    limits.record_auth_result('login', 'a@example.test', 'ip-a', True, client=client, now=164)
    limits.record_auth_result('login', 'a@example.test', 'ip-a', False, client=client, now=164)
    assert limits.check_auth_attempt('login', 'a@example.test', 'ip-a', client=client, now=164).allowed


def test_ip_limit_cannot_be_evaded_by_rotating_accounts(monkeypatch):
    monkeypatch.setenv('AUTH_LOGIN_IP_LIMIT', '2')
    assert limits.check_auth_attempt('login', 'a', 'same-ip', client=Down(), now=100).allowed
    assert limits.check_auth_attempt('login', 'b', 'same-ip', client=Down(), now=100).allowed
    blocked = limits.check_auth_attempt('login', 'c', 'same-ip', client=Down(), now=100)
    assert not blocked.allowed and blocked.dimension == 'ip'
    assert limits.check_auth_attempt('login', 'c', 'same-ip', client=Down(), now=181).allowed


def test_redis_calls_are_atomic_and_do_not_include_plain_account_data():
    client = SimpleNamespace(eval=lambda *args: [0, 2, 17])
    with patch.object(client, 'eval', return_value=[0, 2, 17]) as evaluate:
        result = limits.check_auth_attempt('login', 'private@example.test', '192.0.2.1', client=client, now=100)
    assert result.retry_after == 17 and result.dimension == 'ip'
    keys = evaluate.call_args.args[2:5]
    assert all('private@example.test' not in key and '192.0.2.1' not in key for key in keys)


def test_application_does_not_trust_arbitrary_forwarded_header():
    request = SimpleNamespace(client=SimpleNamespace(host='192.0.2.10'), headers={'x-forwarded-for': 'spoofed'})
    assert limits.client_ip(request) == '192.0.2.10'


def test_local_outage_fallback_is_bounded():
    for index in range(4200):
        limits.record_auth_result('login', str(index), 'ip', False, client=Down(), now=100)
    assert len(limits._local) == 4096


def test_invalid_redis_connection_configuration_still_uses_fallback():
    with patch.object(limits, '_connection', side_effect=ValueError('bad redis URL')):
        assert limits.check_auth_attempt('login', 'a', 'ip', now=100).allowed
        for _ in range(3):
            limits.record_auth_result('login', 'a', 'ip', False, now=100)
        assert not limits.check_auth_attempt('login', 'a', 'ip', now=100).allowed
