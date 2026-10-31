"""拉新活动的账要经得起核对：发出去的分要能对上，重复触发不能重复发。

奖励只认「跑完一次扣分任务」，所以每个用例都走真实的 reserve → settle 链路，
而不是直接调发放函数。
"""
import unittest

from fastapi.testclient import TestClient

from tests import support  # noqa: F401 - configures isolated account database before app import
from server import accounts, referrals
from server.main import app

PAID_PATH = "/api/hit-detector/analyze"  # 5 积分的真实收费接口


def _wallet(user_id):
    return accounts.wallet_summary(user_id)


def _run_paid_task(user_id):
    """真实走一次扣分任务并结算，返回 usage id。"""
    rule = accounts.pricing_rule("POST", PAID_PATH)
    usage = accounts.reserve_points(user_id, rule, "POST", PAID_PATH)
    accounts.settle_usage(usage, 200, 12)
    return usage


def _register(client, email, ref=""):
    payload = {"email": email, "password": "testing-pass-123", "display_name": email.split("@")[0]}
    if ref:
        payload["ref"] = ref
    response = client.post("/api/auth/register", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


class ReferralTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def _inviter(self):
        data = _register(self.client, f"inviter-{id(self)}@example.com")
        return data["user"]

    # ---- 绑定与注册奖励 ----

    def test_valid_code_credits_bonus_once_and_records_pending_referral(self):
        inviter = self._inviter()
        code = referrals.ensure_code(inviter["id"])
        invitee = _register(TestClient(app), f"invitee-{id(self)}@example.com", ref=code)

        self.assertEqual("bound", invitee["referral"]["status"])
        self.assertEqual(10, invitee["referral"]["bonus"])
        self.assertEqual(10, _wallet(invitee["user"]["id"])["bonus"])
        # 奖励只进 bonus 桶：不能变成试用额度，更不能变成可提现的付费积分。
        self.assertEqual(0, _wallet(invitee["user"]["id"])["trial"])
        self.assertEqual(0, _wallet(invitee["user"]["id"])["paid"])

        summary = referrals.summary(inviter["id"])
        self.assertEqual(1, summary["counts"]["total"])
        self.assertEqual(1, summary["counts"]["pending"])
        self.assertEqual(1, len(summary["invitees"]))
        self.assertNotIn("invitee-", summary["invitees"][0]["email"])

    def test_lowercase_and_padded_code_still_matches(self):
        inviter = self._inviter()
        code = referrals.ensure_code(inviter["id"])
        invitee = _register(TestClient(app), f"loose-{id(self)}@example.com", ref=f"  {code.lower()} ")
        self.assertEqual("bound", invitee["referral"]["status"])

    def test_unknown_code_never_blocks_registration(self):
        data = _register(TestClient(app), f"nocode-{id(self)}@example.com", ref="ZZZZZZ")
        self.assertEqual("ignored", data["referral"]["status"])
        self.assertEqual("code_not_found", data["referral"]["reason"])
        self.assertIsNotNone(data["user"]["id"])
        self.assertEqual(0, _wallet(data["user"]["id"])["bonus"])

    def test_self_referral_is_rejected(self):
        inviter = self._inviter()
        code = referrals.ensure_code(inviter["id"])
        result = referrals.bind_signup(inviter["id"], code, "1.1.1.1")
        self.assertEqual("self_referral", result["reason"])
        self.assertEqual(0, referrals.summary(inviter["id"])["counts"]["total"])

    def test_same_invitee_cannot_be_claimed_twice(self):
        inviter = self._inviter()
        other = _register(TestClient(app), f"second-{id(self)}@example.com")["user"]
        code = referrals.ensure_code(inviter["id"])
        invitee = _register(TestClient(app), f"once-{id(self)}@example.com", ref=code)["user"]

        result = referrals.bind_signup(invitee["id"], referrals.ensure_code(other["id"]), "2.2.2.2")
        self.assertEqual("already_referred", result["reason"])
        self.assertEqual(10, _wallet(invitee["id"])["bonus"])

    def test_same_ip_is_capped_per_inviter(self):
        inviter = self._inviter()
        code = referrals.ensure_code(inviter["id"])
        for index in range(referrals.INVITE_IP_SAME_INVITER_CAP):
            invitee = _register(TestClient(app), f"ip-{index}-{id(self)}@example.com")["user"]
            self.assertEqual("bound", referrals.bind_signup(invitee["id"], code, "9.9.9.9")["status"])
        overflow = _register(TestClient(app), f"ip-over-{id(self)}@example.com")["user"]
        self.assertEqual("ip_repeated", referrals.bind_signup(overflow["id"], code, "9.9.9.9")["reason"])
        # 换一个来源 IP 就能继续，说明卡的是异常聚集而不是正常分享。
        fresh = _register(TestClient(app), f"ip-fresh-{id(self)}@example.com")["user"]
        self.assertEqual("bound", referrals.bind_signup(fresh["id"], code, "8.8.4.4")["status"])

    def test_daily_cap_stops_more_bindings(self):
        inviter = self._inviter()
        code = referrals.ensure_code(inviter["id"])
        for index in range(referrals.INVITE_DAILY_CAP):
            invitee = _register(TestClient(app), f"day-{index}-{id(self)}@example.com")["user"]
            result = referrals.bind_signup(invitee["id"], code, f"10.0.0.{index}")
            self.assertEqual("bound", result["status"], result.get("reason", ""))
        overflow = _register(TestClient(app), f"day-over-{id(self)}@example.com")["user"]
        self.assertEqual("daily_cap", referrals.bind_signup(overflow["id"], code, "10.0.0.99")["reason"])
        self.assertEqual(referrals.INVITE_DAILY_CAP, referrals.summary(inviter["id"])["counts"]["total"])

    # ---- 激活与双向奖励 ----

    def test_first_paid_task_pays_both_sides_exactly_once(self):
        inviter = self._inviter()
        code = referrals.ensure_code(inviter["id"])
        invitee = _register(TestClient(app), f"active-{id(self)}@example.com", ref=code)["user"]

        usage = _run_paid_task(invitee["id"])
        self.assertEqual(referrals.INVITE_ACTIVATE_INVITER, _wallet(inviter["id"])["bonus"])
        # 注册 10 + 激活 10，再扣掉这次任务的 5 分。
        self.assertEqual(10 + referrals.INVITE_ACTIVATE_INVITEE - 5, _wallet(invitee["id"])["bonus"])
        self.assertEqual("rewarded", referrals.summary(inviter["id"])["invitees"][0]["status"])

        # 重复触发（重放同一次结算）不能重复发钱。
        referrals.on_usage_completed(usage)
        self.assertEqual(referrals.INVITE_ACTIVATE_INVITER, _wallet(inviter["id"])["bonus"])

        # 第二次任务不再触发奖励。
        accounts.recharge(_owner_id(), invitee["id"], 50, "trial", "测试充值")
        _run_paid_task(invitee["id"])
        self.assertEqual(referrals.INVITE_ACTIVATE_INVITER, _wallet(inviter["id"])["bonus"])

    def test_zero_point_step_does_not_activate(self):
        inviter = self._inviter()
        code = referrals.ensure_code(inviter["id"])
        invitee = _register(TestClient(app), f"free-{id(self)}@example.com", ref=code)["user"]

        rule = accounts.pricing_rule("POST", "/api/workbench/steps")
        usage = accounts.reserve_points(invitee["id"], rule, "POST", "/api/workbench/steps")
        accounts.settle_usage(usage, 200, 5)

        self.assertEqual(0, _wallet(inviter["id"])["bonus"])
        self.assertEqual("pending", referrals.summary(inviter["id"])["invitees"][0]["status"])

    def test_activation_of_unreferred_user_is_a_noop(self):
        loner = _register(TestClient(app), f"loner-{id(self)}@example.com")["user"]
        accounts.recharge(_owner_id(), loner["id"], 30, "trial", "测试充值")
        _run_paid_task(loner["id"])
        self.assertEqual(0, _wallet(loner["id"])["bonus"])

    # ---- 接口 ----

    def test_summary_endpoint_returns_code_link_and_rules(self):
        _register(self.client, f"panel-{id(self)}@example.com")
        data = self.client.get("/api/referrals")
        self.assertEqual(200, data.status_code)
        body = data.json()["referrals"]
        self.assertEqual(6, len(body["code"]))
        self.assertEqual(f"/?ref={body['code']}", body["path"])
        self.assertEqual(10, body["rewards"]["signup"])
        self.assertEqual(referrals.INVITE_DAILY_CAP, body["caps"]["remaining_today"])

    def test_referrals_endpoint_requires_login(self):
        self.assertEqual(401, TestClient(app).get("/api/referrals").status_code)

    def test_admin_overview_exposes_funnel(self):
        inviter = self._inviter()
        code = referrals.ensure_code(inviter["id"])
        invitee = _register(TestClient(app), f"funnel-{id(self)}@example.com", ref=code)["user"]
        _run_paid_task(invitee["id"])

        admin = TestClient(app)
        admin.post("/api/auth/login", json={"email": "admin@example.com", "password": "testing-pass-123"})
        body = admin.get("/api/admin/overview").json()["referrals"]
        self.assertGreaterEqual(body["referrals"], 1)
        self.assertGreaterEqual(body["rewarded"], 1)
        self.assertGreaterEqual(body["activation_rate"], 0)
        # 每条记录注册时发 10 分，每条 rewarded 再发 15 + 10。账面上必须能对上。
        self.assertEqual(25 * body["rewarded"] + 10 * body["referrals"], body["points_granted"])


def _owner_id():
    with accounts.DB_LOCK, accounts._connect() as connection:
        return connection.execute(
            "SELECT id FROM users WHERE email=?", (accounts.OWNER_EMAIL,)
        ).fetchone()["id"]


class ReferralSchemaTests(unittest.TestCase):
    """线上是靠 init_schema 补表的：deploy.sh 用 --no-deps 起服务，
    compose 里的 migrate 服务不会跑，所以这条路径必须自己成立。
    """

    def test_init_schema_upgrades_a_database_that_predates_the_column(self):
        import sqlite3
        import tempfile
        from pathlib import Path

        from sqlalchemy import create_engine

        from server import database

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "old.db")
            raw = sqlite3.connect(path)
            raw.execute("CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT)")
            raw.commit()
            raw.close()

            engine = create_engine(f"sqlite:///{path.as_posix()}")
            previous = database.ENGINE
            database.ENGINE = engine
            try:
                referrals.init_schema()
                referrals.init_schema()  # 第二次必须是空操作
            finally:
                database.ENGINE = previous
                engine.dispose()

            check = sqlite3.connect(path)
            try:
                columns = {row[1] for row in check.execute("PRAGMA table_info(users)")}
                tables = {row[0] for row in check.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                indexes = {row[0] for row in check.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'")}
            finally:
                check.close()  # Windows 上不关连接，临时目录删不掉
        self.assertIn("invite_code", columns)
        self.assertIn("referrals", tables)
        self.assertIn("uq_users_invite_code", indexes)


class ReferralForeignKeyTests(unittest.TestCase):
    def test_clean_install_has_cascade_foreign_keys_so_deleting_a_user_leaves_no_orphan(self):
        """两条建表路径必须产出同一张表：SQLite 走 accounts.init_db 的建表语句。"""
        with accounts.DB_LOCK, accounts._connect() as connection:
            keys = connection.execute("PRAGMA foreign_key_list(referrals)").fetchall()
        targets = {(row["from"], row["table"], row["on_delete"]) for row in keys}
        self.assertIn(("inviter_id", "users", "CASCADE"), targets)
        self.assertIn(("invitee_id", "users", "CASCADE"), targets)


if __name__ == "__main__":
    unittest.main()
