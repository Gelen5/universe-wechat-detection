from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from server import database
from server.models import Base, users_table
from server.workflow_billing import InsufficientPoints, create_billed_workflow


class WorkflowBillingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        engine = create_engine(f"sqlite:///{Path(self.temp.name, 'billing.db').as_posix()}")
        Base.metadata.create_all(engine)
        database.ENGINE = engine
        database.SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
        with engine.begin() as connection:
            connection.execute(users_table.insert(), {"id": "payer", "email": "payer@example.com", "display_name": "P",
                "password_hash": "x", "role": "user", "status": "active", "created_at": "2026-01-01"})
            connection.execute(text("CREATE TABLE wallets (user_id TEXT PRIMARY KEY, balance INTEGER, trial_balance INTEGER, bonus_balance INTEGER, paid_balance INTEGER, updated_at TEXT)"))
            connection.execute(text("CREATE TABLE pricing_rules (method TEXT, path TEXT, feature TEXT, points INTEGER, estimated_cost_micros INTEGER, active INTEGER, updated_at TEXT, PRIMARY KEY(method,path))"))
            connection.execute(text("CREATE TABLE point_transactions (id TEXT PRIMARY KEY,user_id TEXT,amount INTEGER,balance_before INTEGER,balance_after INTEGER,bucket TEXT,kind TEXT,source TEXT,feature TEXT,request_id TEXT,operator_id TEXT,note TEXT,allocation_json TEXT,created_at TEXT)"))
            connection.execute(text("CREATE TABLE usage_records (request_id TEXT PRIMARY KEY,user_id TEXT,method TEXT,path TEXT,feature TEXT,points INTEGER,status TEXT,http_status INTEGER,duration_ms INTEGER,estimated_cost_micros INTEGER,allocation_json TEXT,created_at TEXT,finished_at TEXT)"))
            connection.execute(text("INSERT INTO wallets VALUES ('payer',100,60,20,20,'now')"))
            connection.execute(text("INSERT INTO pricing_rules VALUES ('POST','/api/workbench/sessions','完整工作流',30,0,1,'now')"))
        self.engine = engine

    def tearDown(self):
        self.engine.dispose()
        self.temp.cleanup()

    def scalar(self, sql):
        with self.engine.connect() as connection:
            return connection.scalar(text(sql))

    def test_reservation_and_workflow_commit_together(self):
        workflow, replay = create_billed_workflow("payer", "billing-key", "interactive", {"topic": "A"})
        self.assertFalse(replay)
        self.assertEqual(70, self.scalar("SELECT balance FROM wallets WHERE user_id='payer'"))
        self.assertEqual(1, self.scalar("SELECT COUNT(*) FROM usage_records"))
        self.assertEqual(workflow["usage_id"], self.scalar("SELECT request_id FROM usage_records"))

    def test_idempotent_replay_does_not_charge_twice(self):
        first, _ = create_billed_workflow("payer", "same-billing", "interactive", {})
        second, replay = create_billed_workflow("payer", "same-billing", "interactive", {})
        self.assertTrue(replay)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(70, self.scalar("SELECT balance FROM wallets WHERE user_id='payer'"))
        self.assertEqual(1, self.scalar("SELECT COUNT(*) FROM point_transactions"))

    def test_insufficient_balance_writes_nothing(self):
        with self.engine.begin() as connection:
            connection.execute(text("UPDATE wallets SET balance=5,trial_balance=5,bonus_balance=0,paid_balance=0"))
        with self.assertRaises(InsufficientPoints):
            create_billed_workflow("payer", "no-money", "interactive", {})
        self.assertEqual(0, self.scalar("SELECT COUNT(*) FROM workflow_sessions"))
        self.assertEqual(0, self.scalar("SELECT COUNT(*) FROM usage_records"))

    def test_failed_workflow_insert_rolls_back_wallet_and_ledger(self):
        with self.assertRaises(Exception):
            create_billed_workflow("payer", "bad-mode", "invalid", {})
        self.assertEqual(100, self.scalar("SELECT balance FROM wallets WHERE user_id='payer'"))
        self.assertEqual(0, self.scalar("SELECT COUNT(*) FROM usage_records"))
        self.assertEqual(0, self.scalar("SELECT COUNT(*) FROM point_transactions"))


if __name__ == "__main__":
    unittest.main()
