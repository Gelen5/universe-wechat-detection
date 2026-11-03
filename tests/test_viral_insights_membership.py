"""爆款情报会员：试用、权益、接口保护、支付发放/退款、与积分充值隔离。"""
import base64
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from urllib.parse import urlencode

import pytest
import rsa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from tests import support  # noqa: F401
from server import accounts, alipay_pay, database, viral_insights_membership as vim
from server.main import app
from server.models import ImageBoardItem, ImageBoardSyncRun, LowfansArticle


# ---------------------------------------------------------------- fixtures
@pytest.fixture
def paywall(monkeypatch):
    monkeypatch.setenv("VIRAL_INSIGHTS_PAYWALL_ENABLED", "1")
    yield


@pytest.fixture
def clock(monkeypatch):
    """Controllable 'database server' clock."""
    state = {"now": datetime(2026, 11, 4, 0, 0, 0, tzinfo=timezone.utc)}
    monkeypatch.setattr(vim, "_db_now", lambda connection: state["now"])
    return state


def _client_for_new_user():
    client = TestClient(app)
    email = uuid.uuid4().hex + "@example.test"
    response = client.post("/api/auth/register", json={"email": email, "password": "testing-pass-123",
                                                      "display_name": "vi"})
    assert response.status_code < 400, response.text
    user_id = client.get("/api/auth/me").json()["user"]["id"]
    return client, user_id


_SEEDED = {"done": False}


def _seed():
    if _SEEDED["done"]:
        return
    with database.session_scope() as session:
        for i in range(1, 13):
            session.add(LowfansArticle(
                stat_date="2026-11-02", range_type="7d", rank_no=i, art_id=f"vi-art-{i}",
                wx_biz="biz", wx_name=f"号{i}", wx_type="科技", title=f"测试低粉爆文标题第{i}篇很长很长很长的标题",
                art_url=f"https://mp.weixin.qq.com/s/secret-{i}", read_num=50000 + i,
                account_read_base=1000, boost_ratio=50.0, burst_score=9.0, stats_range="90d"))
            session.add(ImageBoardItem(
                stat_date="2026-11-02", sn=f"vi-sn-{i}", wx_biz="biz", wx_type="生活", content_type="book",
                title=f"测试爆图{i}", content="正文", art_url=f"https://mp.weixin.qq.com/s/img-{i}",
                pic_url=f"https://mmbiz.qpic.cn/secret-{i}.jpg", read_num=9000 + i, image_num=3, word_num=20,
                video_num=0))
        session.add(ImageBoardSyncRun(finished_at=datetime.now(timezone.utc), stat_date="2026-11-02",
                                      source="test", status="ok", inserted=12))
    _SEEDED["done"] = True


def _membership_order(user_id: str, package_id: str = "month", status: str = "PENDING_PAYMENT") -> str:
    package = next(p for p in vim.PACKAGES if p["id"] == package_id)
    oid = "VI" + uuid.uuid4().hex[:20].upper()
    with database.ENGINE.begin() as connection:
        connection.execute(alipay_pay.alipay_orders.insert().values(
            out_trade_no=oid, app_id="test-app", subject="会员", total_amount=package["price"],
            status="CREATED", refunded_amount="0.00", created_at=alipay_pay._now(), updated_at=alipay_pay._now()))
        connection.execute(vim.orders.insert().values(
            out_trade_no=oid, user_id=user_id, package_id=package_id, amount=package["price"],
            days=package["days"], status=status, created_at=datetime.now(timezone.utc).isoformat()))
    return oid


def _signed_notify(oid: str, amount: str, **extra):
    pub, priv = rsa.newkeys(1024)
    pem = RSAPublicNumbers(pub.e, pub.n).public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    public = "".join(pem.decode().splitlines()[1:-1])
    cfg = {"app_id": "test-app", "seller_id": "test-seller", "gateway": alipay_pay.PRODUCTION_GATEWAY,
           "alipay_public_key": public}
    params = {"app_id": "test-app", "seller_id": "test-seller", "out_trade_no": oid, "trade_no": "T" + oid,
              "trade_status": "TRADE_SUCCESS", "total_amount": amount, "buyer_pay_amount": amount,
              "gmt_payment": accounts.utc_now(), "notify_id": uuid.uuid4().hex, "sign_type": "RSA2", **extra}
    params["sign"] = base64.b64encode(rsa.sign(alipay_pay._sign_content(params).encode(), priv, "SHA-256")).decode()
    return cfg, params


