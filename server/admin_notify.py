"""管理员邮件提醒：新心愿待审核、用户举报。

只走邮件（Resend）。线上已配 RESEND_API_KEY / RESEND_FROM（与注册验证码同一套）。
所有发送都是 best-effort：在后台线程里跑，超时 8 秒，失败只写日志——绝不能让
「发不出邮件」把用户的心愿提交卡住或报错。
"""
from __future__ import annotations

import logging
import os
import threading

import requests

from . import accounts

RESEND_URL = 'https://api.resend.com/emails'
SITE = os.getenv('PUBLIC_SITE_URL', 'https://yuzoudiyigongzuotai.cn').rstrip('/')


def admin_email() -> str:
    """收件人：优先 ADMIN_NOTIFY_EMAIL，否则用站长账号邮箱。"""
    return (os.getenv('ADMIN_NOTIFY_EMAIL') or accounts.OWNER_EMAIL or '').strip()


def _send(subject: str, html: str) -> None:
    key = os.getenv('RESEND_API_KEY', '').strip()
    sender = os.getenv('RESEND_FROM', '').strip()
    to = admin_email()
    if not (key and sender and to):
        logging.getLogger(__name__).info('admin_notify skipped: resend not configured')
        return
    response = requests.post(
        RESEND_URL,
        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
        json={'from': sender, 'to': [to], 'subject': subject, 'html': html},
        timeout=8,
    )
    if response.status_code >= 400:
        logging.getLogger(__name__).warning(
            'admin_notify failed: %s %s', response.status_code, (response.text or '')[:200])


def _spawn(subject: str, html: str) -> None:
    def run() -> None:
        try:
            _send(subject, html)
        except Exception:  # noqa: BLE001 - 提醒失败不能影响业务
            logging.getLogger(__name__).exception('admin_notify crashed')

    threading.Thread(target=run, daemon=True, name='admin-notify').start()


def _seen(key: str, ttl: int = 86400) -> bool:
    """同一条心愿只提醒一次（Redis 不可用时按「没发过」处理）。"""
    try:
        import redis

        client = redis.Redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379/0'),
                                      socket_connect_timeout=2, socket_timeout=2)
        return bool(client.set('admin-notify:' + key, '1', nx=True, ex=ttl))
    except Exception:  # noqa: BLE001
        return True


def _wrap(title: str, rows: list[tuple[str, str]], cta: str) -> str:
    body = ''.join(
        f'<tr><td style="padding:6px 16px 6px 0;color:#6b7a72;white-space:nowrap">{label}</td>'
        f'<td style="padding:6px 0;color:#1d3b30">{value}</td></tr>'
        for label, value in rows)
    return f'''<div style="font:15px/1.7 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#1d3b30;max-width:560px">
  <p style="margin:0 0 4px;color:#2f6f4f;font-size:13px;letter-spacing:.08em">宇宙第一工作台 · 心愿广场</p>
  <h2 style="margin:0 0 16px;font-size:20px">{title}</h2>
  <table style="border-collapse:collapse;margin:0 0 20px">{body}</table>
  <a href="{SITE}{cta}" style="display:inline-block;background:#2f6f4f;color:#fff;text-decoration:none;
     padding:11px 22px;border-radius:10px;font-weight:600">打开审核页 →</a>
  <p style="margin:22px 0 0;color:#8a998f;font-size:12px">这封邮件由系统自动发送；处理完心愿后不会再提醒同一条。</p>
</div>'''


def wish_submitted(wish: dict, publisher: str = '') -> None:
    wish_id = str(wish.get('id') or '')
    if not wish_id or not _seen('wish:' + wish_id):
        return
    title = str(wish.get('title') or '未命名心愿')
    rows = [
        ('心愿', title),
        ('分类', str(wish.get('category') or '未分类')),
        ('发布者', publisher or '未知'),
        ('希望实现', f"{wish.get('target_kind') or ''} · {wish.get('target_text') or ''}".strip(' ·')),
    ]
    if wish.get('target_amount'):
        rows.append(('所需金额', f"¥{wish['target_amount']}"))
    _spawn(f'【心愿广场】有新心愿待审核：{title}', _wrap('有新的心愿等待审核', rows, '/wish-review'))


def wish_reported(wish: dict, reason: str, reporter: str = '') -> None:
    wish_id = str(wish.get('id') or '')
    if not wish_id or not _seen(f'report:{wish_id}:{abs(hash(reason)) % 10**8}'):
        return
    title = str(wish.get('title') or '未命名心愿')
    rows = [
        ('心愿', title),
        ('分类', str(wish.get('category') or '未分类')),
        ('举报人', reporter or '匿名'),
        ('原因', reason[:300]),
    ]
    _spawn(f'【心愿广场】有用户举报：{title}', _wrap('有用户举报了这条心愿', rows, '/wish-review'))


def pending_counts() -> dict[str, int]:
    """待审核心愿数 + 已发布心愿上的举报数，给站内红点用。"""
    from sqlalchemy import func, select

    from . import database
    from .wish_square import wish_reports, wishes

    with database.ENGINE.connect() as connection:
        pending = connection.execute(
            select(func.count()).select_from(wishes).where(wishes.c.status == 'pending')).scalar() or 0
        reports = connection.execute(
            select(func.count()).select_from(wish_reports)
            .join(wishes, wishes.c.id == wish_reports.c.wish_id)
            .where(wishes.c.status == 'published')).scalar() or 0
    return {'pending': int(pending), 'reports': int(reports)}
