"""邀请好友独立页面（/invite）。

和 /wallet 一样是服务端渲染：邀请码、名额、受邀名单一次查好内嵌，
前端只负责复制和展示。这样导航栏可以直接指向一个真实 URL，
而不用为了一个弹窗在 SPA 里塞一个假视图。
"""
from __future__ import annotations

import html

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from . import accounts, referrals
from .wallet_page import _page

router = APIRouter(tags=["invite-page"])

_EXTRA_STYLE = """
.wx-invite{margin-top:22px;padding:24px;border:1px solid rgba(20,37,29,.08);border-radius:18px;background:#fff;
box-shadow:0 22px 50px -38px rgba(20,37,29,.5)}
.wx-invite h2{margin:0 0 6px;font-size:17px;font-weight:600}
.wx-invite .wx-lead{margin:0 0 18px;font-size:13px;color:#6b7a72;line-height:1.7}
.wx-code-row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.wx-code{flex:1 1 220px;min-width:0;padding:14px 16px;border:1px dashed #9cc4ae;border-radius:14px;
background:#f7fcf9;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:22px;font-weight:600;
letter-spacing:.24em;text-align:center;color:#0F5132;overflow-wrap:anywhere}
.wx-code-row button{padding:14px 22px;border:0;border-radius:14px;background:linear-gradient(158deg,#1B7A58,#0F5132);
color:#fff;font-size:14px;font-weight:600;cursor:pointer;box-shadow:0 10px 24px -14px rgba(15,81,50,.7)}
.wx-code-row button:hover{filter:brightness(1.05)}
.wx-progress{margin:16px 0 0;font-size:12.5px;color:#6b7a72}
.wx-progress b{color:#0F5132}
.wx-rules{margin:22px 0 0;padding:18px 20px;border-radius:16px;background:#f8faf8;border:1px solid rgba(20,37,29,.06)}
.wx-rules h3{margin:0 0 10px;font-size:13px;font-weight:600;color:#14251d}
.wx-rules ol{margin:0;padding-left:18px;font-size:12.5px;color:#5b6b62;line-height:1.9}
.wx-rules b{color:#0F5132}
.wx-guest{margin-top:26px}
.wx-guest h2{margin:0 0 12px;font-size:15px;font-weight:600}
.wx-guest .wx-row{grid-template-columns:1fr auto}
.wx-badge{padding:4px 10px;border-radius:999px;font-size:11.5px;font-weight:600;white-space:nowrap}
.wx-badge.pending{background:#fdf3e0;color:#8a6416}
.wx-badge.activated{background:#e8f1fd;color:#23558f}
.wx-badge.rewarded{background:#e4f6ec;color:#22684a}
.wx-toast{position:fixed;left:50%;bottom:28px;transform:translateX(-50%) translateY(12px);opacity:0;
padding:10px 18px;border-radius:999px;background:#14251d;color:#fff;font-size:13px;
transition:opacity .18s ease,transform .18s ease;pointer-events:none}
.wx-toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
@media (max-width:520px){.wx-code{font-size:18px;letter-spacing:.18em}.wx-code-row button{width:100%}}
"""

_LABEL = {"pending": "待完成任务", "activated": "奖励发放中", "rewarded": "已发奖励"}


