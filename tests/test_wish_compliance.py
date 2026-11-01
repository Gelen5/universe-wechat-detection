"""心愿广场的合规护栏：回报类措辞拦截 + 金额上限 + 审核端二次拦截。"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tests.support  # noqa: F401,E402

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from server import accounts, database, wish_square  # noqa: E402
from server.main import app  # noqa: E402

BODY = {
    'title': '想给爷爷换一副助听器',
    'story': '爷爷年纪大了听不清，想给他换一副合适的助听器，让他能听清我们说话。' * 2,
    'category': '生活改善',
    'target_kind': '物品',
    'target_text': '一副助听器',
    'display_name': '小周',
    'target_amount': '2000',
}


@pytest.fixture()
def client():
    with TestClient(app) as c:
        email = 'wish-compliance@example.com'
        password = 'testing-pass-123'
        accounts.init_db()
        try:
            accounts.create_user(email, password, '心愿测试')
        except Exception:  # noqa: BLE001 - 重复跑用例时已存在
            pass
        login = c.post('/api/auth/login', json={'email': email, 'password': password})
        assert login.status_code == 200, login.text[:200]
        yield c


def _user_id(email: str) -> str:
    with accounts._connect() as conn:
        row = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
    return row['id']


class TestRiskyTerms:
    @pytest.mark.parametrize('word', ['投资', '分红', '返利', '保本', '利息', '众筹', '募捐', '慈善'])
    def test_each_blocked_word_is_rejected(self, client, word):
        body = dict(BODY, story=(BODY['story'] + f'这件事我可以给你{word}。'))
        response = client.post('/api/wishes', json=body)
        assert response.status_code == 422, response.text[:200]
        assert word in response.json()['detail']

    def test_clean_wish_is_accepted(self, client):
        response = client.post('/api/wishes', json=BODY)
        assert response.status_code == 201, response.text[:200]
        assert response.json()['risk_terms'] == []


class TestAmountCap:
    def test_over_five_thousand_is_rejected(self, client):
        response = client.post('/api/wishes', json=dict(BODY, target_amount='5000.01'))
        assert response.status_code == 422
        assert '5000' in response.json()['detail']

    def test_exactly_five_thousand_is_allowed(self, client):
        response = client.post('/api/wishes', json=dict(BODY, target_amount='5000'))
        assert response.status_code == 201, response.text[:200]


class TestReviewGuard:
    def test_cannot_publish_a_wish_with_risky_words(self, client, monkeypatch):
        wish_id = uuid.uuid4().hex
        with database.ENGINE.begin() as connection:
            connection.execute(wish_square.wishes.insert().values(
                id=wish_id, user_id=_user_id('wish-compliance@example.com'), title='一起投资分红',
                story='这是一段包含投资和分红字样的历史心愿文本，用于验证审核端拦截。',
                category='生活改善', target_kind='小额资金', target_text='一笔资金',
                status='pending', display_name='小周',
                created_at='2026-01-01T00:00:00+00:00', updated_at='2026-01-01T00:00:00+00:00'))
        monkeypatch.setattr(wish_square.accounts, 'require_admin', lambda request: {'id': 'admin', 'role': 'admin'})
        with pytest.raises(HTTPException) as exc:
            wish_square.review_wish(wish_id, wish_square.ReviewBody(decision='published', note=''), object())
        assert exc.value.status_code == 422
        assert '投资' in exc.value.detail

    def test_rejected_decision_is_always_allowed(self, client, monkeypatch):
        wish_id = uuid.uuid4().hex
        with database.ENGINE.begin() as connection:
            connection.execute(wish_square.wishes.insert().values(
                id=wish_id, user_id=_user_id('wish-compliance@example.com'), title='一起投资分红',
                story='历史数据里的风险措辞，驳回不受限制。',
                category='生活改善', target_kind='小额资金', target_text='一笔资金',
                status='pending', display_name='小周',
                created_at='2026-01-02T00:00:00+00:00', updated_at='2026-01-02T00:00:00+00:00'))
        monkeypatch.setattr(wish_square.accounts, 'require_admin', lambda request: {'id': 'admin', 'role': 'admin'})
        result = wish_square.review_wish(
            wish_id, wish_square.ReviewBody(decision='rejected', note='含投资表述'), object())
        assert result['status'] == 'rejected'
