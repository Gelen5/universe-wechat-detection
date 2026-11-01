"""管理员心愿提醒：邮件内容、去重、站内计数。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tests.support  # noqa: F401,E402

from server import accounts, admin_notify  # noqa: E402

WISH = {
    'id': 'wish-1',
    'title': '想去一次大理',
    'category': '旅行',
    'target_kind': '心愿',
    'target_text': '有人陪我去洱海骑行',
    'target_amount': '3000',
}


def test_admin_email_defaults_to_owner(monkeypatch):
    monkeypatch.delenv('ADMIN_NOTIFY_EMAIL', raising=False)
    assert admin_notify.admin_email() == accounts.OWNER_EMAIL


def test_submitted_email_carries_the_essentials(monkeypatch):
    captured = {}
    monkeypatch.setattr(admin_notify, '_seen', lambda *a, **k: True)
    monkeypatch.setattr(admin_notify, '_spawn', lambda subject, html: captured.update(subject=subject, html=html))

    admin_notify.wish_submitted(WISH, '张三')

    assert '想去一次大理' in captured['subject']
    assert '待审核' in captured['subject']
    body = captured['html']
    for piece in ('想去一次大理', '旅行', '张三', '洱海骑行', '3000', '/wish-review'):
        assert piece in body, piece


def test_same_wish_is_only_announced_once(monkeypatch):
    calls = []
    monkeypatch.setattr(admin_notify, '_seen', lambda *a, **k: False)  # 第二次视为已发过
    monkeypatch.setattr(admin_notify, '_spawn', lambda subject, html: calls.append(subject))

    admin_notify.wish_submitted(WISH)

    assert calls == []


def test_report_email_marks_the_reason(monkeypatch):
    captured = {}
    monkeypatch.setattr(admin_notify, '_seen', lambda *a, **k: True)
    monkeypatch.setattr(admin_notify, '_spawn', lambda subject, html: captured.update(subject=subject, html=html))

    admin_notify.wish_reported(WISH, '收款码是别人的', '李四')

    assert '举报' in captured['subject']
    assert '收款码是别人的' in captured['html']
    assert '李四' in captured['html']


def test_pending_counts_returns_two_integers():
    from server import main  # noqa: F401 - 确保建表

    counts = admin_notify.pending_counts()
    assert set(counts) == {'pending', 'reports'}
    assert all(isinstance(value, int) for value in counts.values())
