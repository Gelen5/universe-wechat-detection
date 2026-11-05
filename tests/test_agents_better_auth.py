import re
import uuid
import requests
from fastapi.testclient import TestClient
from tests import support
from tests.test_better_auth_registration import identity_process
from server import accounts
from server.main import app

def test_better_auth_agent_binding(monkeypatch, identity_process):
    monkeypatch.setenv('AUTH_ENGINE', 'better-auth')
    monkeypatch.setenv('AUTH_ACCEPT_LEGACY_SESSIONS', '0')
    monkeypatch.setenv('BETTER_AUTH_INTERNAL_URL', f"http://127.0.0.1:{identity_process['port']}")
    monkeypatch.setenv('AUTH_BRIDGE_SECRET', 'fixture-bridge-secret-at-least-32-characters')
    monkeypatch.setenv('BETTER_AUTH_URL', 'http://testserver')
    with accounts._connect() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS agent_profiles(user_id TEXT PRIMARY KEY,code TEXT UNIQUE NOT NULL,active BOOLEAN NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS agent_customers(customer_id TEXT PRIMARY KEY,agent_id TEXT NOT NULL,created_at TEXT NOT NULL);''')
    agent=accounts.create_user(uuid.uuid4().hex+'@example.test','Password12345','agent')
    code=uuid.uuid4().hex[:24].upper()
    with accounts._connect() as c:
        c.execute('INSERT INTO agent_profiles VALUES(?,?,?,?)',(agent['id'],code,True,accounts.utc_now()))
    email=uuid.uuid4().hex+'@example.test'
    with TestClient(app) as client:
        assert client.post('/api/auth/email-code',json={'email':email}).status_code==200
        delivered=requests.get(f"http://127.0.0.1:{identity_process['sink']}/",timeout=5).json()
        otp=re.search(r'\b\d{6}\b',delivered['text']).group()
        response=client.post('/api/auth/register',json={'email':email,'password':'Password12345','display_name':'buyer','email_code':otp,'agent':code})
        assert response.status_code==200,response.text
        assert response.json()['agent_attribution']=='bound'
        with accounts._connect() as c:
            assert c.execute('SELECT agent_id FROM agent_customers WHERE customer_id=?',(response.json()['user']['id'],)).fetchone()['agent_id']==agent['id']
