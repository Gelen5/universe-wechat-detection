from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server import conversation_repository as repo
from server import database
from server.models import Base, PointTransaction, UsageRecord, Wallet, users_table


class ConversationBillingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        engine = create_engine(
            f"sqlite:///{Path(self.temp.name, 'billing.db').as_posix()}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(engine)
        database.ENGINE = engine
        database.SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
        with engine.begin() as connection:
            connection.execute(users_table.insert(), {
                "id": "user-a", "email": "a@example.com", "display_name": "A",
                "password_hash": "x", "role": "user", "status": "active", "created_at": "2026",
            })
        with database.session_scope() as db:
            db.add(Wallet(user_id="user-a", balance=30, trial_balance=10,
                          bonus_balance=10, paid_balance=10, updated_at="2026"))
        self.conversation = repo.create_conversation(
            "user-a", skill_id="wechat_writer", mode="manual")

    def tearDown(self):
        database.ENGINE.dispose()
        self.temp.cleanup()

    def create(self, key: str):
        return repo.create_message_run(
            self.conversation["id"], "user-a", "写文章", key,
            reserve_points=10, feature="公众号创作",
        )

    def wallet(self):
        with database.session_scope() as db:
            row = db.get(Wallet, "user-a")
            return row.balance, row.trial_balance, row.bonus_balance, row.paid_balance

    def test_idempotent_message_reserves_once_and_cancel_refunds_once(self):
        _, run, replay = self.create("billing-cancel")
        self.assertFalse(replay)
        self.assertEqual((20, 0, 10, 10), self.wallet())
        _, repeated, replay = self.create("billing-cancel")
        self.assertTrue(replay)
        self.assertEqual(run["id"], repeated["id"])
        self.assertEqual((20, 0, 10, 10), self.wallet())

        repo.cancel_run(run["id"], "user-a")
        repo.cancel_run(run["id"], "user-a")
        self.assertEqual((30, 10, 10, 10), self.wallet())
        with database.session_scope() as db:
            usage = db.get(UsageRecord, run["usage_id"])
            self.assertEqual("refunded", usage.status)
            self.assertEqual(1, db.query(PointTransaction).filter_by(kind="refund").count())

    def test_failed_run_refunds_but_completed_run_settles(self):
        _, failed, _ = self.create("billing-failed")
        repo.transition_run(failed["id"], "user-a", "failed", error_code="test")
        self.assertEqual((30, 10, 10, 10), self.wallet())

        _, completed, _ = self.create("billing-completed")
        repo.transition_run(completed["id"], "user-a", "completed")
        self.assertEqual((20, 0, 10, 10), self.wallet())
        with database.session_scope() as db:
            self.assertEqual("completed", db.get(UsageRecord, completed["usage_id"]).status)

    def test_provider_usage_is_attributed_to_run_and_settled(self):
        _, run, _ = self.create("billing-provider")
        repo.record_provider_call(
            run["id"], "user-a", provider="compatible", model="text-model",
            input_tokens=120, output_tokens=80, latency_ms=321,
            estimated_cost_micros=4321,
        )
        repo.transition_run(run["id"], "user-a", "completed")
        with database.session_scope() as db:
            usage = db.get(UsageRecord, run["usage_id"])
            self.assertEqual("completed", usage.status)
            self.assertEqual("compatible", usage.provider)
            self.assertEqual("text-model", usage.model)
            self.assertEqual(4321, usage.actual_cost_micros)

    def test_insufficient_points_writes_no_message_run_or_usage(self):
        with database.session_scope() as db:
            wallet = db.get(Wallet, "user-a")
            wallet.balance = wallet.trial_balance = wallet.bonus_balance = wallet.paid_balance = 0
        with self.assertRaises(repo.InsufficientPoints):
            self.create("billing-insufficient")
        self.assertEqual([], repo.list_messages(self.conversation["id"], "user-a"))
        with database.session_scope() as db:
            self.assertEqual(0, db.query(UsageRecord).count())


if __name__ == "__main__":
    unittest.main()
