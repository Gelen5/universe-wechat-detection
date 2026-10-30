"""Actual Better Auth Node process + FastAPI + isolated SQLite business ledger.

Only email delivery is a local sink. No live user or provider is contacted.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import uuid

import pytest
import requests
from fastapi import HTTPException
from fastapi import Request, Response
from fastapi.testclient import TestClient
from tests import support  # noqa: F401
from server import accounts, better_auth_bridge
from server.main import app


@pytest.fixture(scope='module')
def identity_process():
    root = Path(__file__).resolve().parents[1]
    process = subprocess.Popen(['node', 'auth-service/test/bridge-fixture.mjs'], cwd=root,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        line = process.stdout.readline().strip()
        assert line.startswith('READY '), line
        yield json.loads(line[6:])
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_real_registration_verifies_email_before_wallet_and_grants_once(identity_process, monkeypatch):
    monkeypatch.setenv('AUTH_ENGINE', 'better-auth')
    monkeypatch.setenv('BETTER_AUTH_INTERNAL_URL', f"http://127.0.0.1:{identity_process['port']}")
    monkeypatch.setenv('AUTH_BRIDGE_SECRET', 'fixture-bridge-secret-at-least-32-characters')
    monkeypatch.setenv('BETTER_AUTH_URL', 'http://testserver')
    monkeypatch.setattr(accounts, 'NEW_USER_TRIAL_POINTS', 6)
    email = uuid.uuid4().hex + '@example.test'
    body = {'email':email,'password':'Password12345','display_name':'验证用户'}
    with TestClient(app) as client:
        config = client.get('/api/auth/config').json()
        assert config['auth_engine'] == 'better-auth'
        response = client.post('/api/auth/email-code', json={'email':email})
        assert response.status_code == 200, response.text
        with accounts._connect() as connection:
            assert connection.execute('SELECT 1 FROM users WHERE email=?',(email,)).fetchone() is None
        bad = client.post('/api/auth/register', json=body | {'email_code':'invalid'})
        assert bad.status_code >= 400
        with accounts._connect() as connection:
            assert connection.execute('SELECT 1 FROM users WHERE email=?',(email,)).fetchone() is None
        delivered = requests.get(f"http://127.0.0.1:{identity_process['sink']}/", timeout=5).json()
        code = re.search(r'\b\d{6}\b', delivered['text']).group()
        response = client.post('/api/auth/register', json=body | {'email_code':code})
        assert response.status_code == 200, response.text
        user_id = response.json()['user']['id']
        assert response.json()['wallet']['balance'] == 6
        assert any('better-auth' in name for name in client.cookies)
        assert client.get('/api/auth/me').json()['user']['id'] == user_id
        replay = client.post('/api/auth/register', json=body | {'email_code':code})
        assert replay.status_code == 409
        assert client.post('/api/auth/logout').status_code == 200
        assert client.get('/api/auth/me').status_code == 401
        login = client.post('/api/auth/login', json=body)
        assert login.status_code == 200, login.text
        assert login.json()['user']['id'] == user_id
        with accounts._connect() as connection:
            assert connection.execute('SELECT count(*) FROM wallets WHERE user_id=?',(user_id,)).fetchone()[0] == 1
            assert connection.execute("SELECT count(*) FROM point_transactions WHERE user_id=? AND feature='新用户试用'",(user_id,)).fetchone()[0] == 1
        # A rollback can still authenticate this new account without a reset.
        assert accounts.authenticate(email,body['password'])['id'] == user_id
        with accounts._connect() as connection:
            connection.execute("UPDATE users SET status='disabled' WHERE id=?",(user_id,))
        assert client.get('/api/auth/me').status_code == 403


def test_bridge_rejects_unverified_identity_and_wrong_origin(monkeypatch):
    monkeypatch.setenv('BETTER_AUTH_URL', 'https://yuzoudiyigongzuotai.cn')
    with pytest.raises(HTTPException) as exc:
        better_auth_bridge.business_user({'id':uuid.uuid4().hex,'email':uuid.uuid4().hex+'@example.test','emailVerified':False})
    assert exc.value.status_code == 403
    monkeypatch.setenv('AUTH_ENGINE','better-auth')
    with TestClient(app) as client:
        result=client.post('/api/auth/login',json={'email':'a@example.test','password':'Password123'},headers={'Origin':'https://attacker.test'})
        assert result.status_code == 403


def test_identity_mismatch_cannot_link_existing_wallet(monkeypatch):
    user=accounts.create_user(uuid.uuid4().hex+'@example.test','Password123','旧用户')
    with pytest.raises(HTTPException):
        better_auth_bridge.business_user({'id':uuid.uuid4().hex,'email':user['email'],'emailVerified':True})
    with pytest.raises(HTTPException):
        better_auth_bridge.business_user({'id':user['id'],'email':'another@example.test','emailVerified':True})


def test_migrated_admin_impersonation_remains_bound_to_current_actor(monkeypatch):
    accounts.init_db()
    admin=accounts.authenticate('admin@example.com','testing-pass-123')
    target=accounts.create_user(uuid.uuid4().hex+'@example.test','Password123','代操作目标')
    response=Response()
    accounts.create_session(target['id'],response,impersonator_id=admin['id'])
    cookie=response.headers['set-cookie'].split(';')[0]+'; better-auth.session_token=synthetic'
    request=Request({'type':'http','headers':[(b'cookie',cookie.encode())]})
    monkeypatch.setenv('AUTH_ENGINE','better-auth')
    monkeypatch.setenv('AUTH_ACCEPT_LEGACY_SESSIONS','0')
    monkeypatch.setattr(better_auth_bridge,'from_request',lambda request:admin)
    assert accounts.user_from_request(request)['id']==target['id']
    monkeypatch.setattr(better_auth_bridge,'from_request',lambda request:target)
    assert accounts.user_from_request(request)['id']==target['id']
    monkeypatch.setattr(better_auth_bridge,'from_request',lambda request:None)
    assert accounts.user_from_request(request) is None


def test_readiness_reports_auth_outage_without_accepting_legacy_password(monkeypatch):
    monkeypatch.setenv('AUTH_ENGINE','better-auth')
    def unavailable(*args,**kwargs):
        raise HTTPException(503,'认证服务暂不可用')
    monkeypatch.setattr(better_auth_bridge,'call',unavailable)
    with TestClient(app) as client:
        response=client.get('/health/ready')
        assert response.status_code == 503
        assert response.json()['checks']['better_auth'] is False
        response=client.post('/api/auth/login',json={'email':'admin@example.com','password':'testing-pass-123'})
        assert response.status_code == 503