def _post_notify(client, params):
    return client.post("/api/pay/alipay/notify", content=urlencode(params),
                       headers={"Content-Type": "application/x-www-form-urlencoded"}).text


# ---------------------------------------------------------------- 试用
def test_trial_boundary_is_exactly_24_hours(paywall, clock):
    client, uid = _client_for_new_user()
    start = clock["now"]
    body = client.post("/api/viral-insights/trial/activate").json()
    assert body["activated"] is True and body["status"] == "trial_active"
    clock["now"] = start + timedelta(hours=24) - timedelta(seconds=1)
    assert vim.has_access(uid) is True
    clock["now"] = start + timedelta(hours=24)
    assert vim.has_access(uid) is False
    assert client.get("/api/viral-insights/membership").json()["status"] == "trial_expired"


def test_existing_user_gets_trial_once_and_repeat_does_not_reset(paywall, clock):
    old = accounts.create_user(uuid.uuid4().hex + "@example.test", "testing-pass-123", "old")
    with accounts._connect() as connection:
        connection.execute("UPDATE users SET created_at=? WHERE id=?", ("2025-01-01T00:00:00+00:00", old["id"]))
    client = TestClient(app)
    assert client.post("/api/auth/login", json={"email": old["email"], "password": "testing-pass-123"}).status_code < 400
    first = client.post("/api/viral-insights/trial/activate").json()
    clock["now"] += timedelta(hours=30)
    second = client.post("/api/viral-insights/trial/activate").json()
    assert second["activated"] is False
    assert second["trial_expires_at"] == first["trial_expires_at"]
    assert second["status"] == "trial_expired"


def test_purchase_removes_trial_eligibility(paywall, clock):
    client, uid = _client_for_new_user()
    oid = _membership_order(uid, "week")
    vim.apply_paid(oid)
    assert client.post("/api/viral-insights/trial/activate").status_code == 409


# ---------------------------------------------------------------- 访问控制
def test_shared_entitlement_unlocks_both_modules(paywall, clock):
    _seed()
    client, uid = _client_for_new_user()
    assert client.get("/api/lowfans").json()["preview"] is True
    assert client.get("/api/image-board").json()["preview"] is True
    client.post("/api/viral-insights/trial/activate")
    lowfans = client.get("/api/lowfans").json()
    board = client.get("/api/image-board").json()
    assert not lowfans.get("preview") and lowfans["items"][0]["art_url"].startswith("https://")
    assert not board.get("preview") and board["items"][0]["cover_url"]


def test_preview_is_redacted_and_cannot_be_paged(paywall):
    _seed()
    client = TestClient(app)
    for query in ("", "?page=2", "?page_size=100", "?q=标题", "?sort=read&date=2026-11-02"):
        data = client.get("/api/lowfans" + query).json()
        assert data["preview"] is True and len(data["items"]) <= vim.preview_limit()
        assert data["page"] == 1
        for item in data["items"]:
            assert set(item) <= {"rank_no", "wx_type", "title_preview", "publish_date", "stat_date"}
        assert "secret" not in str(data) and "stats" not in data
    board = client.get("/api/image-board?scope=all&q=爆图").json()
    assert board["preview"] is True and len(board["items"]) <= vim.preview_limit()
    assert "mmbiz" not in str(board) and "mp.weixin" not in str(board)


def test_bypass_endpoints_return_membership_403(paywall):
    _seed()
    anon = TestClient(app)
    client, _ = _client_for_new_user()
    for c in (anon, client):
        detail = c.get("/api/lowfans/vi-art-1")
        cover = c.get("/api/image-board/cover?sn=vi-sn-1")
        assert detail.status_code == 403 and detail.json()["detail"]["code"] == "INSIGHTS_MEMBERSHIP_REQUIRED"
        assert cover.status_code == 403 and cover.json()["detail"]["code"] == "INSIGHTS_MEMBERSHIP_REQUIRED"
    for path, payload in (("/api/lowfans/export", {}), ("/api/lowfans/refresh", {"art_id": "vi-art-1"})):
        response = client.post(path, json=payload)
        assert response.status_code == 403  # never 402: no points reserved
        assert response.json()["detail"]["code"] == "INSIGHTS_MEMBERSHIP_REQUIRED"
        assert "X-Points-Charged" not in response.headers


