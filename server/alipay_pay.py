"""AI 网页应用收款（支付宝统一收单 alipay.trade.page.pay）接入。

覆盖下单、交易查询、退款、退款查询、关闭交易、异步通知和同步回跳结果页。

支付配置来源：项目根目录 ``.alipay-sandbox.json``（快速沙箱产物，已加入
``.gitignore``，不入库）。服务端启动时不读取，首次请求时按文件实际内容加载，
避免把密钥写进代码、日志或配置副本。

安全边界：
- 同步回跳参数只用于定位订单，支付结果一律以交易查询或已验签的异步通知为准；
- 异步通知必须验签、校验业务字段并做幂等，处理成功返回纯文本 ``success``；
- 生产环境请用 ``ALIPAY_GATEWAY`` 指向生产网关并配置公网 HTTPS ``ALIPAY_NOTIFY_URL``。
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import Column, MetaData, String, Table, insert, select, update
from sqlalchemy.exc import IntegrityError

from alipay.aop.api.AlipayClientConfig import AlipayClientConfig
from alipay.aop.api.DefaultAlipayClient import DefaultAlipayClient
from alipay.aop.api.domain.AlipayTradeCloseModel import AlipayTradeCloseModel
from alipay.aop.api.domain.AlipayTradeFastpayRefundQueryModel import AlipayTradeFastpayRefundQueryModel
from alipay.aop.api.domain.AlipayTradePagePayModel import AlipayTradePagePayModel
from alipay.aop.api.domain.AlipayTradeQueryModel import AlipayTradeQueryModel
from alipay.aop.api.domain.AlipayTradeRefundModel import AlipayTradeRefundModel
from alipay.aop.api.request.AlipayTradeCloseRequest import AlipayTradeCloseRequest
from alipay.aop.api.request.AlipayTradeFastpayRefundQueryRequest import AlipayTradeFastpayRefundQueryRequest
from alipay.aop.api.request.AlipayTradePagePayRequest import AlipayTradePagePayRequest
from alipay.aop.api.request.AlipayTradeQueryRequest import AlipayTradeQueryRequest
from alipay.aop.api.request.AlipayTradeRefundRequest import AlipayTradeRefundRequest
from alipay.aop.api.util.SignatureUtils import get_sign_content, verify_with_rsa

from .database import ENGINE

logger = logging.getLogger(__name__)

router = APIRouter(tags=["alipay-pay"])

ROOT = Path(__file__).resolve().parents[1]
SANDBOX_CONFIG_PATH = ROOT / ".alipay-sandbox.json"
SANDBOX_GATEWAY = "https://openapi-sandbox.dl.alipaydev.com/gateway.do"
PRODUCTION_GATEWAY = "https://openapi.alipay.com/gateway.do"

PAGE_PAY_PRODUCT_CODE = "FAST_INSTANT_TRADE_PAY"
PAID_STATUSES = ("TRADE_SUCCESS", "TRADE_FINISHED")
_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
_AMOUNT_RE = re.compile(r"^\d{1,9}(?:\.\d{1,2})?$")


class PaymentConfigError(RuntimeError):
    """沙箱/生产支付配置缺失或不可用。"""


# ------------------------------------------------------------------ 配置
def _read_sandbox_entry(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise PaymentConfigError(
            "未找到 .alipay-sandbox.json，请先完成沙箱配置或改用生产支付配置"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PaymentConfigError("支付配置文件无法解析") from exc

    entries = payload.get("appIds") or []
    if not isinstance(entries, list) or not entries:
        raise PaymentConfigError("支付配置中没有可用的应用信息")
    entry = entries[0]
    if not isinstance(entry, dict) or not str(entry.get("appId") or "").strip():
        raise PaymentConfigError("支付配置中没有可用的应用信息")
    return entry


def load_payment_config() -> dict[str, str]:
    """按项目根配置文件加载运行时支付配置（Python 使用 PKCS#1 私钥字段）。"""

    entry = _read_sandbox_entry(SANDBOX_CONFIG_PATH)

    app_id = str(entry.get("appId") or "").strip()
    private_key = str(entry.get("appPrivatePkcsKey") or "").strip()
    alipay_public_key = str(entry.get("alipayPublicKey") or "").strip()
    if not private_key:
        raise PaymentConfigError("支付配置缺少 appPrivatePkcsKey（Python 需要 PKCS#1 私钥）")
    if not alipay_public_key:
        raise PaymentConfigError("支付配置缺少 alipayPublicKey")

    gateway = os.getenv("ALIPAY_GATEWAY", "").strip() or SANDBOX_GATEWAY
    return {
        "app_id": app_id,
        "private_key": private_key,
        "alipay_public_key": alipay_public_key,
        "seller_id": str(entry.get("pid") or "").strip(),
        "gateway": gateway,
    }


