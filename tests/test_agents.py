"""Agent attribution tests use isolated SQLite, never real payment data."""
import sqlite3
import tempfile
from contextlib import closing
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import support  # Configure isolated database before server imports.
from server import accounts, agents, agent_schema
from sqlalchemy import create_engine, text

class AgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = accounts.DB_PATH
        accounts.DB_PATH = Path(self.tmp.name) / 'test.db'
        with closing(sqlite3.connect(accounts.DB_PATH)) as c:
            c.executescript('''CREATE TABLE users(id TEXT PRIMARY KEY,email TEXT,status TEXT,display_name TEXT);
            CREATE TABLE agent_profiles(user_id TEXT PRIMARY KEY,code TEXT UNIQUE,active BOOLEAN,created_at TEXT);
            CREATE TABLE agent_customers(customer_id TEXT PRIMARY KEY,agent_id TEXT,created_at TEXT,CHECK(customer_id <> agent_id));
            CREATE TABLE alipay_orders(out_trade_no TEXT PRIMARY KEY,total_amount TEXT,refunded_amount TEXT,status TEXT,paid_at TEXT,created_at TEXT);
            CREATE TABLE alipay_recharges(out_trade_no TEXT PRIMARY KEY,user_id TEXT,status TEXT);
            INSERT INTO users VALUES('a','agent@example.com','active','Agent'),('b','buyer@example.com','active','Buyer'),('x','other@example.com','active','Other');
            INSERT INTO agent_profiles VALUES('a','ABC',1,'2026-01-01'),('x','STOP',0,'2026-01-01');''')
            c.commit()
    def tearDown(self):
        accounts.DB_PATH = self.old_path
        self.tmp.cleanup()
    def rows(self, sql):
        with closing(sqlite3.connect(accounts.DB_PATH)) as c:
            return c.execute(sql).fetchall()
    def test_bind_and_no_rebind(self):
        agents.bind_signup('b','ABC'); agents.bind_signup('b','STOP'); agents.bind_signup('a','ABC')
        self.assertEqual(self.rows('SELECT customer_id,agent_id FROM agent_customers'), [('b','a')])
    def test_unknown_and_disabled(self):
        agents.bind_signup('b','BAD'); agents.bind_signup('b','STOP')
        self.assertEqual(self.rows('SELECT * FROM agent_customers'), [])
    def test_reports_only_paid_credited_orders_and_refunds(self):
        agents.bind_signup('b','ABC')
        with closing(sqlite3.connect(accounts.DB_PATH)) as c:
            c.executescript("""INSERT INTO alipay_orders VALUES('paid','10.00','3.00','PARTIAL_REFUNDED','2026-01-01','2026-01-01'),('unpaid','8.00','0.00','CREATED',NULL,'2026-01-01');
            INSERT INTO alipay_recharges VALUES('paid','b','CREDITED'),('unpaid','b','PENDING');""")
            c.commit()
        with patch.object(agents,'require_owner'):
            data=agents.agent_orders('a',None)
        self.assertEqual(data['total'], 1)
        self.assertEqual(data['orders'][0]['refunded_amount'], '3.00')
        self.assertNotIn('paid_cents',data['orders'][0])
    def test_targeted_installer_is_idempotent_and_preserves_migration_marker(self):
        db_file=Path(self.tmp.name) / 'schema.db'
        engine=create_engine(f'sqlite:///{db_file.as_posix()}')
        with engine.begin() as c:
            c.execute(text('CREATE TABLE users (id varchar(64) PRIMARY KEY)'))
            c.execute(text('CREATE TABLE alembic_version (version_num varchar(32))'))
            c.execute(text("INSERT INTO alembic_version VALUES ('20261025_0009')"))
            agent_schema.install(c)
            agent_schema.install(c)
            self.assertEqual(c.execute(text('SELECT version_num FROM alembic_version')).scalar(), '20261025_0009')
        engine.dispose()
    def test_admin_permission_is_required(self):
        with patch.object(agents, 'require_owner', side_effect=agents.HTTPException(403)):
            with self.assertRaises(agents.HTTPException): agents.list_agents(None)

if __name__ == '__main__': unittest.main()
