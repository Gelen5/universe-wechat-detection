from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from unittest.mock import patch
import uuid
import pytest
from server import accounts

accounts.init_db()


def new_user():
    return accounts.create_user(f'checkin-{uuid.uuid4().hex}@example.com', 'test-password-123', '签到测试')['id']


def test_beijing_day_rollover():
    assert accounts.checkin_day(datetime(2026, 11, 5, 15, 59, tzinfo=timezone.utc)) == '2026-11-05'
    assert accounts.checkin_day(datetime(2026, 11, 5, 16, 0, tzinfo=timezone.utc)) == '2026-11-06'


def test_daily_checkin_concurrency_and_ledger():
    user = new_user()
    before = accounts.wallet_summary(user)
    now = datetime(2026, 11, 5, 16, 0, tzinfo=timezone.utc)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: accounts.daily_checkin(user, now=now), range(12)))
    assert sum(bool(x['credited']) for x in results) == 1
    wallet = accounts.wallet_summary(user)
    assert wallet['balance'] == before['balance'] + 5
    assert wallet['bonus'] == before['bonus'] + 5
    records = [x for x in accounts.list_transactions(user) if x['source'] == 'daily_checkin']
    assert len(records) == 1 and records[0]['amount'] == 5 and records[0]['feature'] == '每日签到'
    assert accounts.checkin_status(user, now=now)['checked_in']
    tomorrow = datetime(2026, 11, 6, 16, 0, tzinfo=timezone.utc)
    assert not accounts.checkin_status(user, now=tomorrow)['checked_in']
    assert accounts.daily_checkin(user, now=tomorrow)['credited']
    assert accounts.wallet_summary(user)['balance'] == before['balance'] + 10


def test_failed_credit_rolls_back():
    user = new_user(); before = accounts.wallet_summary(user)
    def fail(connection, user_id, *args, **kwargs):
        connection.execute('UPDATE wallets SET balance=balance+5,bonus_balance=bonus_balance+5 WHERE user_id=?', (user_id,))
        raise RuntimeError('test rollback')
    with patch.object(accounts, 'credit_bucket', side_effect=fail), pytest.raises(RuntimeError):
        accounts.daily_checkin(user)
    assert accounts.wallet_summary(user)['balance'] == before['balance']
    assert not accounts.checkin_status(user)['checked_in']


def test_checkin_http_requires_login_and_is_idempotent():
    from fastapi.testclient import TestClient
    from server.main import app
    email = f'checkin-http-{uuid.uuid4().hex}@example.com'
    accounts.create_user(email, 'test-password-123', '签到接口')
    with TestClient(app) as client:
        assert client.get('/api/checkin').status_code == 401
        assert client.post('/api/checkin').status_code == 401
        login = client.post('/api/auth/login', json={'email':email, 'password':'test-password-123'})
        assert login.status_code == 200
        before = login.json()['wallet']['balance']
        wallet_page = client.get('/wallet')
        assert wallet_page.status_code == 200
        assert 'daily-checkin-wallet' in wallet_page.text
        assert '/static/daily-checkin.js' in wallet_page.text
        assert client.get('/api/checkin').json()['checked_in'] is False
        first = client.post('/api/checkin')
        second = client.post('/api/checkin')
        assert first.status_code == second.status_code == 200
        assert first.json()['credited'] is True and second.json()['credited'] is False
        assert second.json()['wallet']['balance'] == before + 5
        assert client.get('/api/wallet').json()['transactions'][0]['feature'] == '每日签到'