def build_client(config: dict[str, str]) -> DefaultAlipayClient:
    client_config = AlipayClientConfig()
    client_config.server_url = config["gateway"]
    client_config.app_id = config["app_id"]
    client_config.app_private_key = config["private_key"]
    client_config.alipay_public_key = config["alipay_public_key"]
    client_config.charset = "utf-8"
    client_config.sign_type = "RSA2"
    return DefaultAlipayClient(alipay_client_config=client_config)


def _client() -> DefaultAlipayClient:
    return build_client(load_payment_config())


# ------------------------------------------------------------------ 存储
metadata = MetaData()

alipay_orders = Table(
    "alipay_orders",
    metadata,
    Column("out_trade_no", String(64), primary_key=True),
    Column("app_id", String(32), nullable=False),
    Column("subject", String(256), nullable=False),
    Column("total_amount", String(32), nullable=False),
    Column("status", String(32), nullable=False),
    Column("trade_no", String(64)),
    Column("refunded_amount", String(32), nullable=False, default="0.00"),
    Column("created_at", String(32), nullable=False),
    Column("paid_at", String(32)),
    Column("updated_at", String(32), nullable=False),
)

alipay_notify_events = Table(
    "alipay_notify_events",
    metadata,
    Column("notify_id", String(128), primary_key=True),
    Column("out_trade_no", String(64)),
    Column("trade_no", String(64)),
    Column("trade_status", String(32)),
    Column("received_at", String(32), nullable=False),
)


def ensure_schema() -> None:
    metadata.create_all(ENGINE, checkfirst=True)


ensure_schema()


def _now() -> str:
    return datetime.now().strftime(_TIMESTAMP_FORMAT)


def _normalize_amount(value: Any, *, field: str = "金额") -> str:
    text = str(value if value is not None else "").strip()
    if not _AMOUNT_RE.match(text):
        raise ValueError(f"{field}格式不正确")
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:  # pragma: no cover - 正则已拦截
        raise ValueError(f"{field}格式不正确") from exc
    if amount < Decimal("0.01") or amount > Decimal("100000000"):
        raise ValueError(f"{field}超出取值范围")
    return f"{amount.quantize(Decimal('0.01'))}"