def test_meta_stays_public_and_aggregate_only(paywall):
    _seed()
    data = TestClient(app).get("/api/lowfans/meta").json()
    assert "items" not in data and "secret" not in str(data)


def test_member_export_still_charges_points_and_needs_access(paywall, clock):
    _seed()
    client, uid = _client_for_new_user()
    client.post("/api/viral-insights/trial/activate")
    response = client.post("/api/lowfans/export", json={})
    assert response.status_code == 402  # entitled, but export points remain separate


def test_member_responses_are_not_publicly_cached(paywall, clock):
    _seed()
    client, _ = _client_for_new_user()
    client.post("/api/viral-insights/trial/activate")
    assert "no-store" in client.get("/api/lowfans").headers["Cache-Control"]
    assert "public" not in client.get("/api/image-board").headers["Cache-Control"]


def test_paywall_disabled_keeps_legacy_behaviour(monkeypatch):
    monkeypatch.setenv("VIRAL_INSIGHTS_PAYWALL_ENABLED", "0")
    _seed()
    anon = TestClient(app)
    data = anon.get("/api/lowfans").json()
    assert not data.get("preview") and data["items"][0]["art_url"]
    assert anon.get("/api/lowfans/vi-art-1").status_code == 200
    assert not anon.get("/api/image-board").json().get("preview")
    client, _ = _client_for_new_user()
    assert client.post("/api/viral-insights/orders", json={"package_id": "week"}).status_code == 409
    assert client.post("/api/lowfans/export", json={}).status_code == 402  # unchanged points path


# ---------------------------------------------------------------- 订单与支付
def test_order_amount_and_days_are_server_defined(paywall):
    client, uid = _client_for_new_user()
    with patch.object(alipay_pay, "load_payment_config", return_value={"app_id": "test-app"}), \
         patch.object(alipay_pay, "_page_pay_form", return_value="<form></form>"):
        body = client.post("/api/viral-insights/orders",
                           json={"package_id": "week", "total_amount": "0.01", "days": 999}).json()
    assert body["total_amount"] == "9.90" and body["package"]["days"] == 7
    order = client.get("/api/viral-insights/orders/" + body["out_trade_no"]).json()
    assert order["amount"] == "9.90" and order["days"] == 7
    other, _ = _client_for_new_user()
    assert other.get("/api/viral-insights/orders/" + body["out_trade_no"]).status_code == 404
    assert client.post("/api/viral-insights/orders", json={"package_id": "lifetime"}).status_code == 404


def test_forged_and_replayed_notifications(paywall, clock):
    client, uid = _client_for_new_user()
    oid = _membership_order(uid, "month")
    cfg, params = _signed_notify(oid, "29.90")
    http = TestClient(app)
    with patch.object(alipay_pay, "load_payment_config", return_value=cfg):
        assert _post_notify(http, dict(params, total_amount="0.01")) == "fail"
        assert _post_notify(http, dict(params, sign="AAAA" + params["sign"][4:])) == "fail"
        assert vim.has_access(uid) is False
        for _ in range(3):
            assert _post_notify(http, params) == "success"
    state = client.get("/api/viral-insights/membership").json()
    assert state["status"] == "member_active"
    assert state["membership_expires_at"] == (clock["now"] + timedelta(days=30)).isoformat()


def test_active_query_compensates_missing_notification(paywall, clock):
    _, uid = _client_for_new_user()
    oid = _membership_order(uid, "week")
    # Existing reconciler only scans orders older than one minute; backdate this one.
    with database.ENGINE.begin() as connection:
        connection.execute(update(alipay_pay.alipay_orders).where(alipay_pay.alipay_orders.c.out_trade_no == oid)
                           .values(created_at="2000-01-01 00:00:00"))
    with patch.object(alipay_pay, "_trade_query",
                      return_value={"code": "10000", "trade_status": "TRADE_SUCCESS", "trade_no": "Q" + oid}):
        alipay_pay.reconcile_pending_orders(older_than_minutes=0, limit=500, trigger="test")
        alipay_pay.reconcile_pending_orders(older_than_minutes=0, limit=500, trigger="test")
    assert vim.has_access(uid) is True
    with database.ENGINE.connect() as connection:
        assert connection.execute(select(vim.orders.c.status).where(vim.orders.c.out_trade_no == oid)).scalar() == "PAID"


