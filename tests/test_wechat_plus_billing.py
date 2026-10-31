"""公众号创作 Plus 的按动作计费。

三条不变量，任何一条破了都会让用户多付钱或者白嫖：

1. 预扣按最高档（12）走，结算按实际动作（闲聊 0 / 选题 2 / 成稿 12）。
2. 差额必须原路退回，三个钱包桶（trial / bonus / paid）的合计要跟 balance 对得上。
3. 失败、取消都必须全额退回；重试不能重复扣。

这里测的是 accounts 的结算算术和 API 的预扣时机；worker 那一层用假 action 直接调
settle/refund 覆盖。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tests.support  # noqa: F401,E402  先把数据库指向临时文件

from fastapi.testclient import TestClient  # noqa: E402

from server import accounts  # noqa: E402
from server.main import app  # noqa: E402


def wallet(user_id: str) -> dict:
    return accounts.wallet_summary(user_id)


def seed(user_id: str, points: int = 100) -> None:
    with accounts._connect() as conn:
        conn.execute(
            "UPDATE wallets SET balance=?, trial_balance=?, bonus_balance=?, paid_balance=? WHERE user_id=?",
            (points, points, 0, 0, user_id),
        )


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def user_id(client):
    email = "plus-billing@example.com"
    password = "testing-pass-123"
    login = client.post("/api/auth/login", json={"email": email, "password": password})
    if login.status_code != 200:
        created = accounts.register(email, password, "计费测试")
        assert created
        login = client.post("/api/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200
    return login.json()["user"]["id"]


class TestPricingTable:
    def test_chat_is_free_and_writing_is_the_dear_side(self):
        assert accounts.PLUS_ACTION_POINTS["clarify"] == 0
        assert accounts.PLUS_ACTION_POINTS["answer"] == 0
        assert accounts.PLUS_ACTION_POINTS["write"] == 12
        assert accounts.PLUS_MAX_POINTS == 12

    def test_unknown_action_falls_back_to_the_ceiling(self):
        # 宁可多收后退，不能少收：新动作上线时默认按最高档，写完再补规则。
        assert accounts.plus_points_for("brand_new_action") == accounts.PLUS_MAX_POINTS
        assert accounts.plus_points_for(None) == accounts.PLUS_MAX_POINTS
        assert accounts.plus_points_for("revise") == 6

    def test_plus_paths_are_not_in_the_middleware_pricing_table(self):
        # 中间件按「方法+路径」计价，Plus 一条路径多种动作，必须由它自己管。
        assert accounts.pricing_rule("POST", "/api/wechat-plus/sessions/abc/messages") is None


class TestSettlement:
    def test_free_turn_refunds_everything(self, user_id):
        seed(user_id)
        usage = accounts.reserve_points(user_id, accounts.plus_rule(12), "POST", "/api/wechat-plus/x")
        assert wallet(user_id)["balance"] == 88
        accounts.refund_usage(usage, 200, 10)
        assert wallet(user_id)["balance"] == 100
        assert accounts.usage_state(usage) == "refunded"

    def test_partial_settlement_refunds_only_the_difference(self, user_id):
        seed(user_id)
        usage = accounts.reserve_points(user_id, accounts.plus_rule(12), "POST", "/api/wechat-plus/x")
        accounts.settle_usage_with_points(usage, 200, 1200, 2)
        summary = wallet(user_id)
        assert summary["balance"] == 98
        assert summary["trial"] == 98, "差额必须退回原来的桶"
        assert accounts.usage_state(usage) == "completed"

    def test_full_turn_keeps_the_whole_reservation(self, user_id):
        seed(user_id)
        usage = accounts.reserve_points(user_id, accounts.plus_rule(12), "POST", "/api/wechat-plus/x")
        accounts.settle_usage_with_points(usage, 200, 5000, 12)
        assert wallet(user_id)["balance"] == 88

    def test_settlement_is_idempotent(self, user_id):
        seed(user_id)
        usage = accounts.reserve_points(user_id, accounts.plus_rule(12), "POST", "/api/wechat-plus/x")
        accounts.settle_usage_with_points(usage, 200, 1000, 6)
        accounts.settle_usage_with_points(usage, 200, 1000, 6)  # 重复调用不该再退
        assert wallet(user_id)["balance"] == 94

    def test_refund_after_full_settlement_does_nothing(self, user_id):
        seed(user_id)
        usage = accounts.reserve_points(user_id, accounts.plus_rule(12), "POST", "/api/wechat-plus/x")
        accounts.settle_usage_with_points(usage, 200, 1000, 12)
        accounts.refund_usage(usage, 200, 1000)
        assert wallet(user_id)["balance"] == 88, "已结算的单子不该再退"

    def test_buckets_are_restored_in_the_right_order(self, user_id):
        seed(user_id)
        with accounts._connect() as conn:
            # 混合扣费：3 试用 + 2 赠送 + 7 付费
            conn.execute(
                "UPDATE wallets SET balance=12, trial_balance=3, bonus_balance=2, paid_balance=7 WHERE user_id=?",
                (user_id,),
            )
        usage = accounts.reserve_points(user_id, accounts.plus_rule(12), "POST", "/api/wechat-plus/x")
        assert wallet(user_id)["balance"] == 0
        accounts.settle_usage_with_points(usage, 200, 1000, 2)  # 退 10
        summary = wallet(user_id)
        assert summary["balance"] == 10
        assert summary["trial"] + summary["bonus"] + summary["paid"] == 10


class TestApiReservation:
    def test_message_reserves_the_ceiling_before_doing_any_work(self, client, user_id):
        seed(user_id)
        created = client.post("/api/wechat-plus/sessions", json={"title": "计费"})
        assert created.status_code == 201
        session = created.json()["session"]
        sent = client.post(
            f"/api/wechat-plus/sessions/{session['id']}/messages",
            json={"message": "我想写一篇关于 AI 的文章", "version": session["version"],
                  "idempotency_key": "billing-test-key-1"},
        )
        assert sent.status_code == 202, sent.text[:300]
        assert sent.json()["points"]["reserved"] == 12
        assert wallet(user_id)["balance"] == 88

    def test_poor_wallet_is_rejected_before_the_turn_is_queued(self, client, user_id):
        seed(user_id, points=0)
        created = client.post("/api/wechat-plus/sessions", json={"title": "没积分"})
        session = created.json()["session"]
        sent = client.post(
            f"/api/wechat-plus/sessions/{session['id']}/messages",
            json={"message": "写一篇", "version": session["version"],
                  "idempotency_key": "billing-test-key-2"},
        )
        assert sent.status_code == 402, sent.text[:200]
        assert "积分不足" in sent.json()["detail"]

    def test_pricing_copy_reaches_the_client(self, client, user_id):
        listed = client.get("/api/wechat-plus/sessions")
        assert listed.status_code == 200
        body = listed.json()
        assert body["pricing_points"]["write"] == 12
        assert "内测期间暂不扣" not in body["pricing"]

    def test_cancel_refunds_the_reservation(self, client, user_id):
        seed(user_id)
        created = client.post("/api/wechat-plus/sessions", json={"title": "取消退款"})
        session = created.json()["session"]
        sent = client.post(
            f"/api/wechat-plus/sessions/{session['id']}/messages",
            json={"message": "写一篇", "version": session["version"],
                  "idempotency_key": "billing-test-key-3"},
        )
        assert sent.status_code == 202
        turn_id = sent.json()["turn"]["id"]
        assert wallet(user_id)["balance"] == 88

        cancelled = client.post(f"/api/wechat-plus/sessions/{session['id']}/cancel/{turn_id}")
        assert cancelled.status_code == 200
        assert wallet(user_id)["balance"] == 100, "取消必须全额退分"