def _amount_of(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except InvalidOperation:
        return Decimal("0")


def _find_order(out_trade_no: str) -> dict[str, Any] | None:
    with ENGINE.begin() as connection:
        row = connection.execute(
            select(alipay_orders).where(alipay_orders.c.out_trade_no == out_trade_no)
        ).mappings().first()
    return dict(row) if row else None


def _set_order_status(
    out_trade_no: str,
    status: str,
    *,
    trade_no: str | None = None,
    paid_at: str | None = None,
) -> None:
    values: dict[str, Any] = {"status": status, "updated_at": _now()}
    if trade_no:
        values["trade_no"] = trade_no
    if paid_at:
        values["paid_at"] = paid_at
    with ENGINE.begin() as connection:
        connection.execute(
            update(alipay_orders)
            .where(alipay_orders.c.out_trade_no == out_trade_no)
            .values(**values)
        )


def _bump_refunded(out_trade_no: str, amount: Decimal) -> None:
    order = _find_order(out_trade_no)
    if order is None:
        return
    total = _amount_of(order["refunded_amount"]) + amount
    with ENGINE.begin() as connection:
        connection.execute(
            update(alipay_orders)
            .where(alipay_orders.c.out_trade_no == out_trade_no)
            .values(refunded_amount=f"{total.quantize(Decimal('0.01'))}", updated_at=_now())
        )


def _new_out_trade_no() -> str:
    return f"PAY{datetime.now().strftime('%Y%m%d%H%M%S')}{secrets.token_hex(4).upper()}"


# ------------------------------------------------------------------ SDK 调用
def _biz_content(response: Any, node: str) -> dict[str, Any]:
    """解析 SDK 返回。

    当前 SDK 的 ``execute()`` 已完成报文解包与响应验签，返回的字符串通常是业务
    节点内容本身；同时兼容仍带 ``alipay_xxx_response`` 外壳的版本。
    """

    if isinstance(response, dict):
        payload: Any = response
    else:
        try:
            payload = json.loads(response)
        except (TypeError, ValueError):
            return {"code": "PARSE_ERROR"}
    if not isinstance(payload, dict):
        return {"code": "PARSE_ERROR"}
    if isinstance(payload.get("code"), str):
        return payload
    value = payload.get(node)
    if isinstance(value, dict):
        return value
    return {"code": "PARSE_ERROR"}


def _trade_query(out_trade_no: str) -> dict[str, Any]:
    request = AlipayTradeQueryRequest()
    model = AlipayTradeQueryModel()
    model.out_trade_no = out_trade_no
    request.biz_model = model
    client = _client()
    return _biz_content(client.execute(request), "alipay_trade_query_response")


def _trade_close(out_trade_no: str) -> dict[str, Any]:
    request = AlipayTradeCloseRequest()
    model = AlipayTradeCloseModel()
    model.out_trade_no = out_trade_no
    request.biz_model = model
    client = _client()
    return _biz_content(client.execute(request), "alipay_trade_close_response")


def _trade_refund(out_trade_no: str, refund_amount: str, out_request_no: str, reason: str) -> dict[str, Any]:
    request = AlipayTradeRefundRequest()
    model = AlipayTradeRefundModel()
    model.out_trade_no = out_trade_no
    model.refund_amount = refund_amount
    model.out_request_no = out_request_no
    if reason:
        model.refund_reason = reason
    request.biz_model = model
    client = _client()
    return _biz_content(client.execute(request), "alipay_trade_refund_response")


def _refund_query(out_trade_no: str, out_request_no: str) -> dict[str, Any]:
    request = AlipayTradeFastpayRefundQueryRequest()
    model = AlipayTradeFastpayRefundQueryModel()
    model.out_trade_no = out_trade_no
    model.out_request_no = out_request_no
    request.biz_model = model
    client = _client()
    return _biz_content(client.execute(request), "alipay_trade_fastpay_refund_query_response")


def _page_pay_form(
    out_trade_no: str,
    total_amount: str,
    subject: str,
    *,
    return_url: str,
    notify_url: str,
) -> str:
    request = AlipayTradePagePayRequest()
    if notify_url:
        request.notify_url = notify_url
    if return_url:
        request.return_url = return_url
    model = AlipayTradePagePayModel()
    model.out_trade_no = out_trade_no
    model.total_amount = total_amount
    model.subject = subject
    model.product_code = PAGE_PAY_PRODUCT_CODE
    request.biz_model = model
    client = _client()
    # 页面跳转类接口必须使用 page_execute，不能使用 execute。
    return client.page_execute(request, http_method="POST")


# ------------------------------------------------------------------ 验签
def verify_alipay_signature(params: dict[str, str], config: dict[str, str] | None = None) -> bool:
    """用项目已安装的支付宝 SDK 验签能力校验同步/异步参数的 sign。"""

    sign = str(params.get("sign") or "").strip()
    if not sign:
        return False
    config = config or load_payment_config()
    payload = {key: value for key, value in params.items() if key not in ("sign", "sign_type")}
    try:
        return bool(verify_with_rsa(config["alipay_public_key"], get_sign_content(payload), sign))
    except Exception:  # noqa: BLE001 - 验签异常一律视为未通过
        logger.warning("alipay signature check raised", exc_info=True)
        return False


def _is_paid_notification(params: dict[str, str]) -> bool:
    status = params.get("trade_status") or ""
    if status not in PAID_STATUSES:
        return False
    return not params.get("out_biz_no") and not params.get("gmt_refund") and not params.get("refund_fee")


def _seller_matches(config: dict[str, str], params: dict[str, str]) -> bool:
    expected_id = config.get("seller_id") or ""
    seller_id = params.get("seller_id") or ""
    if not expected_id:
        return True
    return seller_id == expected_id


# ------------------------------------------------------------------ 页面
_STYLE = """
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:radial-gradient(1200px 600px at 50% -10%,#eef2ff 0%,#f7f7f5 45%,#f4f1ec 100%);
color:#1f2328;font-family:"PingFang SC","Microsoft YaHei",-apple-system,system-ui,sans-serif;padding:32px}
.card{width:min(560px,100%);background:#fff;border:1px solid rgba(23,26,31,.08);border-radius:20px;
box-shadow:0 24px 60px -32px rgba(23,26,31,.35);padding:32px}
.brand{display:flex;align-items:center;gap:10px;font-size:13px;letter-spacing:.08em;color:#6b7280}
.dot{width:8px;height:8px;border-radius:50%;background:#1677ff}
h1{font-size:22px;margin:18px 0 6px}
p.lead{margin:0 0 22px;color:#5b6472;font-size:14px;line-height:1.6}
label{display:block;font-size:13px;color:#374151;margin:14px 0 6px}
input{width:100%;padding:12px 14px;border:1px solid #e3e6ea;border-radius:12px;font-size:15px;background:#fbfbfa}
input:focus{outline:none;border-color:#1677ff;background:#fff;box-shadow:0 0 0 3px rgba(22,119,255,.12)}
button{margin-top:22px;width:100%;padding:13px 16px;border:0;border-radius:12px;background:#1677ff;color:#fff;
font-size:15px;font-weight:600;cursor:pointer}
button:disabled{opacity:.6;cursor:progress}
.hint{margin-top:14px;font-size:12px;color:#8b94a3;line-height:1.6}
.status{display:inline-flex;align-items:center;gap:8px;padding:6px 12px;border-radius:999px;font-size:13px;font-weight:600}
.status.ok{background:#e8f7ee;color:#0f7b3f}
.status.wait{background:#fff5e6;color:#a15c00}
.status.bad{background:#fdecec;color:#b42318}
dl{display:grid;grid-template-columns:auto 1fr;gap:10px 18px;margin:22px 0 0;font-size:14px}
dt{color:#6b7280}
dd{margin:0;font-weight:600;word-break:break-all}
.actions{margin-top:24px;display:flex;gap:12px}
.actions a{flex:1;text-align:center;padding:11px 14px;border-radius:12px;text-decoration:none;font-size:14px;
border:1px solid #e3e6ea;color:#1f2328}
.actions a.primary{background:#1677ff;border-color:#1677ff;color:#fff}
"""


def _page(title: str, body: str) -> str:
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{title}</title><style>{_STYLE}</style></head><body>"
        f'<main class="card">{body}</main></body></html>'
    )