def test_purchase_during_trial_and_renewal_extend_sequentially(paywall, clock):
    client, uid = _client_for_new_user()
    start = clock["now"]
    client.post("/api/viral-insights/trial/activate")
    clock["now"] = start + timedelta(hours=2)
    first = _membership_order(uid, "week")
    vim.apply_paid(first)
    clock["now"] = start + timedelta(hours=3)
    second = _membership_order(uid, "month")
    vim.apply_paid(second)
    vim.apply_paid(second)  # idempotent
    expected = start + timedelta(hours=24) + timedelta(days=7) + timedelta(days=30)
    assert client.get("/api/viral-insights/membership").json()["membership_expires_at"] == expected.isoformat()


def test_concurrent_payment_grants_do_not_overlap(paywall, clock):
    _, uid = _client_for_new_user()
    orders = [_membership_order(uid, "week") for _ in range(4)]
    threads = [threading.Thread(target=vim.apply_paid, args=(oid,)) for oid in orders]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    state = vim._state(uid)
    assert state["membership_expires_at"] == (clock["now"] + timedelta(days=28)).isoformat()


def test_refund_revokes_and_recomputes_once(paywall, clock):
    _, uid = _client_for_new_user()
    first, second = _membership_order(uid, "week"), _membership_order(uid, "month")
    vim.apply_paid(first)
    clock["now"] += timedelta(seconds=1)
    vim.apply_paid(second)
    assert vim.apply_refund(first) is True
    assert vim.apply_refund(first) is False  # repeat refund is a no-op
    state = vim._state(uid)
    # second order now begins at its own payment time instead of after the refunded week
    assert state["membership_expires_at"] == (clock["now"] + timedelta(days=30)).isoformat()
    vim.apply_refund(second)
    assert vim.has_access(uid) is False
    assert vim._state(uid)["status"] == "member_expired"


def test_refund_notification_revokes_membership(paywall, clock):
    _, uid = _client_for_new_user()
    oid = _membership_order(uid, "week")
    vim.apply_paid(oid)
    cfg, params = _signed_notify(oid, "9.90", trade_status="TRADE_CLOSED", gmt_refund=accounts.utc_now(),
                                 refund_fee="9.90", out_biz_no="RF1")
    with patch.object(alipay_pay, "load_payment_config", return_value=cfg):
        assert _post_notify(TestClient(app), params) == "success"
        assert _post_notify(TestClient(app), params) == "success"
    assert vim.has_access(uid) is False


def test_membership_payment_never_credits_points_or_referral(paywall, clock):
    from server import referrals, referral_recharge as rr
    inviter = accounts.create_user(uuid.uuid4().hex + "@example.test", "testing-pass-123", "a")["id"]
    client, invitee = _client_for_new_user()
    referrals.bind_signup(invitee, referrals.ensure_code(inviter), "shared")
    rr.configure("2020-01-01T00:00:00+00:00", True)
    before_a, before_b = accounts.wallet_summary(inviter), accounts.wallet_summary(invitee)
    oid = _membership_order(invitee, "year")
    cfg, params = _signed_notify(oid, "199.00")
    with patch.object(alipay_pay, "load_payment_config", return_value=cfg):
        assert _post_notify(TestClient(app), params) == "success"
    assert vim.has_access(invitee) is True
    assert accounts.wallet_summary(inviter) == before_a
    assert accounts.wallet_summary(invitee)["balance"] == before_b["balance"]
    with accounts._connect() as connection:
        assert connection.execute("SELECT COUNT(*) AS n FROM alipay_recharges WHERE out_trade_no=?", (oid,)).fetchone()["n"] == 0


