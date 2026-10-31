"""账单页（/bill）：充值、退款、消费与站长收入汇总。

设计口径：
- 现金维度只认支付宝（``alipay_recharges`` ⟕ ``alipay_orders``），金额为真实支付；
- 积分维度认 ``point_transactions``（消费、退款冲正、非支付宝入账的赠送/试用）；
- 两边不重复：支付宝入账的 recharge 记录只走现金维度，不再从积分账本重复列出；
- 收入汇总（``REVENUE``）只给站长本人看，普通用户不渲染也不返回。
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from . import accounts

router = APIRouter(tags=["bill-page"])

# 支付宝订单状态（见 alipay_pay：CREATED / PENDING_PAYMENT / PAID / CLOSED / REFUNDED / PARTIAL_REFUNDED）
_STATUS_LABEL = {
    "CREATED": ("待支付", "gray"),
    "PENDING_PAYMENT": ("待支付", "gray"),
    "PAID": ("已到账", "ok"),
    "CLOSED": ("已关闭", "gray"),
    "REFUNDED": ("已退款", "blue"),
    "PARTIAL_REFUNDED": ("部分退款", "blue"),
}
_BUCKET_LABEL = {"paid": "付费积分", "bonus": "赠送积分", "trial": "试用积分"}

_STYLE = """
*{box-sizing:border-box}
:root{--ink:#14251d;--ink2:#3d5348;--muted:#71857b;--faint:#98a8a0;--green:#0F5132;--green2:#1B7A58;
--line:rgba(20,37,29,.09);--line2:rgba(20,37,29,.055);--amber:#a15c00;--blue:#3D5BFF;--num:Georgia,"Songti SC",serif}
body{margin:0;min-height:100vh;color:var(--ink);
background:radial-gradient(760px 420px at 8% -10%,#e7f4ec 0%,rgba(231,244,236,0) 62%),
radial-gradient(680px 380px at 98% 2%,#eef2ff 0%,rgba(238,242,255,0) 58%),#f6f5f1;
font-family:"PingFang SC","Microsoft YaHei",-apple-system,system-ui,sans-serif;-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}
button{font-family:inherit}
.bl-wrap{max-width:880px;margin:0 auto;padding:28px 22px 72px}
.bl-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:24px}
.bl-back{font-size:13px;color:#5b6b62}
.bl-back:hover{color:var(--green)}
.bl-cta{display:inline-flex;align-items:center;gap:8px;padding:9px 16px;border-radius:10px;
background:linear-gradient(158deg,var(--green2),var(--green));color:#fff;font-size:13px;font-weight:600;
box-shadow:0 10px 24px -14px rgba(15,81,50,.7);border:0;cursor:pointer}
.bl-cta:hover{filter:brightness(1.06)}
.bl-eyebrow{margin:0 0 6px;font-size:11px;letter-spacing:.18em;color:#7b8a82;text-transform:uppercase}
h1{margin:0 0 4px;font-size:26px;font-weight:600;letter-spacing:-.01em}
.bl-account{margin:0;font-size:13px;color:var(--muted)}
.bl-hero{padding:22px 24px;border:1px solid var(--line);border-radius:18px;background:#fff;
box-shadow:0 22px 50px -38px rgba(20,37,29,.5)}
.bl-bal{display:flex;align-items:baseline;gap:10px}
.bl-bal b{font-family:var(--num);font-size:44px;line-height:1;letter-spacing:-.02em;color:var(--green);
font-variant-numeric:tabular-nums}
.bl-bal span{font-size:14px;color:#5b6b62}
.bl-bal small{font-size:12px;color:var(--faint);margin-left:2px}
.bl-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;margin-top:20px;
border-top:1px solid var(--line2);padding-top:16px;background:var(--line2)}
.bl-stat{background:#fff;padding:2px 0}
.bl-stat p{margin:0}
.bl-stat .k{font-size:12px;color:var(--muted);margin-bottom:6px}
.bl-stat .v{font-family:var(--num);font-size:21px;letter-spacing:-.01em;font-variant-numeric:tabular-nums;
display:flex;align-items:baseline;gap:4px}
.bl-stat .v em{font-family:"PingFang SC",sans-serif;font-style:normal;font-size:12.5px;color:var(--faint)}
.bl-rev{margin-top:14px;padding:20px 24px 18px;border:1px solid var(--line);border-radius:18px;background:#fff;
box-shadow:0 22px 50px -40px rgba(20,37,29,.45)}
.bl-rev-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}
.bl-rev-big{display:flex;align-items:baseline;gap:8px;margin-top:10px}
.bl-rev-big b{font-family:var(--num);font-size:34px;line-height:1;color:var(--green);letter-spacing:-.02em;
font-variant-numeric:tabular-nums}
.bl-rev-big span{font-size:12.5px;color:var(--faint)}
.bl-rev-mini{display:flex;gap:26px;margin-top:16px;padding-top:14px;border-top:1px solid var(--line2);flex-wrap:wrap}
.bl-rev-mini div{font-size:12px;color:var(--muted)}
.bl-rev-mini b{display:block;font-family:var(--num);font-size:15px;color:var(--ink);margin-top:4px;
font-variant-numeric:tabular-nums;font-weight:600}
.bl-rev-mini b.amber{color:var(--amber)}
.bl-bars{margin-top:18px;padding-top:16px;border-top:1px solid var(--line2)}
.bl-bars-t{display:flex;justify-content:space-between;font-size:11.5px;color:var(--faint);margin-bottom:10px;
letter-spacing:.06em}
.bl-bar{display:flex;align-items:center;gap:10px;margin-bottom:7px}
.bl-bar .m{width:46px;font-size:11.5px;color:var(--muted);font-variant-numeric:tabular-nums;flex:none}
.bl-track{flex:1;height:8px;border-radius:999px;background:#eef1ee;overflow:hidden}
.bl-track i{display:block;height:100%;border-radius:999px;background:linear-gradient(90deg,#B9D8C7,#7FB89C)}
.bl-track i.now{background:linear-gradient(90deg,var(--green2),var(--green))}
.bl-bar .a{width:78px;text-align:right;font-size:11.5px;font-family:var(--num);color:var(--ink2);
font-variant-numeric:tabular-nums;flex:none}
.bl-toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin:26px 0 10px}
.bl-tabs{display:flex;gap:6px;flex-wrap:wrap}
.bl-tabs button{padding:6px 14px;border-radius:999px;border:1px solid rgba(20,37,29,.12);background:transparent;
font-size:12.5px;color:#5b6b62;cursor:pointer;transition:.15s}
.bl-tabs button:hover{border-color:rgba(20,37,29,.28);color:var(--ink)}
.bl-tabs button.active{border-color:var(--green2);color:var(--green);background:rgba(27,122,88,.1);font-weight:600}
.bl-tools{display:flex;gap:8px;align-items:center}
.bl-tools select,.bl-tools a{padding:6px 12px;border-radius:9px;border:1px solid rgba(20,37,29,.12);background:#fff;
font-size:12.5px;color:var(--ink);cursor:pointer}
.bl-tools a:hover,.bl-tools select:hover{border-color:rgba(20,37,29,.28)}
.bl-day{margin:22px 0 6px;font-size:12px;letter-spacing:.06em;color:var(--faint);display:flex;align-items:center;gap:8px}
.bl-day::after{content:"";flex:1;height:1px;background:var(--line2)}
.bl-row{display:grid;grid-template-columns:36px 1fr auto;align-items:center;gap:14px;padding:14px 4px;
border-bottom:1px solid var(--line2);cursor:pointer;border-radius:8px;transition:background .15s}
.bl-row:hover,.bl-row.open{background:rgba(27,122,88,.045)}
.bl-row:last-of-type{border-bottom:0}
.bl-ico{width:36px;height:36px;border-radius:11px;display:grid;place-items:center;font-size:14px;font-weight:700}
.bl-ico.in{background:rgba(27,122,88,.12);color:var(--green)}
.bl-ico.out{background:rgba(180,110,20,.12);color:var(--amber)}
.bl-ico.refund{background:rgba(61,91,255,.1);color:var(--blue)}
.bl-ico.wait{background:rgba(20,37,29,.06);color:var(--muted)}
.bl-title{margin:0;font-size:14px;font-weight:500;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.bl-meta{margin:3px 0 0;font-size:12px;color:var(--faint);display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.bl-meta .sep{opacity:.5}
.bl-badge{display:inline-flex;align-items:center;gap:4px;padding:1px 7px;border-radius:999px;font-size:11px;
font-weight:600}
.bl-badge::before{content:"";width:5px;height:5px;border-radius:50%;background:currentColor}
.bl-badge.ok{background:rgba(27,122,88,.1);color:var(--green)}
.bl-badge.amber{background:rgba(161,92,0,.1);color:var(--amber)}
.bl-badge.blue{background:rgba(61,91,255,.1);color:var(--blue)}
.bl-badge.gray{background:rgba(20,37,29,.06);color:var(--muted)}
.bl-amount{font-family:var(--num);font-size:14.5px;font-weight:600;font-variant-numeric:tabular-nums;
text-align:right;white-space:nowrap}
.bl-amount.in{color:var(--green)}.bl-amount.out{color:var(--amber)}.bl-amount.refund{color:var(--blue)}
.bl-amount.wait{color:var(--muted)}
.bl-amount small{display:block;font-family:"PingFang SC",sans-serif;font-size:11px;font-weight:400;
color:var(--faint);margin-top:3px}
.bl-detail{grid-column:1/-1;display:none;margin:2px 0 6px;padding:14px 16px;border-radius:12px;
background:rgba(20,37,29,.026);border:1px solid var(--line2)}
.bl-row.open .bl-detail{display:block}
.bl-dl{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px 20px;margin:0}
.bl-dl dt{font-size:11px;color:var(--faint);margin-bottom:3px}
.bl-dl dd{margin:0;font-size:12.5px;color:var(--ink2);font-variant-numeric:tabular-nums}
.bl-copy{border:0;background:transparent;padding:0;font-family:ui-monospace,Menlo,Consolas,monospace;
font-size:11.5px;color:#6b7a72;cursor:pointer;text-decoration:underline dotted}
.bl-copy:hover{color:var(--green)}
.bl-empty{padding:44px 0;text-align:center;color:var(--faint);font-size:13px}
.bl-empty a{display:inline-block;margin-top:12px;padding:8px 16px;border-radius:10px;background:var(--green);
color:#fff;font-size:13px}
.bl-foot{margin-top:28px;text-align:center;font-size:11.5px;color:var(--faint);line-height:1.9}
:focus-visible{outline:2px solid var(--green2);outline-offset:2px}
@media (max-width:720px){
 .bl-stats{grid-template-columns:repeat(2,1fr);gap:14px 1px}
 .bl-stat:nth-child(3),.bl-stat:nth-child(4){padding-top:8px}
}
@media (max-width:520px){
 .bl-wrap{padding:22px 16px 64px}
 .bl-hero,.bl-rev{padding:18px}
 .bl-bal b{font-size:36px}.bl-rev-big b{font-size:29px}h1{font-size:23px}
 .bl-row{grid-template-columns:32px 1fr auto;gap:10px}
 .bl-tools{width:100%}.bl-tools select,.bl-tools a{flex:1;text-align:center}
}
"""


def _page(title: str, body: str) -> str:
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{title}</title><style>{_STYLE}</style></head><body>"
        f'<div class="bl-wrap">{body}</div></body></html>'
    )


def _beijing_now() -> datetime:
    return datetime.now() + timedelta(hours=8)


def _local_time(value: Any) -> str:
    """把库里存的时间统一成本地（北京）时间文本。

    积分账本用 ``datetime.now(timezone.utc).isoformat()``（带 +00:00），
    支付宝表用北京时间的 ``YYYY-MM-DD HH:MM:SS``；两种都要能正确显示。
    """
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text[:19]
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None)
    return parsed.strftime("%Y-%m-%d %H:%M:%S")


def _money(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _cny(value: Decimal) -> str:
    return f"¥{value:,.2f}"


def _package_names() -> dict[str, str]:
    try:
        from .alipay_pay import _PACKAGES
        return {str(item["id"]): str(item["name"]) for item in _PACKAGES}
    except Exception:  # noqa: BLE001 - 套餐表读不到时退回 id
        return {}


def _login_required_page() -> HTMLResponse:
    return HTMLResponse(
        _page(
            "请先登录",
            '<div class="bl-head"><a class="bl-back" href="/">← 返回工作台</a></div>'
            "<h1>请先登录</h1>"
            '<p class="bl-account">账单需要绑定账号，登录后即可查看充值、消费与退款记录。</p>'
            '<p style="margin-top:20px"><a class="bl-cta" href="/">去登录</a></p>',
        ),
        status_code=401,
        headers={"Cache-Control": "no-store"},
    )


def _cash_rows(user_id: str, package_names: dict[str, str]) -> list[dict[str, Any]]:
    """支付宝充值与退款（现金维度）。"""
    rows: list[dict[str, Any]] = []
    with accounts.DB_LOCK, accounts._connect() as connection:
        try:
            records = connection.execute(
                """SELECT r.out_trade_no, r.package_id, r.credits, r.amount, r.status AS recharge_status,
                          r.credited_at, r.created_at,
                          o.status AS order_status, o.subject, o.trade_no, o.refunded_amount, o.paid_at
                   FROM alipay_recharges r
                   LEFT JOIN alipay_orders o ON o.out_trade_no = r.out_trade_no
                   WHERE r.user_id = ?
                   ORDER BY r.created_at DESC LIMIT 200""",
                (user_id,),
            ).fetchall()
        except Exception:  # noqa: BLE001 - 未启用支付时表可能不存在
            return rows
    for record in records:
        item = dict(record)
        status = str(item.get("order_status") or "").upper()
        recharge_status = str(item.get("recharge_status") or "").upper()
        refunded = _money(item.get("refunded_amount"))
        kind = "refund" if status in ("REFUNDED", "PARTIAL_REFUNDED") or refunded > 0 else "recharge"
        if kind == "recharge" and status in ("CREATED", "PENDING_PAYMENT", ""):
            label, tone = "待支付", "wait"
        elif kind == "refund":
            label, tone = ("已退款" if status == "REFUNDED" else "部分退款"), "blue"
        elif status == "CLOSED":
            label, tone = "已关闭", "gray"
        elif status == "PAID" and recharge_status == "CREDITED":
            label, tone = "已到账", "ok"
        elif status == "PAID":
            label, tone = "已支付待入账", "amber"
        else:
            label, tone = (_STATUS_LABEL.get(status) or ("处理中", "gray"))
        package_id = str(item.get("package_id") or "")
        name = package_names.get(package_id) or package_id or "自定义金额"
        amount = _money(item.get("amount"))
        credits = int(item.get("credits") or 0)
        detail = [
            ["支付方式", "支付宝网页支付"],
            ["商户订单号", str(item.get("out_trade_no") or "")],
            ["下单时间", _local_time(item.get("created_at"))],
        ]
        if item.get("paid_at"):
            detail.append(["支付时间", _local_time(item["paid_at"])])
        if item.get("credited_at"):
            detail.append(["积分到账", _local_time(item["credited_at"])])
        if item.get("trade_no"):
            detail.append(["支付宝交易号", str(item["trade_no"])])
        if refunded > 0:
            detail.append(["已退金额", _cny(refunded)])
        rows.append(
            {
                "kind": kind,
                "at": _local_time(item.get("credited_at") or item.get("paid_at") or item.get("created_at") or ""),
                "title": f"{name}套餐" if kind == "recharge" else f"{name}套餐 · 退款",
                "status": label,
                "tone": tone,
                "amount": _cny(-amount if kind == "recharge" else -refunded),
                "cash": float(amount if kind == "recharge" else refunded),
                "amount_class": "wait" if tone == "wait" else (kind if kind == "refund" else "in"),
                "points": f"{credits:,} 积分" if kind == "recharge" else "积分已冲正",
                "bal": f"套餐 · {int(credits):,} 积分" if kind == "recharge" else "",
                "detail": detail,
                "order": str(item.get("out_trade_no") or ""),
            }
        )
    return rows


def _allocation_label(raw: Any) -> str:
    """把扣费分配 JSON 翻成「付费 20 · 赠送 10」这样的可读文本。"""
    try:
        allocation = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return ""
    if not isinstance(allocation, dict):
        return ""
    parts = [
        f"{_BUCKET_LABEL.get(str(key), str(key)).replace('积分', '')} {int(value):,}"
        for key, value in allocation.items()
        if int(value or 0)
    ]
    return " · ".join(parts)


def _point_rows(user_id: str, package_names: dict[str, str]) -> list[dict[str, Any]]:
    """积分消费、退款冲正与赠送/试用入账（积分维度，排除支付宝充值避免重复）。

    退款行把 ``request_id`` 存成 ``<原请求号>:refund``，所以这里按去掉后缀的
    键在 Python 侧关联 ``usage_records``。不在 SQL 里做 REPLACE：那段 SQL 会经
    ``text()`` 解析，字面量里的冒号在 PostgreSQL 上会被当成绑定参数。
    """
    with accounts.DB_LOCK, accounts._connect() as connection:
        records = connection.execute(
            """SELECT amount, bucket, kind, source, feature, note, request_id,
                      balance_after, allocation_json, created_at
               FROM point_transactions WHERE user_id=?
               ORDER BY created_at DESC LIMIT 300""",
            (user_id,),
        ).fetchall()
        usage: dict[str, dict[str, Any]] = {}
        request_ids = sorted({
            str(dict(row).get("request_id") or "").split(":refund")[0]
            for row in records
        } - {""})
        if request_ids:
            placeholders = ",".join("?" for _ in request_ids)
            for row in connection.execute(
                f"""SELECT request_id, status, http_status FROM usage_records
                    WHERE request_id IN ({placeholders})""",
                tuple(request_ids),
            ).fetchall():
                entry = dict(row)
                usage[str(entry["request_id"])] = entry
    rows: list[dict[str, Any]] = []
    for record in records:
        item = dict(record)
        kind = str(item.get("kind") or "").lower()
        source = str(item.get("source") or "").lower()
        amount = int(item.get("amount") or 0)
        if kind == "recharge" and source == "alipay":
            continue  # 现金维度已列，避免同一笔出现两次
        linked = usage.get(str(item.get("request_id") or "").split(":refund")[0]) or {}
        usage_status = str(linked.get("status") or "").lower()
        if kind == "consume":
            row_kind = "consume"
            title = str(item.get("feature") or item.get("note") or "功能消费")
            title = title.replace("预扣 ", "").strip() or "功能消费"
            if usage_status == "refunded":
                label, tone = "已退回", "blue"
            elif usage_status == "completed":
                label, tone = "已结算", "ok"
            elif usage_status == "reserved":
                label, tone = "扣费中", "amber"
            else:
                label, tone = "已结算", "gray"
        elif kind == "refund":
            row_kind, title, tone, label = "refund", f"{item.get('feature') or '订单'} · 退回积分", "blue", "已退回"
        else:
            row_kind = "grant"
            title = str(item.get("note") or item.get("feature") or "积分入账")
            tone, label = "ok", "已入账"
        bucket_raw = str(item.get("bucket") or "")
        allocation = _allocation_label(item.get("allocation_json"))
        if bucket_raw == "mixed":
            bucket = allocation or "多个积分桶"
        else:
            bucket = _BUCKET_LABEL.get(bucket_raw, bucket_raw)
        detail = [
            ["变动", f"{amount:+,} 积分"],
            ["扣减来源", bucket or "—"],
            ["变动后余额", f"{int(item.get('balance_after') or 0):,}"],
            ["时间", _local_time(item.get("created_at"))],
        ]
        if item.get("request_id"):
            # 退款行用 "<原请求号>:refund"，展示时去掉后缀，避免和扣费行看起来是两个请求。
            detail.append(["请求编号", str(item["request_id"]).replace(":refund", "")])
        if item.get("note"):
            detail.append(["备注", str(item["note"]).replace("预扣 ", "").strip()])
        rows.append(
            {
                "kind": row_kind,
                "at": _local_time(item.get("created_at")),
                "title": title,
                "status": label,
                "tone": tone,
                "amount": f"{amount:+,} 积分".replace("+-", "-"),
                # 退款冲正也是「加回积分」，但语义不是收入，用蓝色和消费区分开。
                "amount_class": "refund" if row_kind == "refund" else ("in" if amount > 0 else "out"),
                "points": bucket or "—",
                "bal": f"余 {int(item.get('balance_after') or 0):,}",
                "detail": detail,
                "order": "",
            }
        )
    return rows


def _month_key(now: datetime, back: int) -> str:
    """从当前月往回数 ``back`` 个自然月，返回 ``YYYY-MM``。

    不能用 ``now - timedelta(days=30*back)``：月末会漂移叠加，出现重复或跳月。
    """
    index = now.year * 12 + (now.month - 1) - back
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def _revenue() -> dict[str, Any] | None:
    """站长视角：网站充值收入汇总。仅 OWNER 可见。"""
    now = _beijing_now()
    months: list[dict[str, Any]] = []
    total_net = Decimal("0")
    refunded_total = Decimal("0")
    pending_credit = Decimal("0")
    try:
        with accounts.DB_LOCK, accounts._connect() as connection:
            for back in range(5, -1, -1):
                first = _month_key(now, back)
                gross_row = connection.execute(
                    """SELECT COALESCE(SUM(CAST(r.amount AS NUMERIC)),0), COUNT(*)
                       FROM alipay_recharges r WHERE r.status='CREDITED'
                         AND substr(COALESCE(r.credited_at, r.created_at),1,7)=?""",
                    (first,),
                ).fetchone()
                refund_row = connection.execute(
                    """SELECT COALESCE(SUM(CAST(o.refunded_amount AS NUMERIC)),0)
                       FROM alipay_orders o WHERE CAST(o.refunded_amount AS NUMERIC) > 0
                         AND substr(COALESCE(o.paid_at, o.created_at),1,7)=?""",
                    (first,),
                ).fetchone()
                gross = _money(gross_row[0] if gross_row else 0)
                refund = _money(refund_row[0] if refund_row else 0)
                months.append(
                    {"month": first, "gross": gross, "refund": refund, "net": gross - refund,
                     "count": int(gross_row[1] if gross_row else 0)}
                )
            total_row = connection.execute(
                """SELECT COALESCE(SUM(CAST(r.amount AS NUMERIC)),0) FROM alipay_recharges r WHERE r.status='CREDITED'"""
            ).fetchone()
            refund_total_row = connection.execute(
                """SELECT COALESCE(SUM(CAST(o.refunded_amount AS NUMERIC)),0) FROM alipay_orders o"""
            ).fetchone()
            pending_row = connection.execute(
                """SELECT COALESCE(SUM(CAST(r.amount AS NUMERIC)),0), COUNT(*)
                   FROM alipay_recharges r LEFT JOIN alipay_orders o ON o.out_trade_no=r.out_trade_no
                   WHERE o.status='PAID' AND r.status<>'CREDITED'"""
            ).fetchone()
    except Exception:  # noqa: BLE001 - 未启支付时不展示收入
        return None
    gross_total = _money(total_row[0] if total_row else 0)
    refunded_total = _money(refund_total_row[0] if refund_total_row else 0)
    pending_credit = _money(pending_row[0] if pending_row else 0)
    total_net = gross_total - refunded_total
    current = months[-1]["net"] if months else Decimal("0")
    previous = months[-2]["net"] if len(months) > 1 else Decimal("0")
    if previous > 0:
        change = ((current - previous) / previous * 100).quantize(Decimal("0.1"))
    else:
        change = None
    peak = max([m["net"] for m in months] or [Decimal("0")]) or Decimal("1")
    return {
        "months": [
            {
                "month": m["month"],
                "net": _cny(m["net"]),
                "width": round(float(m["net"]) * 100 / float(peak), 1),
                "count": m["count"],
                "current": m is months[-1],
            }
            for m in months
        ],
        "current_month": months[-1]["month"] if months else now.strftime("%Y-%m"),
        "current_net": _cny(current),
        "total_net": _cny(total_net),
        "refunded": _cny(refunded_total),
        "refunded_text": f"−{_cny(refunded_total)}" if refunded_total > 0 else "¥0.00",
        "pending": _cny(pending_credit),
        "change": change,
        "current_count": months[-1]["count"] if months else 0,
    }


def _summary(rows: list[dict[str, Any]], cash_rows: list[dict[str, Any]]) -> dict[str, Any]:
    now = _beijing_now()
    month = now.strftime("%Y-%m")
    month_points = 0
    for row in rows:
        if row["kind"] != "consume" or not str(row["at"]).startswith(month):
            continue
        text = str(row["amount"]).replace(",", "").replace(" 积分", "")
        try:
            month_points += -int(text)
        except ValueError:
            continue
    month_cash = Decimal("0")
    paid_count = 0
    total_cash = Decimal("0")
    pending = 0
    for row in cash_rows:
        if row["kind"] == "recharge" and row["tone"] in ("ok", "amber"):
            total_cash += Decimal(str(row.get("cash") or 0))
            paid_count += 1
            if str(row["at"]).startswith(month):
                month_cash += Decimal(str(row.get("cash") or 0))
        if row["tone"] == "wait":
            pending += 1
    return {
        "month_cash": _cny(month_cash),
        "month_points": month_points,
        "total_cash": _cny(total_cash),
        "paid_count": paid_count,
        "pending": pending,
    }


def _collect(request: Request) -> tuple[dict[str, Any] | None, HTMLResponse | None]:
    try:
        user = accounts.user_from_request(request)
    except Exception:  # noqa: BLE001
        user = None
    if user is None:
        return None, _login_required_page()
    package_names = _package_names()
    cash = _cash_rows(user["id"], package_names)
    points = _point_rows(user["id"], package_names)
    rows = sorted(cash + points, key=lambda item: str(item["at"]), reverse=True)
    summary = _summary(sorted(points, key=lambda i: i["at"]), cash)
    wallet = accounts.wallet_summary(user["id"])
    is_owner = (
        str(user.get("role") or "") == "admin"
        and str(user.get("email") or "").lower() == accounts.OWNER_EMAIL
    )
    payload = {
        "rows": rows,
        "summary": summary,
        "wallet": wallet,
        "owner": is_owner,
        "revenue": _revenue() if is_owner else None,
        "email": user.get("email") or "",
    }
    return payload, None


@router.get("/bill", response_class=HTMLResponse, include_in_schema=False)
def bill_page(request: Request) -> HTMLResponse:
    payload, failure = _collect(request)
    if failure is not None or payload is None:
        return failure or _login_required_page()
    wallet = payload["wallet"]
    summary = payload["summary"]
    balance = int(wallet["balance"])
    revenue = payload["revenue"]

    stats = (
        '<div class="bl-stats">'
        f'<div class="bl-stat"><p class="k">本月支出</p><p class="v">{summary["month_cash"]}'
        f'<em>/ {summary["month_points"]:,} 积分</em></p></div>'
        f'<div class="bl-stat"><p class="k">累计充值</p><p class="v">{summary["total_cash"]}'
        f'<em>/ {summary["paid_count"]} 笔</em></p></div>'
        f'<div class="bl-stat"><p class="k">积分构成</p><p class="v">{balance:,}'
        f'<em>付费 {int(wallet["paid"]):,} · 赠送 {int(wallet["bonus"]):,} · 试用 {int(wallet["trial"]):,}</em></p></div>'
        f'<div class="bl-stat"><p class="k">待支付订单</p><p class="v">{summary["pending"]}<em>笔</em></p></div>'
        "</div>"
    )
    hero = (
        '<section class="bl-hero">'
        f'<div class="bl-bal"><b>{balance:,}</b><span>积分</span>'
        f"<small>≈ ¥{balance * 0.1:,.2f} · 1 积分 = 0.1 元</small></div>"
        + stats
        + "</section>"
    )

    revenue_block = ""
    if revenue:
        change = revenue.get("change")
        if change is None:
            delta = '<span class="bl-badge gray">无上月数据</span>'
        elif change >= 0:
            delta = f'<span class="bl-badge ok">↑ {change}% 环比</span>'
        else:
            delta = f'<span class="bl-badge amber">↓ {abs(change)}% 环比</span>'
        bars = "".join(
            f'<div class="bl-bar"><span class="m">{m["month"][5:]} 月</span>'
            f'<span class="bl-track"><i class="{"now" if m["current"] else ""}" '
            f'style="width:{max(m["width"], 1.2)}%"></i></span>'
            f'<span class="a">{m["net"]}</span></div>'
            for m in revenue["months"]
        )
        revenue_block = (
            '<section class="bl-rev">'
            '<div class="bl-rev-head"><div>'
            '<p class="bl-eyebrow">REVENUE · 站长视角</p>'
            f'<div class="bl-rev-big"><b>{revenue["current_net"]}</b>'
            f'<span>{revenue["current_month"]} 净收入</span></div>'
            f"</div>{delta}</div>"
            '<div class="bl-rev-mini">'
            f'<div>累计净收入<b>{revenue["total_net"]}</b></div>'
            f'<div>待入账<b class="amber">{revenue["pending"]}</b></div>'
            f'<div>退款冲减<b class="amber">{revenue["refunded_text"]}</b></div>'
            f'<div>本月笔数<b>{revenue["current_count"]} 笔</b></div>'
            "</div>"
            '<div class="bl-bars"><div class="bl-bars-t"><span>近 6 个月充值收入</span>'
            f"<span>按支付宝到账金额</span></div>{bars}</div>"
            "</section>"
        )

    tabs = (
        '<div class="bl-toolbar"><div class="bl-tabs" id="bl-tabs" role="group" aria-label="账单类型筛选">'
        '<button type="button" class="active" data-filter="all">全部</button>'
        '<button type="button" data-filter="recharge">充值</button>'
        '<button type="button" data-filter="refund">退款</button>'
        '<button type="button" data-filter="consume">消费</button>'
        '<button type="button" data-filter="grant">赠送</button>'
        "</div>"
        '<div class="bl-tools">'
        '<select id="bl-range" aria-label="时间范围">'
        '<option value="all">全部时间</option><option value="month">本月</option>'
        '<option value="last">上月</option><option value="90">近 90 天</option></select>'
        '<a href="/api/bill/export.csv" download>导出 CSV</a>'
        "</div></div>"
    )

    data_json = json.dumps({"rows": payload["rows"]}, ensure_ascii=False).replace("</", "<\\/")
    body = (
        '<header class="bl-head"><a class="bl-back" href="/">← 返回工作台</a>'
        '<a class="bl-cta" href="/pricing">充值积分</a></header>'
        '<p class="bl-eyebrow">BILLING STATEMENT</p>'
        "<h1>我的账单</h1>"
        f'<p class="bl-account">{payload["email"]} · 支付宝网页支付</p>'
        + hero
        + revenue_block
        + tabs
        + '<section id="bl-list" aria-live="polite"></section>'
        + '<p class="bl-foot">积分与现金分开记录：积分用于站内功能，¥ 为真实支付金额。<br>'
        "退款会同时冲正积分，积分冲正不等于现金到账。</p>"
        + f'<script type="application/json" id="bl-data">{data_json}</script>'
        + _SCRIPT
    )
    return HTMLResponse(_page("我的账单", body), headers={"Cache-Control": "no-store"})


_SCRIPT = """
<script>
(() => {
  const data = JSON.parse(document.getElementById('bl-data').textContent || '{}');
  const rows = Array.isArray(data.rows) ? data.rows : [];
  const list = document.getElementById('bl-list');
  const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let filter = sessionStorage.getItem('bl-filter') || 'all';
  let range = sessionStorage.getItem('bl-range') || 'all';

  const today = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  const dayOf = (iso) => String(iso || '').slice(0, 10);
  const monthOf = (iso) => String(iso || '').slice(0, 7);
  const nowMonth = `${today.getFullYear()}-${pad(today.getMonth() + 1)}`;
  const lastMonth = (() => {
    const d = new Date(today.getFullYear(), today.getMonth() - 1, 1);
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}`;
  })();

  function inRange(item) {
    if (range === 'all') return true;
    const iso = String(item.at || '');
    if (range === 'month') return monthOf(iso) === nowMonth;
    if (range === 'last') return monthOf(iso) === lastMonth;
    if (range === '90') {
      const then = new Date(today.getTime() - 90 * 86400000);
      return new Date(iso.replace(' ', 'T')) >= then;
    }
    return true;
  }

  function dayLabel(day) {
    const localToday = `${today.getFullYear()}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}`;
    const y = new Date(today.getTime() - 86400000);
    const localYesterday = `${y.getFullYear()}-${pad(y.getMonth() + 1)}-${pad(y.getDate())}`;
    if (day === localToday) return '今天 · ' + day.slice(5).replace('-', ' 月 ') + ' 日';
    if (day === localYesterday) return '昨天 · ' + day.slice(5).replace('-', ' 月 ') + ' 日';
    return day.slice(5).replace('-', ' 月 ') + ' 日';
  }
  const timeOf = (iso) => { const m = String(iso || '').match(/[T ](\\d{2}:\\d{2})/); return m ? m[1] : ''; };
  const glyph = (item) => item.amount_class === 'refund' ? '↩'
    : item.amount_class === 'wait' ? '·'
    : String(item.amount).trim().startsWith('-') ? '−' : '+';

  function render() {
    const shown = rows.filter(r => (filter === 'all' || r.kind === filter) && inRange(r));
    if (!shown.length) {
      list.innerHTML = rows.length
        ? '<p class="bl-empty">当前筛选下没有记录</p>'
        : '<p class="bl-empty">还没有账单记录<br><a href="/pricing">去充值积分</a></p>';
      return;
    }
    let html = '', day = '', i = 0;
    for (const item of shown) {
      const d = dayOf(item.at);
      if (d !== day) { day = d; html += `<div class="bl-day"><span>${esc(dayLabel(d))}</span></div>`; }
      const detail = (item.detail || []).map(([k, v]) => {
        const isOrder = /订单号|交易号/.test(k);
        const val = isOrder ? `<button class="bl-copy" type="button" data-copy="${esc(v)}">${esc(v)}</button>` : esc(v);
        return `<div><dt>${esc(k)}</dt><dd>${val}</dd></div>`;
      }).join('');
      html += `<article class="bl-row" tabindex="0">
        <span class="bl-ico ${esc(item.amount_class)}">${glyph(item)}</span>
        <div>
          <p class="bl-title">${esc(item.title)}<span class="bl-badge ${esc(item.tone)}">${esc(item.status)}</span></p>
          <p class="bl-meta"><span>${esc(timeOf(item.at))}</span><span class="sep">·</span><span>${esc(item.points)}</span></p>
        </div>
        <span class="bl-amount ${esc(item.amount_class)}">${esc(item.amount)}<small>${esc(item.bal || '')}</small></span>
        <div class="bl-detail"><dl class="bl-dl">${detail}</dl></div>
      </article>`;
      i++;
    }
    list.innerHTML = html;
  }

  document.getElementById('bl-tabs')?.addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-filter]');
    if (!btn) return;
    filter = btn.dataset.filter;
    sessionStorage.setItem('bl-filter', filter);
    document.querySelectorAll('#bl-tabs button').forEach(b => b.classList.toggle('active', b === btn));
    render();
  });
  document.getElementById('bl-range')?.addEventListener('change', (e) => {
    range = e.target.value; sessionStorage.setItem('bl-range', range); render();
  });
  list.addEventListener('click', async (e) => {
    const copy = e.target.closest('button[data-copy]');
    if (copy) {
      e.stopPropagation();
      try {
        await navigator.clipboard.writeText(copy.dataset.copy);
        const t = copy.textContent; copy.textContent = '已复制';
        setTimeout(() => copy.textContent = t, 1200);
      } catch (_) {}
      return;
    }
    const row = e.target.closest('.bl-row');
    if (row) row.classList.toggle('open');
  });
  list.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      const row = e.target.closest('.bl-row');
      if (row) { e.preventDefault(); row.classList.toggle('open'); }
    }
  });

  document.querySelectorAll('#bl-tabs button').forEach(b =>
    b.classList.toggle('active', b.dataset.filter === filter));
  const rangeEl = document.getElementById('bl-range');
  if (rangeEl) rangeEl.value = range;
  render();
})();
</script>
"""


@router.get("/api/bill/export.csv", include_in_schema=False)
def export_csv(request: Request) -> Response:
    payload, failure = _collect(request)
    if payload is None:
        return Response("请先登录", status_code=401, media_type="text/plain; charset=utf-8")
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["时间", "类型", "说明", "状态", "金额/积分", "积分桶", "订单号"])
    kind_label = {"recharge": "充值", "refund": "退款", "consume": "消费", "grant": "赠送"}
    for row in payload["rows"]:
        writer.writerow([
            row["at"], kind_label.get(row["kind"], row["kind"]), row["title"],
            row["status"], row["amount"], row["points"], row["order"],
        ])
    body = "\ufeff" + buffer.getvalue()
    return Response(
        body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="bill.csv"',
            "Cache-Control": "no-store",
        },
    )