_PAY_PAGE_SCRIPT = """
<script>
const form = document.getElementById('pay-form');
const button = document.getElementById('submit');
const hint = document.getElementById('hint');
form.addEventListener('submit', async (event) => {
  event.preventDefault();
  button.disabled = true;
  hint.textContent = '正在创建支付宝订单…';
  try {
    const response = await fetch('/api/pay/alipay/orders', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        subject: document.getElementById('subject').value,
        total_amount: document.getElementById('amount').value,
      }),
    });
    const data = await response.json();
    if (!response.ok || !data.form_html) {
      hint.textContent = data.detail || '创建订单失败，请稍后重试';
      button.disabled = false;
      return;
    }
    // 支付接口返回的是 HTML 表单，必须渲染后自动提交，不能当 URL 跳转。
    const holder = document.createElement('div');
    holder.innerHTML = data.form_html;
    document.body.appendChild(holder);
    const payForm = holder.querySelector('form');
    if (payForm) { payForm.submit(); } else { hint.textContent = '未获取到支付表单'; button.disabled = false; }
  } catch (error) {
    hint.textContent = '网络异常，请稍后重试';
    button.disabled = false;
  }
});
</script>
"""


# ------------------------------------------------------------------ 请求模型
class CreateOrderPayload(BaseModel):
    subject: str = Field(min_length=1, max_length=256)
    total_amount: str = Field(min_length=1, max_length=32)
    out_trade_no: str | None = Field(default=None, max_length=64)


class RefundPayload(BaseModel):
    refund_amount: str = Field(min_length=1, max_length=32)
    out_request_no: str | None = Field(default=None, max_length=64)
    refund_reason: str = Field(default="", max_length=256)


def _return_url(request: Request) -> str:
    configured = os.getenv("ALIPAY_RETURN_URL", "").strip()
    if configured:
        return configured
    return str(request.base_url).rstrip("/") + "/api/pay/alipay/return"


def _notify_url() -> str:
    return os.getenv("ALIPAY_NOTIFY_URL", "").strip()


# ------------------------------------------------------------------ 接口
_PACKAGES = (
    ("入门", "100 积分", "10.00", "偶尔写作与配图"),
    ("进阶", "300 积分", "29.00", "每周稳定产出"),
    ("专业", "1000 积分", "88.00", "高频创作与批量改稿"),
)


