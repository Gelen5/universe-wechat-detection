"""Web 重启后回收进程内挂起任务：只退该退的，绝不误伤活任务。"""
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from server import accounts, database, main


def _iso(age_seconds):
    return (datetime.now(timezone.utc) - timedelta(seconds=age_seconds)).isoformat()


class JobRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / 'accounts.db'
        self.engine = create_engine('sqlite://', poolclass=StaticPool,
                                    connect_args={'check_same_thread': False})
        self.patches = [
            patch.object(accounts, 'DB_PATH', self.db_path),
            patch.object(database, 'ENGINE', self.engine),
        ]
        for item in self.patches:
            item.start()
        accounts.init_db()
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute(
                "INSERT INTO users(id,email,display_name,password_hash,created_at) VALUES (?,?,?,?,?)",
                ('u1', 'u1@example.test', 'u1', 'x', _iso(0)),
            )
            connection.commit()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.engine.dispose()
        self.tmp.cleanup()

    def _insert(self, job_id, job_type, status, age, usage_id=None, started=True):
        created = _iso(age)
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute(
                """INSERT INTO jobs(id,user_id,type,lane,idempotency_key,usage_id,status,
                                    payload_json,created_at,started_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (job_id, 'u1', job_type, 'text', 'key-' + job_id, usage_id, status,
                 '{}', created, created if started else None),
            )
            connection.commit()

    def _status(self, job_id):
        with closing(sqlite3.connect(self.db_path)) as connection:
            row = connection.execute('SELECT status FROM jobs WHERE id=?', (job_id,)).fetchone()
        return row[0] if row else None

    def test_recovers_stale_running_and_queued(self):
        self._insert('j1', 'creator_chat', 'running', 7200, 'usage-1', True)
        self._insert('j2', 'tie_tu', 'queued', 7200, 'usage-2', False)
        with patch.object(accounts, 'refund_usage') as refund:
            self.assertEqual(2, accounts.recover_interrupted_jobs(grace_seconds=900))
        self.assertEqual('failed', self._status('j1'))
        self.assertEqual('failed', self._status('j2'))
        self.assertEqual(2, refund.call_count)

    def test_keeps_fresh_running_jobs(self):
        self._insert('j3', 'creator_chat', 'running', 30, 'usage-3', True)
        with patch.object(accounts, 'refund_usage') as refund:
            self.assertEqual(0, accounts.recover_interrupted_jobs(grace_seconds=900))
        self.assertEqual('running', self._status('j3'))
        refund.assert_not_called()

    def test_skips_celery_managed_types(self):
        self._insert('j4', 'article_visual.plan', 'running', 7200, 'usage-4', True)
        self._insert('j5', 'viral_remix.image', 'running', 7200, 'usage-5', True)
        with patch.object(accounts, 'refund_usage') as refund:
            self.assertEqual(0, accounts.recover_interrupted_jobs(grace_seconds=900))
        self.assertEqual('running', self._status('j4'))
        self.assertEqual('running', self._status('j5'))
        refund.assert_not_called()

    def test_skips_terminal_jobs(self):
        self._insert('j6', 'creator_chat', 'completed', 7200, 'usage-6', True)
        with patch.object(accounts, 'refund_usage') as refund:
            self.assertEqual(0, accounts.recover_interrupted_jobs(grace_seconds=900))
        self.assertEqual('completed', self._status('j6'))
        refund.assert_not_called()

    def test_recovery_is_idempotent(self):
        self._insert('j7', 'creator_chat', 'running', 7200, 'usage-7', True)
        with patch.object(accounts, 'refund_usage') as refund:
            self.assertEqual(1, accounts.recover_interrupted_jobs(grace_seconds=900))
            self.assertEqual(0, accounts.recover_interrupted_jobs(grace_seconds=900))
        self.assertEqual(1, refund.call_count)

    def test_real_refund_restores_wallet_once(self):
        """不 mock refund_usage：验证积分真的回到钱包，且重复恢复不会二次退款。"""
        created = _iso(7200)
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute(
                """INSERT INTO wallets(user_id,balance,trial_balance,bonus_balance,paid_balance,updated_at)
                   VALUES (?,?,?,?,?,?)""",
                ('u1', 90, 90, 0, 0, created),
            )
            connection.execute(
                """INSERT INTO usage_records
                   (request_id,user_id,method,path,feature,points,status,allocation_json,created_at)
                   VALUES (?,?,?,?,?,?,'reserved',?,?)""",
                ('usage-real', 'u1', 'POST', '/api/creator/chat', 'creator_chat',
                 10, '{"trial": 10}', created),
            )
            connection.commit()
        self._insert('j-real', 'creator_chat', 'running', 7200, 'usage-real', True)

        self.assertEqual(1, accounts.recover_interrupted_jobs(grace_seconds=900))
        with closing(sqlite3.connect(self.db_path)) as connection:
            balance = connection.execute(
                'SELECT balance FROM wallets WHERE user_id=?', ('u1',)).fetchone()[0]
            usage_status = connection.execute(
                'SELECT status FROM usage_records WHERE request_id=?', ('usage-real',)).fetchone()[0]
            refund_count = connection.execute(
                "SELECT COUNT(*) FROM point_transactions WHERE kind='refund' AND request_id=?",
                ('usage-real:refund',)).fetchone()[0]
        self.assertEqual(100, balance)
        self.assertEqual('refunded', usage_status)
        self.assertEqual(1, refund_count)
        self.assertEqual('failed', self._status('j-real'))

        self.assertEqual(0, accounts.recover_interrupted_jobs(grace_seconds=900))
        with closing(sqlite3.connect(self.db_path)) as connection:
            balance = connection.execute(
                'SELECT balance FROM wallets WHERE user_id=?', ('u1',)).fetchone()[0]
        self.assertEqual(100, balance)

    def test_startup_invokes_recovery(self):
        env = {'CREATOR_JOB_RECOVERY_ENABLED': '1', 'ALIPAY_RECONCILE_ENABLED': '0'}
        with patch.object(accounts, 'recover_interrupted_jobs', return_value=2) as recover, \
             patch.dict(os.environ, env):
            with TestClient(main.app):
                pass
        self.assertGreaterEqual(recover.call_count, 1)

    def test_recovery_can_be_disabled(self):
        env = {'CREATOR_JOB_RECOVERY_ENABLED': '0', 'ALIPAY_RECONCILE_ENABLED': '0'}
        with patch.object(accounts, 'recover_interrupted_jobs') as recover, \
             patch.dict(os.environ, env):
            with TestClient(main.app):
                pass
        self.assertEqual(0, recover.call_count)


if __name__ == '__main__':
    unittest.main()