def _esc(value: object) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _invite_body(info: dict, user: dict) -> str:
    code = _esc(info["code"])
    counts = info["counts"]
    caps = info["caps"]
    rewards = info["rewards"]

    if caps["remaining_today"] > 0:
        progress = (f'今天还能邀请 <b>{caps["remaining_today"]}</b> 人'
                    f'（每天上限 {caps["daily"]} 人）')
    else:
        progress = f'今天的名额用完了，明天 0 点刷新（每天上限 <b>{caps["daily"]}</b> 人）'

    rules = (
        '<section class="wx-rules">'
        "<h3>活动规则</h3>"
        "<ol>"
        f'<li>好友用你的邀请码注册，他立刻得 <b>{rewards["signup"]} 积分</b>。</li>'
        f'<li>他跑完第一个任务后，你得 <b>{rewards["activate_inviter"]} 积分</b>，'
        f'他再得 <b>{rewards["activate_invitee"]} 积分</b>。</li>'
        "<li>奖励只发「赠送积分」，不可提现、不可转账，仅用于平台功能。</li>"
        f'<li>每个账号每天最多计入 {caps["daily"]} 人、30 天最多 {caps["monthly"]} 人；'
        "同一 IP 对同一个人 24 小时内最多计 3 次。</li>"
        "</ol>"
        "</section>"
    )

    if info["invitees"]:
        rows = "".join(
            '<article class="wx-row">'
            f'<div><p class="wx-title">{_esc(item["display_name"])}</p>'
            f'<p class="wx-meta"><span>{_esc(item["email"])}</span>'
            f'<span>{_esc(str(item["created_at"])[:10])}</span></p></div>'
            f'<span class="wx-badge {_esc(item["status"])}">'
            f'{_esc(_LABEL.get(item["status"], item["status"]))}</span>'
            "</article>"
            for item in info["invitees"]
        )
        guest = f'<section class="wx-guest"><h2>通过你注册的朋友</h2>{rows}</section>'
    else:
        guest = (
            '<section class="wx-guest"><h2>通过你注册的朋友</h2>'
            '<p class="wx-empty">还没有人用你的邀请码。把上面那条链接发出去试试。</p>'
            "</section>"
        )

    return (
        '<header class="wx-head">'
        '<a class="wx-back" href="/">← 返回工作台</a>'
        '<a class="wx-back" href="/wallet">我的积分 →</a>'
        "</header>"
        '<section class="wx-hero">'
        '<p class="wx-eyebrow">INVITE</p>'
        "<h1>邀请好友</h1>"
        f'<p class="wx-account">{_esc(user.get("email") or "")}</p>'
        f'<div class="wx-month"><span>已邀请 <b>{counts["total"]}</b> 人</span>'
        f'<span>已发奖励 <b>{counts["rewarded"]}</b> 人</span>'
        f'<span>累计获得 <b>{info["earned_points"]}</b> 积分</span></div>'
        "</section>"
        '<section class="wx-invite">'
        "<h2>你的邀请码</h2>"
        f'<p class="wx-lead">好友注册时填这个码，或者直接点你的链接打开工作台，两边都有积分。'
        f'每邀请一个人，最多可得 {rewards["signup"] + rewards["activate_inviter"] + rewards["activate_invitee"]} 积分。</p>'
        '<div class="wx-code-row">'
        f'<code class="wx-code" id="wx-invite-code">{code}</code>'
        '<button type="button" id="wx-invite-copy">复制邀请链接</button>'
        "</div>"
        f'<p class="wx-progress">{progress}</p>'
        "</section>"
        + rules
        + guest
        + '<div class="wx-toast" id="wx-toast" role="status" aria-live="polite"></div>'
        + _SCRIPT
    )


_SCRIPT = """
<script>
(() => {
  const code = document.getElementById('wx-invite-code').textContent.trim();
  const link = `${location.origin}/?ref=${encodeURIComponent(code)}`;
  const toast = document.getElementById('wx-toast');
  const flash = (text) => {
    toast.textContent = text;
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), 1900);
  };
  document.getElementById('wx-invite-copy')?.addEventListener('click', async (event) => {
    const button = event.currentTarget;
    try {
      await navigator.clipboard.writeText(link);
    } catch (error) {
      // 非 HTTPS 或旧浏览器没有 clipboard：退回到能选中的输入框。
      const helper = document.createElement('input');
      helper.value = link;
      document.body.appendChild(helper);
      helper.select();
      try { document.execCommand('copy'); } catch (ignored) { window.prompt('复制这条邀请链接', link); }
      helper.remove();
    }
    flash('邀请链接已复制');
    const original = button.textContent;
    button.textContent = '已复制';
    setTimeout(() => { button.textContent = original; }, 1600);
  });
})();
</script>
"""


def _need_login() -> HTMLResponse:
    return HTMLResponse(
        _page(
            "请先登录",
            '<header class="wx-head"><a class="wx-back" href="/">← 返回工作台</a></header>'
            "<h1>请先登录</h1>"
            '<p class="wx-account">邀请码跟着账号走，登录后才能看到你自己的那一条。</p>'
            '<p style="margin-top:20px"><a class="wx-cta" href="/">去登录</a></p>',
        ),
        status_code=401,
        headers={"Cache-Control": "no-store"},
    )


@router.get("/invite", response_class=HTMLResponse, include_in_schema=False)
def invite_page(request: Request) -> HTMLResponse:
    try:
        user = accounts.user_from_request(request)
    except Exception:  # noqa: BLE001 - 认证服务异常时给可读页面
        user = None
    if user is None:
        return _need_login()

    try:
        info = referrals.summary(user["id"])
    except Exception:  # noqa: BLE001 - 邀请活动异常不能把页面变成 500
        return HTMLResponse(
            _page("邀请好友",
                  f'<style>{_EXTRA_STYLE}</style>'
                  '<header class="wx-head"><a class="wx-back" href="/">← 返回工作台</a></header>'
                  "<h1>邀请好友</h1>"
                  '<p class="wx-account">邀请服务暂时不可用，请稍后再试。</p>'),
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )

    body = _invite_body(info, user)
    return HTMLResponse(
        _page("邀请好友", f"<style>{_EXTRA_STYLE}</style>{body}"),
        headers={"Cache-Control": "no-store"},
    )