@router.get("/pay", response_class=HTMLResponse, include_in_schema=False)
def pay_page(subject: str = "AI 写作助手 · 积分充值", amount: str = "10.00") -> HTMLResponse:
    safe_subject = (subject or "").strip()[:128] or "积分充值"
    try:
        safe_amount = _normalize_amount(amount)
    except ValueError:
        safe_amount = "10.00"
    body = (
        '<div class="brand"><span class="dot"></span>宇宙第一工作台 · 收银台</div>'
        "<h1>确认订单并支付</h1>"
        '<p class="lead">使用支付宝完成付款。付款结果以服务端交易查询与异步通知为准，本页不做成功判定。</p>'
        '<form id="pay-form">'
        '<label for="subject">订单标题</label>'
        f'<input id="subject" name="subject" value="{safe_subject}" maxlength="128" required>'
        '<label for="amount">应付金额（元）</label>'
        f'<input id="amount" name="amount" value="{safe_amount}" inputmode="decimal" required>'
        '<label>支付方式</label>'
        '<div style="display:flex;align-items:center;gap:10px;padding:12px 14px;border:1px solid #1677ff;'
        'border-radius:12px;background:#f5f9ff">'
        '<span style="display:inline-flex;width:22px;height:22px;border-radius:6px;background:#1677ff;'
        'color:#fff;font-size:12px;font-weight:700;align-items:center;justify-content:center">支</span>'
        '<span style="font-size:15px;font-weight:600">支付宝</span>'
        '<span style="margin-left:auto;font-size:12px;color:#1677ff">推荐</span>'
        "</div>"
        '<button id="submit" type="submit">前往支付宝付款</button>'
        "</form>"
        '<p class="hint" id="hint">金额范围 0.01 – 100000000.00 元；付款完成后可回到本页查询订单状态。</p>'
        + _PAY_PAGE_SCRIPT
    )
    return HTMLResponse(_page("收银台 · 确认支付", body), headers={"Cache-Control": "no-cache"})


@router.get("/pricing", response_class=HTMLResponse, include_in_schema=False)
def pricing_page() -> HTMLResponse:
    cards = []
    for name, credits, price, blurb in _PACKAGES:
        cards.append(
            '<a class="plan" href="/pay?subject=%E7%A7%AF%E5%88%86%E5%A5%97%E9%A4%90%C2%B7'
            + name
            + "&amount="
            + price
            + '">'
            + f'<div class="plan-name">{name}</div>'
            + f'<div class="plan-credits">{credits}</div>'
            + f'<div class="plan-blurb">{blurb}</div>'
            + f'<div class="plan-price">¥{price}</div>'
            + '<div class="plan-cta">立即购买</div>'
            + "</a>"
        )
    extra_style = (
        "<style>"
        ".plans{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin:22px 0 0}"
        ".plan{display:block;padding:18px;border:1px solid #e3e6ea;border-radius:16px;text-decoration:none;color:#1f2328;"
        "background:#fbfbfa;transition:border-color .15s ease,transform .15s ease}"
        ".plan:hover{border-color:#1677ff;transform:translateY(-2px)}"
        ".plan-name{font-size:13px;color:#6b7280}"
        ".plan-credits{font-size:20px;font-weight:700;margin-top:6px}"
        ".plan-blurb{font-size:12px;color:#8b94a3;margin-top:6px;min-height:32px}"
        ".plan-price{font-family:Georgia,serif;font-size:26px;margin-top:10px}"
        ".plan-cta{margin-top:12px;text-align:center;padding:9px 12px;border-radius:10px;"
        "background:#1677ff;color:#fff;font-size:13px;font-weight:600}"
        "</style>"
    )
    body = (
        '<div class="brand"><span class="dot"></span>宇宙第一工作台 · 商品</div>'
        "<h1>积分套餐</h1>"
        '<p class="lead">积分用于公众号创作、账号诊断、配图与改稿等能力，1 积分 = ¥0.10。选择套餐后进入支付宝收银台付款。</p>'
        + extra_style
        + '<div class="plans">'
        + "".join(cards)
        + "</div>"
        + '<p class="hint">付款成功后积分将记入当前账号；如需发票或对公转账，请联系服务方。</p>'
        + '<div class="actions"><a href="/">返回工作台</a>'
        '<a class="primary" href="/pay">直接前往收银台</a></div>'
    )
    return HTMLResponse(_page("积分套餐", body), headers={"Cache-Control": "no-cache"})


