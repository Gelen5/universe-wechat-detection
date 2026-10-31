"""积分钱包独立页面（/wallet）。

替代原先的弹窗式「我的积分」：整页展示余额、构成、明细筛选与充值入口。
数据在服务端读取一次并内嵌为 JSON，前端只做展示与筛选，不再发额外请求。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from . import accounts

router = APIRouter(tags=["wallet-page"])

_STYLE = """
*{box-sizing:border-box}
body{margin:0;min-height:100vh;background:
radial-gradient(900px 480px at 12% -8%,#e7f4ec 0%,rgba(231,244,236,0) 60%),
radial-gradient(760px 420px at 96% 4%,#eef2ff 0%,rgba(238,242,255,0) 58%),
#f6f5f1;
color:#14251d;font-family:"PingFang SC","Microsoft YaHei",-apple-system,system-ui,sans-serif}
a{color:inherit;text-decoration:none}
.wx-wrap{max-width:880px;margin:0 auto;padding:28px 22px 64px}
.wx-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:26px}
.wx-back{font-size:13px;color:#5b6b62}
.wx-back:hover{color:#0f5132}
.wx-cta{display:inline-flex;align-items:center;gap:8px;padding:9px 16px;border-radius:10px;
background:linear-gradient(158deg,#1B7A58,#0F5132);color:#fff;font-size:13px;font-weight:600;
box-shadow:0 10px 24px -14px rgba(15,81,50,.7)}
.wx-eyebrow{font-size:11px;letter-spacing:.18em;color:#7b8a82;text-transform:uppercase;margin:0 0 6px}
h1{font-size:26px;margin:0 0 4px;font-weight:600;letter-spacing:-.01em}
.wx-account{margin:0;font-size:13px;color:#6b7a72}
.wx-hero{padding:22px 24px;border:1px solid rgba(20,37,29,.08);border-radius:18px;background:#fff;
box-shadow:0 22px 50px -38px rgba(20,37,29,.5)}
.wx-balance{display:flex;align-items:baseline;gap:10px;margin:16px 0 2px}
.wx-balance b{font-family:Georgia,"Songti SC",serif;font-size:44px;line-height:1;letter-spacing:-.02em;color:#0F5132}
.wx-balance span{font-size:14px;color:#5b6b62}
.wx-balance small{font-size:12px;color:#8b9891;margin-left:4px}
.wx-month{display:flex;gap:22px;margin-top:14px;font-size:12.5px;color:#6b7a72}
.wx-month b{color:#14251d;font-weight:600}
.wx-composition{margin-top:14px;padding:18px 24px;border:1px solid rgba(20,37,29,.08);border-radius:16px;background:#fff}
.wx-bar{display:flex;height:10px;border-radius:999px;overflow:hidden;background:#eef1ee}
.wx-bar i{display:block;height:100%}
.wx-bar .b-trial{background:#b9d8c7}
.wx-bar .b-bonus{background:#7fb89c}
.wx-bar .b-paid{background:#1B7A58}
.wx-legend{display:flex;flex-wrap:wrap;gap:18px;list-style:none;margin:12px 0 0;padding:0;font-size:12.5px;color:#5b6b62}
.wx-legend b{color:#14251d;font-weight:600;margin-left:4px}
.wx-dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;vertical-align:middle}
.wx-dot.trial{background:#b9d8c7}.wx-dot.bonus{background:#7fb89c}.wx-dot.paid{background:#1B7A58}
.wx-history{margin-top:26px}
.wx-toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:10px}
.wx-tabs{display:flex;gap:8px;flex-wrap:wrap}
.wx-tabs button{padding:6px 14px;border-radius:999px;border:1px solid rgba(20,37,29,.12);background:transparent;
font-size:12.5px;color:#5b6b62;cursor:pointer}
.wx-tabs button:hover{border-color:rgba(20,37,29,.28);color:#14251d}
.wx-tabs button.active{border-color:#1B7A58;color:#0F5132;background:rgba(27,122,88,.1)}
.wx-refresh{padding:6px 14px;border-radius:999px;border:1px solid rgba(20,37,29,.12);background:#fff;
font-size:12.5px;color:#14251d;cursor:pointer}
.wx-day{margin:22px 0 6px;font-size:12px;letter-spacing:.06em;color:#8b9891}
.wx-row{display:grid;grid-template-columns:36px 1fr auto;align-items:center;gap:14px;
padding:14px 4px;border-bottom:1px solid rgba(20,37,29,.06)}
.wx-row:last-child{border-bottom:0}
.wx-ico{width:36px;height:36px;border-radius:11px;display:grid;place-items:center;font-size:15px;font-weight:700}
.wx-ico.in{background:rgba(27,122,88,.12);color:#0F5132}
.wx-ico.out{background:rgba(180,110,20,.12);color:#a15c00}
.wx-ico.refund{background:rgba(61,91,255,.1);color:#3D5BFF}
.wx-title{font-size:14px;font-weight:500;color:#14251d;margin:0}
.wx-meta{margin:3px 0 0;font-size:12px;color:#8b9891;display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.wx-copy{border:0;background:transparent;padding:0;font-family:ui-monospace,Menlo,Consolas,monospace;
font-size:11.5px;color:#6b7a72;cursor:pointer;text-decoration:underline dotted}
.wx-copy:hover{color:#0F5132}
.wx-amount{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:14px;font-weight:600}
.wx-amount.in{color:#0F5132}.wx-amount.out{color:#a15c00}.wx-amount.refund{color:#3D5BFF}
.wx-empty{padding:38px 0;text-align:center;color:#8b9891;font-size:13px}
.wx-empty a{display:inline-block;margin-top:12px;padding:8px 16px;border-radius:10px;background:#0F5132;color:#fff;font-size:13px}
.wx-admin{margin-top:30px;padding:20px 22px;border:1px dashed rgba(20,37,29,.18);border-radius:16px;background:#fffdf8}
.wx-admin h2{margin:0 0 4px;font-size:14px}
.wx-admin p{margin:0 0 14px;font-size:12px;color:#8b9891}
.wx-admin label{display:block;font-size:12px;color:#5b6b62;margin:10px 0 4px}
.wx-admin input,.wx-admin select{width:100%;padding:9px 11px;border:1px solid rgba(20,37,29,.14);border-radius:9px;font-size:13px;background:#fff}
.wx-admin .row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.wx-admin button{margin-top:14px;padding:10px 16px;border:0;border-radius:10px;background:#0F5132;color:#fff;font-size:13px;font-weight:600;cursor:pointer}
.wx-hint{margin-left:10px;font-size:12px;color:#6b7a72}
@media (max-width:520px){
  .wx-balance b{font-size:36px}
  .wx-row{grid-template-columns:32px 1fr auto;gap:10px}
  .wx-admin .row{grid-template-columns:1fr}
}
"""


def _page(title: str, body: str) -> str:
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{title}</title><style>{_STYLE}</style></head><body>"
        f'<div class="wx-wrap">{body}</div></body></html>'
    )


def _month_totals(items: list[dict[str, Any]]) -> tuple[int, int]:
    """返回（本月消耗绝对值，本月获得）——按北京时间自然月聚合。"""

    now = datetime.now() + timedelta(hours=8)
    month_prefix = now.strftime("%Y-%m")
    used = 0
    gained = 0
    for item in items:
        created = str(item.get("created_at") or "")
        if not created.startswith(month_prefix):
            continue
        amount = int(item.get("amount") or 0)
        if amount < 0:
            used += -amount
        else:
            gained += amount
    return used, gained


def _login_required_page() -> HTMLResponse:
    return HTMLResponse(
        _page(
            "请先登录",
            '<div class="wx-head"><a class="wx-back" href="/">← 返回工作台</a></div>'
            "<h1>请先登录</h1>"
            '<p class="wx-account">积分需要绑定账号，登录后即可查看余额与明细。</p>'
            '<p style="margin-top:20px"><a class="wx-cta" href="/">去登录</a></p>',
        ),
        status_code=401,
        headers={"Cache-Control": "no-store"},
    )


@router.get("/wallet", response_class=HTMLResponse, include_in_schema=False)
def wallet_page(request: Request) -> HTMLResponse:
    try:
        user = accounts.user_from_request(request)
    except Exception:  # noqa: BLE001 - 认证服务异常时给可读页面
        user = None
    if user is None:
        return _login_required_page()

    summary = accounts.wallet_summary(user["id"])
    items = accounts.list_transactions(user["id"], 200)
    used, gained = _month_totals(items)

    balance = int(summary["balance"])
    trial = int(summary["trial"])
    bonus = int(summary["bonus"])
    paid = int(summary["paid"])
    total_bucket = max(1, trial + bonus + paid)
    pct = lambda value: round(value * 100 / total_bucket, 2)  # noqa: E731

    is_owner = (
        str(user.get("role") or "") == "admin"
        and str(user.get("email") or "").lower() == accounts.OWNER_EMAIL
    )

    hero = (
        '<section class="wx-hero">'
        '<p class="wx-eyebrow">POINTS WALLET</p>'
        "<h1>我的积分</h1>"
        f'<p class="wx-account">{user.get("email") or ""}</p>'
        f'<div class="wx-balance"><b>{balance:,}</b><span>积分</span>'
        f"<small>≈ ¥{balance * 0.1:,.2f} · 1 积分 = 0.1 元</small></div>"
        f'<div class="wx-month"><span>本月消耗 <b>{used}</b></span>'
        f"<span>本月获得 <b>{gained}</b></span></div>"
        "</section>"
    )
    composition = (
        '<section class="wx-composition">'
        '<div class="wx-bar">'
        f'<i class="b-trial" style="width:{pct(trial)}%"></i>'
        f'<i class="b-bonus" style="width:{pct(bonus)}%"></i>'
        f'<i class="b-paid" style="width:{pct(paid)}%"></i>'
        "</div>"
        '<ul class="wx-legend">'
        f'<li><span class="wx-dot trial"></span>试用<b>{trial:,}</b></li>'
        f'<li><span class="wx-dot bonus"></span>赠送<b>{bonus:,}</b></li>'
        f'<li><span class="wx-dot paid"></span>付费<b>{paid:,}</b></li>'
        "</ul>"
        "</section>"
    )
    toolbar = (
        '<div class="wx-toolbar">'
        '<div class="wx-tabs" id="wx-tabs" role="group" aria-label="明细筛选">'
        '<button type="button" class="active" data-filter="all">全部</button>'
        '<button type="button" data-filter="recharge">充值</button>'
        '<button type="button" data-filter="refund">退款</button>'
        '<button type="button" data-filter="consume">消费</button>'
        "</div>"
        '<button class="wx-refresh" id="wx-refresh" type="button">刷新</button>'
        "</div>"
    )
    admin_block = (
        '<section class="wx-admin" id="wx-admin" hidden>'
        "<h2>管理员充值</h2>"
        "<p>人工收款与试用赠送分开记录；充值会写入积分账本。</p>"
        '<label for="wx-admin-query">查找用户</label>'
        '<input id="wx-admin-query" type="search" placeholder="邮箱或昵称" autocomplete="off">'
        '<div id="wx-admin-results" class="wx-hint"></div>'
        '<div class="row">'
        '<div><label for="wx-admin-points">积分</label>'
        '<input id="wx-admin-points" type="number" min="1" max="1000000" value="100"></div>'
        '<div><label for="wx-admin-bucket">类型</label>'
        '<select id="wx-admin-bucket"><option value="trial">试用积分</option>'
        '<option value="bonus">赠送积分</option><option value="paid">付费积分</option></select></div>'
        "</div>"
        '<label for="wx-admin-note">备注</label>'
        '<input id="wx-admin-note" type="text" maxlength="300" placeholder="例如：新用户内测赠送">'
        '<button id="wx-admin-submit" type="button">确认充值</button>'
        '<span class="wx-hint" id="wx-admin-hint"></span>'
        "</section>"
    ) if is_owner else ""

    payload = {
        "items": items,
        "owner": is_owner,
    }
    data_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")

    body = (
        '<header class="wx-head">'
        '<a class="wx-back" href="/">← 返回工作台</a>'
        '<a class="wx-cta" href="/pricing">充值积分</a>'
        "</header>"
        + hero
        + composition
        + f'<section class="wx-history">{toolbar}<div id="wx-list"></div></section>'
        + admin_block
        + f'<script type="application/json" id="wx-data">{data_json}</script>'
        + _SCRIPT
    )
    return HTMLResponse(_page("我的积分", body), headers={"Cache-Control": "no-store"})


_SCRIPT = """
<script>
(() => {
  const data = JSON.parse(document.getElementById('wx-data').textContent || '{}');
  const items = Array.isArray(data.items) ? data.items : [];
  let filter = sessionStorage.getItem('wx-filter') || 'all';

  const kindOf = (item) => {
    const kind = String(item.kind || '').toLowerCase();
    if (kind === 'recharge' || kind === 'refund' || kind === 'consume') return kind;
    return Number(item.amount) > 0 ? 'recharge' : 'consume';
  };
  const orderOf = (item) => {
    const match = String(item.request_id || '').match(/^alipay(?:-refund)?:([^:]+)/);
    return match ? match[1] : '';
  };
  const dayOnly = (iso) => String(iso || '').slice(0, 10);
  const dayLabel = (day) => {
    const today = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    const localToday = `${today.getFullYear()}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}`;
    const yesterday = new Date(today.getTime() - 86400000);
    const localYesterday = `${yesterday.getFullYear()}-${pad(yesterday.getMonth() + 1)}-${pad(yesterday.getDate())}`;
    if (day === localToday) return '今天';
    if (day === localYesterday) return '昨天';
    return day;
  };
  const esc = (value) => String(value == null ? '' : value).replace(/[&<>"']/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const timeOf = (iso) => {
    const match = String(iso || '').match(/[T ](\\d{2}:\\d{2})/);
    return match ? match[1] : '';
  };

  function render() {
    const list = document.getElementById('wx-list');
    const shown = filter === 'all' ? items : items.filter((item) => kindOf(item) === filter);
    if (!shown.length) {
      list.innerHTML = items.length
        ? '<p class="wx-empty">这个分类还没有记录</p>'
        : '<p class="wx-empty">还没有积分记录<br><a href="/pricing">去充值积分</a></p>';
      return;
    }
    let html = '';
    let currentDay = '';
    for (const item of shown) {
      const day = dayOnly(item.created_at);
      if (day !== currentDay) {
        currentDay = day;
        html += `<div class="wx-day">${esc(dayLabel(day))}</div>`;
      }
      const kind = kindOf(item);
      const amount = Number(item.amount) || 0;
      const iconClass = kind === 'refund' ? 'refund' : amount > 0 ? 'in' : 'out';
      const amountClass = kind === 'refund' ? 'refund' : amount > 0 ? 'in' : 'out';
      const sign = amount > 0 ? '+' : '';
      const order = orderOf(item);
      const title = item.feature || item.note || (amount > 0 ? '积分入账' : '功能消费');
      const meta = [timeOf(item.created_at), kind === 'refund' ? '退款冲正' : kind === 'recharge' ? '充值' : '消费'];
      html += `<article class="wx-row">
        <span class="wx-ico ${iconClass}">${kind === 'refund' ? '↩' : amount > 0 ? '+' : '−'}</span>
        <div>
          <p class="wx-title">${esc(title)}</p>
          <p class="wx-meta"><span>${esc(meta.join(' · '))}</span>${order ? `<button class="wx-copy" data-order="${esc(order)}" type="button">订单 ${esc(order)}</button>` : ''}</p>
        </div>
        <b class="wx-amount ${amountClass}">${sign}${Math.abs(amount).toLocaleString('en-US')}</b>
      </article>`;
    }
    list.innerHTML = html;
  }

  document.getElementById('wx-tabs')?.addEventListener('click', (event) => {
    const button = event.target.closest('button[data-filter]');
    if (!button) return;
    filter = button.dataset.filter;
    sessionStorage.setItem('wx-filter', filter);
    document.querySelectorAll('#wx-tabs button').forEach((node) => node.classList.toggle('active', node === button));
    render();
  });
  document.getElementById('wx-refresh')?.addEventListener('click', () => location.reload());
  document.getElementById('wx-list')?.addEventListener('click', async (event) => {
    const button = event.target.closest('button[data-order]');
    if (!button) return;
    try {
      await navigator.clipboard.writeText(button.dataset.order);
      const original = button.textContent;
      button.textContent = '已复制';
      setTimeout(() => { button.textContent = original; }, 1200);
    } catch (error) { /* 剪贴板不可用时忽略 */ }
  });
  document.querySelectorAll('#wx-tabs button').forEach((node) => {
    node.classList.toggle('active', node.dataset.filter === filter);
  });
  render();

  if (data.owner) {
    const panel = document.getElementById('wx-admin');
    panel.hidden = false;
    const results = document.getElementById('wx-admin-results');
    const hint = document.getElementById('wx-admin-hint');
    let selected = null;
    let timer;
    document.getElementById('wx-admin-query')?.addEventListener('input', (event) => {
      clearTimeout(timer);
      const query = event.target.value.trim();
      if (!query) { results.textContent = ''; return; }
      timer = setTimeout(async () => {
        try {
          const response = await fetch('/api/admin/users?query=' + encodeURIComponent(query), {credentials: 'same-origin'});
          const payload = await response.json();
          const users = payload.users || [];
          results.innerHTML = users.slice(0, 6).map((user) => `<button type="button" data-user="${esc(user.id)}" data-label="${esc(user.email)}">${esc(user.email)} · ${user.balance ?? 0} 积分</button>`).join(' ') || '没有匹配用户';
        } catch (error) { results.textContent = '查询失败'; }
      }, 260);
    });
    results.addEventListener('click', (event) => {
      const button = event.target.closest('button[data-user]');
      if (!button) return;
      selected = button.dataset.user;
      results.textContent = '已选择：' + button.dataset.label;
    });
    document.getElementById('wx-admin-submit')?.addEventListener('click', async () => {
      if (!selected) { hint.textContent = '请先选择用户'; return; }
      const points = Number(document.getElementById('wx-admin-points').value || 0);
      const bucket = document.getElementById('wx-admin-bucket').value;
      const note = document.getElementById('wx-admin-note').value.trim();
      if (!points || !note) { hint.textContent = '积分和备注都要填'; return; }
      hint.textContent = '提交中…';
      try {
        const response = await fetch('/api/admin/recharge', {
          method: 'POST', credentials: 'same-origin',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({user_id: selected, points, bucket, note}),
        });
        const payload = await response.json();
        hint.textContent = response.ok ? `已充值，余额 ${payload.wallet?.balance ?? '-'}` : (payload.detail || '充值失败');
        if (response.ok) setTimeout(() => location.reload(), 900);
      } catch (error) { hint.textContent = '网络异常'; }
    });
  }
})();
</script>
"""