def test_points_recharge_still_credits_with_paywall_on(paywall):
    _, uid = _client_for_new_user()
    oid = uuid.uuid4().hex
    with accounts._connect() as connection:
        connection.execute("INSERT INTO alipay_orders(out_trade_no,app_id,subject,total_amount,status,refunded_amount,created_at,updated_at) VALUES(?,'test-app','t','19.90','CREATED','0.00',?,?)", (oid, accounts.utc_now(), accounts.utc_now()))
        connection.execute("INSERT INTO alipay_recharges(out_trade_no,user_id,package_id,credits,amount,status,created_at) VALUES(?,?,'starter',199,'19.90','PENDING',?)", (oid, uid, accounts.utc_now()))
    cfg, params = _signed_notify(oid, "19.90")
    with patch.object(alipay_pay, "load_payment_config", return_value=cfg):
        assert _post_notify(TestClient(app), params) == "success"
    assert accounts.wallet_summary(uid)["paid"] == 199
    assert vim.has_access(uid) is False  # points do not grant membership


# ---------------------------------------------------------------- 图榜同步
def test_image_board_scheduled_sync_disabled_by_default(monkeypatch):
    from server import image_board
    monkeypatch.delenv("IMAGE_BOARD_SYNC_ENABLED", raising=False)
    with patch.object(image_board, "sync") as sync:
        assert image_board.scheduled_sync()["status"] == "disabled"
        sync.assert_not_called()


def test_reconciliation_repairs_paid_membership_without_grant(paywall, clock):
    client, uid = _client_for_new_user()
    oid = _membership_order(uid)
    with database.ENGINE.begin() as conn:
        conn.execute(update(alipay_pay.alipay_orders).where(
            alipay_pay.alipay_orders.c.out_trade_no == oid).values(status='PAID'))
    assert not vim._state(uid)['active']
    with patch.object(alipay_pay, '_trade_query', return_value={'code': '40004'}):
        alipay_pay.reconcile_pending_orders()
    assert vim._state(uid)['active']
    assert client.get('/api/viral-insights/membership').json()['status'] == 'member_active'


def test_payment_query_does_not_mark_gateway_paid_before_grant(paywall, clock):
    _, uid = _client_for_new_user()
    oid = _membership_order(uid)
    order = alipay_pay._find_order(oid)
    with patch.object(alipay_pay, '_trade_query', return_value={'code': '10000', 'trade_status': 'TRADE_SUCCESS'}), \
         patch.object(vim, 'apply_paid', side_effect=RuntimeError('interrupted')):
        with pytest.raises(RuntimeError):
            alipay_pay._sync_from_query(order)
    assert alipay_pay._find_order(oid)['status'] == 'CREATED'


def test_confirmed_refund_reconciliation_revokes_membership(paywall, clock):
    from server import referral_recharge
    client, uid = _client_for_new_user()
    oid = _membership_order(uid, 'week')
    vim.apply_paid(oid)
    referral_recharge.reserve_refund(oid, 'recover-refund', 990)
    referral_recharge.confirm_refund(oid, 'recover-refund')
    referral_recharge.confirm_refund(oid, 'recover-refund')
    assert not vim._state(uid)['active']
    assert client.get('/api/viral-insights/membership').json()['status'] == 'member_expired'


def test_image_board_stale_snapshot_is_flagged(monkeypatch):
    from server import image_board
    _seed()
    monkeypatch.setenv("VIRAL_INSIGHTS_PAYWALL_ENABLED", "0")
    monkeypatch.setenv("IMAGE_BOARD_STALE_HOURS", "6")
    with database.session_scope() as session:
        session.execute(update(ImageBoardSyncRun).values(
            finished_at=datetime.now(timezone.utc) - timedelta(days=5)))
    data = TestClient(app).get("/api/image-board").json()
    assert data["degraded"] is True and data["freshness"]["stale"] is True
    assert "未更新" in data["reason"]
    with patch.object(image_board.requests, "post", side_effect=image_board.requests.ConnectionError):
        monkeypatch.setenv("IMAGE_BOARD_SYNC_ENABLED", "1")
        monkeypatch.setenv("WXRANK_API_KEY", "k")
        result = image_board.scheduled_sync()
    assert result["status"] in {"failed", "cached"}
    assert TestClient(app).get("/api/image-board").json()["items"]  # old snapshot retained