@router.post("/api/pay/alipay/orders")
def create_order(payload: CreateOrderPayload, request: Request) -> JSONResponse:
    try:
        total_amount = _normalize_amount(payload.total_amount)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    config = load_payment_config()
    out_trade_no = (payload.out_trade_no or "").strip() or _new_out_trade_no()
    now = _now()
    try:
        with ENGINE.begin() as connection:
            connection.execute(
                insert(alipay_orders).values(
                    out_trade_no=out_trade_no,
                    app_id=config["app_id"],
                    subject=payload.subject.strip(),
                    total_amount=total_amount,
                    status="CREATED",
                    refunded_amount="0.00",
                    created_at=now,
                    updated_at=now,
                )
            )
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="商户订单号已存在") from exc

    try:
        form_html = _page_pay_form(
            out_trade_no,
            total_amount,
            payload.subject.strip(),
            return_url=_return_url(request),
            notify_url=_notify_url(),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("alipay page pay failed", exc_info=True)
        raise HTTPException(status_code=502, detail="支付宝下单失败，请稍后重试") from exc

    return JSONResponse(
        {
            "out_trade_no": out_trade_no,
            "total_amount": total_amount,
            "subject": payload.subject.strip(),
            "form_html": form_html,
        }
    )


@router.get("/api/pay/alipay/orders/{out_trade_no}")
def get_order(out_trade_no: str) -> JSONResponse:
    order = _find_order(out_trade_no)
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    return JSONResponse(
        {
            "out_trade_no": order["out_trade_no"],
            "subject": order["subject"],
            "total_amount": order["total_amount"],
            "status": order["status"],
            "trade_no": order["trade_no"],
            "refunded_amount": order["refunded_amount"],
            "created_at": order["created_at"],
            "paid_at": order["paid_at"],
        }
    )


def _sync_from_query(order: dict[str, Any]) -> dict[str, Any]:
    result = _trade_query(order["out_trade_no"])
    if result.get("code") != "10000":
        return {"query": result, "order": order}
    status = result.get("trade_status") or ""
    mapped = {
        "TRADE_SUCCESS": "PAID",
        "TRADE_FINISHED": "PAID",
        "WAIT_BUYER_PAY": "PENDING_PAYMENT",
        "TRADE_CLOSED": "CLOSED",
    }.get(status, "UNKNOWN")
    if mapped == "PAID" and order["status"] != "PAID":
        _set_order_status(order["out_trade_no"], "PAID", trade_no=result.get("trade_no"), paid_at=_now())
        order = _find_order(order["out_trade_no"]) or order
    elif mapped == "CLOSED" and order["status"] == "CREATED":
        _set_order_status(order["out_trade_no"], "CLOSED")
        order = _find_order(order["out_trade_no"]) or order
    elif mapped == "PENDING_PAYMENT" and order["status"] == "CREATED":
        _set_order_status(order["out_trade_no"], "PENDING_PAYMENT")
        order = _find_order(order["out_trade_no"]) or order
    return {"query": result, "order": order}


@router.post("/api/pay/alipay/orders/{out_trade_no}/query")
def query_order(out_trade_no: str) -> JSONResponse:
    order = _find_order(out_trade_no)
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    try:
        synced = _sync_from_query(order)
    except PaymentConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.warning("alipay trade query failed", exc_info=True)
        raise HTTPException(status_code=502, detail="交易查询失败，请稍后重试") from exc
    result, current = synced["query"], synced["order"]
    return JSONResponse(
        {
            "out_trade_no": out_trade_no,
            "local_status": current["status"],
            "alipay_trade_status": result.get("trade_status"),
            "code": result.get("code"),
            "sub_code": result.get("sub_code"),
            "trade_no": result.get("trade_no") or current["trade_no"],
            "total_amount": result.get("total_amount") or current["total_amount"],
        }
    )


@router.post("/api/pay/alipay/orders/{out_trade_no}/close")
def close_order(out_trade_no: str) -> JSONResponse:
    order = _find_order(out_trade_no)
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order["status"] == "PAID":
        raise HTTPException(status_code=409, detail="已支付订单不能关闭")
    try:
        result = _trade_close(out_trade_no)
    except Exception as exc:  # noqa: BLE001
        logger.warning("alipay trade close failed", exc_info=True)
        raise HTTPException(status_code=502, detail="关闭交易失败，请稍后重试") from exc
    closed = result.get("code") == "10000"
    if closed:
        _set_order_status(out_trade_no, "CLOSED")
    return JSONResponse(
        {
            "out_trade_no": out_trade_no,
            "code": result.get("code"),
            "sub_code": result.get("sub_code"),
            "trade_no": result.get("trade_no"),
            "closed": closed,
        }
    )


@router.post("/api/pay/alipay/orders/{out_trade_no}/refund")
def refund_order(out_trade_no: str, payload: RefundPayload) -> JSONResponse:
    order = _find_order(out_trade_no)
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order["status"] != "PAID":
        raise HTTPException(status_code=409, detail="只有已支付订单可以退款")
    try:
        refund_amount = _normalize_amount(payload.refund_amount, field="退款金额")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    refunded = _amount_of(order["refunded_amount"])
    if refunded + Decimal(refund_amount) > _amount_of(order["total_amount"]):
        raise HTTPException(status_code=400, detail="累计退款金额超过订单实付金额")

    out_request_no = (payload.out_request_no or "").strip() or f"RF{secrets.token_hex(6).upper()}"
    try:
        result = _trade_refund(out_trade_no, refund_amount, out_request_no, payload.refund_reason)
    except Exception as exc:  # noqa: BLE001
        logger.warning("alipay trade refund failed", exc_info=True)
        raise HTTPException(status_code=502, detail="退款请求失败，请使用同一退款请求号重试") from exc

    fund_change = result.get("fund_change")
    if result.get("code") == "10000" and fund_change == "Y":
        _bump_refunded(out_trade_no, Decimal(refund_amount))
        _set_order_status(out_trade_no, "REFUNDED")
    return JSONResponse(
        {
            "out_trade_no": out_trade_no,
            "out_request_no": out_request_no,
            "code": result.get("code"),
            "sub_code": result.get("sub_code"),
            "fund_change": fund_change,
            "refund_fee": result.get("refund_fee"),
            "refund_amount": refund_amount,
            "needs_refund_query": fund_change != "Y",
        }
    )


@router.get("/api/pay/alipay/orders/{out_trade_no}/refund-query")
def refund_query_order(out_trade_no: str, out_request_no: str) -> JSONResponse:
    order = _find_order(out_trade_no)
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    if not out_request_no.strip():
        raise HTTPException(status_code=400, detail="缺少退款请求号")
    try:
        result = _refund_query(out_trade_no, out_request_no.strip())
    except Exception as exc:  # noqa: BLE001
        logger.warning("alipay refund query failed", exc_info=True)
        raise HTTPException(status_code=502, detail="退款查询失败，请稍后重试") from exc
    return JSONResponse(
        {
            "out_trade_no": out_trade_no,
            "out_request_no": out_request_no.strip(),
            "code": result.get("code"),
            "sub_code": result.get("sub_code"),
            "refund_status": result.get("refund_status"),
            "refund_amount": result.get("refund_amount"),
            "refunded": result.get("refund_status") == "REFUND_SUCCESS",
        }
    )


@router.post("/api/pay/alipay/notify")
async def alipay_notify(request: Request) -> PlainTextResponse:
    params: dict[str, str] = {}
    try:
        form = await request.form()
        params = {key: str(value) for key, value in form.items()}
    except Exception:  # noqa: BLE001
        logger.warning("alipay notify form parse failed", exc_info=True)
        return PlainTextResponse("fail")

    if not params.get("app_id") or not params.get("out_trade_no"):
        return PlainTextResponse("fail")

    try:
        config = load_payment_config()
    except PaymentConfigError:
        logger.warning("alipay notify rejected: payment config unavailable")
        return PlainTextResponse("fail")

    if params.get("app_id") != config["app_id"]:
        logger.warning("alipay notify rejected: app_id mismatch")
        return PlainTextResponse("fail")

    if not verify_alipay_signature(params, config):
        logger.warning("alipay notify rejected: signature check failed")
        return PlainTextResponse("fail")

    order = _find_order(params["out_trade_no"])
    if order is None:
        logger.warning("alipay notify rejected: order not found")
        return PlainTextResponse("fail")
    if not _seller_matches(config, params):
        logger.warning("alipay notify rejected: seller mismatch")
        return PlainTextResponse("fail")
    if _amount_of(params.get("total_amount")) != _amount_of(order["total_amount"]):
        logger.warning("alipay notify rejected: amount mismatch")
        return PlainTextResponse("fail")

    notify_id = (params.get("notify_id") or "").strip() or f"no-notify-id:{params['out_trade_no']}"
    try:
        with ENGINE.begin() as connection:
            connection.execute(
                insert(alipay_notify_events).values(
                    notify_id=notify_id,
                    out_trade_no=params.get("out_trade_no"),
                    trade_no=params.get("trade_no"),
                    trade_status=params.get("trade_status"),
                    received_at=_now(),
                )
            )
    except IntegrityError:
        # 幂等：同一 notify_id 已处理过，直接确认，避免重复记账。
        return PlainTextResponse("success")

    if _is_paid_notification(params) and order["status"] != "PAID":
        _set_order_status(
            order["out_trade_no"],
            "PAID",
            trade_no=params.get("trade_no"),
            paid_at=_now(),
        )
    return PlainTextResponse("success")


@router.get("/api/pay/alipay/return", response_class=HTMLResponse)
def alipay_return(request: Request) -> HTMLResponse:
    params = {key: str(value) for key, value in request.query_params.items()}
    out_trade_no = (params.get("out_trade_no") or "").strip()

    signature_ok = False
    if params.get("sign"):
        try:
            signature_ok = verify_alipay_signature(params)
        except PaymentConfigError:
            signature_ok = False

    # 回跳参数只用于定位订单，支付结果以服务端交易查询为准。
    order = _find_order(out_trade_no) if out_trade_no else None
    if order is None:
        return HTMLResponse(
            _page(
                "支付结果",
                '<div class="brand"><span class="dot"></span>支付宝 · AI 网页应用收款</div>'
                "<h1>未找到订单</h1>"
                '<p class="lead">回跳参数中没有可对应的本地订单。如已完成付款，请联系服务方核实。</p>'
                '<div class="actions"><a class="primary" href="/pay">返回付款页</a></div>',
            ),
            headers={"Cache-Control": "no-cache"},
        )

    status_text = "正在确认支付结果"
    status_class = "wait"
    detail = "支付宝回跳只表示支付流程结束，正在通过服务端交易查询确认最终状态。"
    try:
        synced = _sync_from_query(order)
        order = synced["order"]
        trade_status = synced["query"].get("trade_status") or ""
        if order["status"] == "PAID":
            status_text, status_class = "支付成功", "ok"
            detail = "服务端交易查询确认已付款。"
        elif trade_status == "WAIT_BUYER_PAY":
            status_text, status_class = "等待付款", "wait"
            detail = "交易已创建但买家尚未完成付款。"
        elif trade_status == "TRADE_CLOSED":
            status_text, status_class = "交易已关闭", "bad"
            detail = "交易已关闭，未收到付款。"
        else:
            status_text, status_class = "状态待确认", "wait"
            detail = "暂未查询到明确支付状态，请稍后在订单查询中确认。"
    except Exception:  # noqa: BLE001
        logger.warning("alipay return query failed", exc_info=True)
        status_text, status_class = "状态待确认", "wait"
        detail = "暂时无法连接支付宝查询状态，请稍后重试或联系服务方核实。"

    verify_text = "同步参数验签通过" if signature_ok else "同步参数未验签，仅依据服务端记录"
    body = (
        '<div class="brand"><span class="dot"></span>支付宝 · AI 网页应用收款</div>'
        f"<h1>{status_text}</h1>"
        f'<p class="lead"><span class="status {status_class}">{status_text}</span> {detail}</p>'
        "<dl>"
        f"<dt>订单号</dt><dd>{order['out_trade_no']}</dd>"
        f"<dt>订单标题</dt><dd>{order['subject']}</dd>"
        f"<dt>订单金额</dt><dd>{order['total_amount']} 元</dd>"
        f"<dt>支付宝交易号</dt><dd>{order['trade_no'] or '—'}</dd>"
        f"<dt>本地状态</dt><dd>{order['status']}</dd>"
        "</dl>"
        f'<p class="hint">{verify_text}。</p>'
        '<div class="actions">'
        f'<a class="primary" href="/api/pay/alipay/orders/{order["out_trade_no"]}">查看订单状态</a>'
        '<a href="/pay">继续付款</a></div>'
    )
    return HTMLResponse(_page("支付结果", body), headers={"Cache-Control": "no-cache"})
