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
            CREATE TABLE IF NOT EXISTS agent_customers(customer_id TEXT PRIMARY KEY,agent_id TEXT NOT NULL,created_at TEXT NOT NULL, CHECK(customer_id <> agent_id));
            CREATE TABLE IF NOT EXISTS agent_settlements(id TEXT PRIMARY KEY,request_key TEXT UNIQUE,agent_id TEXT,amount_cents INTEGER,operator_id TEXT,note TEXT,transfer_ref TEXT,created_at TEXT,UNIQUE(agent_id,transfer_ref));''')
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
        self.assertEqual(client.get('/api/agent/orders').status_code,403)
        self.assertEqual(client.get('/api/agent/balance').status_code,403)
        r=self.admin.post('/api/admin/agents',json={'email':email});self.assertEqual(r.status_code,200,r.text)
        code=client.get('/api/agent/me').json()['code']
        self.assertEqual(client.get('/api/agent/orders').status_code,200)
        self.assertEqual(client.get('/api/agent/balance').status_code,200)
        buyer=TestClient(app);_,customer=self.register(buyer,'buyer',agent=code)
        self.assertEqual(buyer.get('/api/admin/agents').status_code,403)
        body={'amount_cents':796,'request_key':'a'*32,'transfer_ref':'test-transfer','note':'test'}
        self.assertEqual(buyer.post('/api/admin/agents/'+agent+'/settlements',json=body).status_code,403)
        with accounts._connect() as c:
            c.execute("INSERT INTO alipay_orders(out_trade_no,app_id,subject,total_amount,status,refunded_amount,created_at,paid_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",('agent-test-order','app','test','19.90','PAID','0.00','2026-11-05 19:44:23','2026-11-05 19:44:23','2026-11-05 19:44:23'))
            c.execute("INSERT INTO alipay_recharges(out_trade_no,user_id,package_id,credits,amount,status,created_at) VALUES(?,?,?,?,?,?,?)",('agent-test-order',customer,'test',1,'19.90','CREDITED','2026-11-05 19:44:23'))
        self.assertEqual(client.get('/api/agent/balance').json()['pending_cents'],796)
        recorded=self.admin.post('/api/admin/agents/'+agent+'/settlements',json=body)
        self.assertEqual(recorded.status_code,200,recorded.text)
        self.assertEqual(client.get('/api/agent/balance').json()['pending_cents'],0)
        self.assertEqual(self.admin.post('/api/admin/agents/'+agent+'/settlements',json=body).json()['status'],'already_recorded')

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
