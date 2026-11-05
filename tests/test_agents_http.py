"""HTTP-level regression for registration attribution and access control."""
import sqlite3
import unittest
import uuid
from fastapi.testclient import TestClient
from tests import support
from server import accounts, owner_revenue
from server.main import app

class AgentHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_owner=owner_revenue.OWNER
        owner_revenue.OWNER = 'admin@example.com'
        with accounts._connect() as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS agent_profiles(user_id TEXT PRIMARY KEY, code TEXT UNIQUE NOT NULL,active BOOLEAN NOT NULL,created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS agent_customers(customer_id TEXT PRIMARY KEY,agent_id TEXT NOT NULL,created_at TEXT NOT NULL, CHECK(customer_id <> agent_id));''')
        cls.admin=TestClient(app)
        r=cls.admin.post('/api/auth/login',json={'email':'admin@example.com','password':'testing-pass-123'})
        assert r.status_code==200,r.text
    @classmethod
    def tearDownClass(cls):
        owner_revenue.OWNER=cls.old_owner

    def register(self, client, prefix, **kwargs):
        email=prefix+'-'+uuid.uuid4().hex[:10]+'@example.com'
        r=client.post('/api/auth/register',json={'email':email,'password':'testing-pass-123','display_name':'test',**kwargs})
        self.assertEqual(r.status_code,200,r.text)
        return email,r.json()['user']['id']
    def test_registration_login_and_permission(self):
        client=TestClient(app);email,agent=self.register(client,'agent')
        self.assertEqual(client.get('/api/admin/agents').status_code,403)
        self.assertEqual(client.get('/api/agent/me').status_code,403)
        r=self.admin.post('/api/admin/agents',json={'email':email});self.assertEqual(r.status_code,200,r.text)
        code=client.get('/api/agent/me').json()['code']
        buyer=TestClient(app);_,customer=self.register(buyer,'buyer',agent=code)
        self.assertEqual(buyer.get('/api/admin/agents').status_code,403)
        with accounts._connect() as c:
            self.assertEqual(c.execute('SELECT agent_id FROM agent_customers WHERE customer_id=?',(customer,)).fetchone()['agent_id'],agent)
        self.assertEqual(buyer.post('/api/auth/login',json={'email':email,'password':'testing-pass-123'}).status_code,200)
        with accounts._connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM agent_customers WHERE customer_id=?',(agent,)).fetchone()[0],0)
        self.assertEqual(self.admin.post('/api/admin/agents/'+agent+'/active',json={'active':False}).status_code,200)
        _,unbound=self.register(TestClient(app),'stopped',agent=code)
        with accounts._connect() as c:
            self.assertIsNone(c.execute('SELECT * FROM agent_customers WHERE customer_id=?',(unbound,)).fetchone())

if __name__=='__main__': unittest.main()
