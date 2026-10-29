"""Turn a failed Run into something the user can actually see and retry.

Before this module a failed stage only changed ``runs.status``; the chat thread
stayed silent and the browser showed one grey line in the panel header. Every
terminal failure now goes through :func:`fail_run`, which writes a normal
assistant message carrying structured metadata so the client can render a
failure card with a retry button.
"""
from __future__ import annotations

import re
from typing import Any

from .. import conversation_repository
from ..providers import ProviderRequestError

STAGE_LABELS = {
    "topic": "选题",
    "outline": "大纲",
    "writing": "写作",
    "deai": "去 AI 复核",
    "typeset": "排版",
}

_SECRET = re.compile(r"\b(?:sk|ak)-[A-Za-z0-9_\-]{6,}", re.I)


def safe_text(value: Any, limit: int = 600) -> str:
    """Strip credential-looking fragments and cap the length before storing."""
    text = _SECRET.sub("[已隐藏凭据]", str(value or "")).strip()
    text = re.sub(r"\s+", " ", text)
    return text[:limit]


def _provider_text(message: str) -> str:
    lower = message.lower()
    if "ip 不在令牌允许访问" in message or "ip is not allowed" in lower:
        return "文字模型拒绝当前服务器的 IP 访问。"
    if any(marker in message for marker in ("额度不足", "余额不足")) or any(
            marker in lower for marker in ("insufficient balance", "insufficient_quota", "quota")):
        return "文字模型额度不足。"
    if "provider connection failed" in lower or "remote end closed" in lower or "connection reset" in lower:
        return "与文字模型的连接被中断。"
    if any(marker in lower for marker in ('http 502', 'http 503', 'http 504', 'bad gateway', 'service unavailable')):
        return "文字模型中转服务暂时不可用，自动重试后仍未恢复。"
    if "timed out" in lower or "timeout" in lower or "time budget" in lower:
        return "模型调用超时。"
    return "模型服务返回了错误。"


def describe(exc: BaseException) -> dict[str, Any]:
    """Classify an exception into a stable code plus a human sentence."""
    message = safe_text(getattr(exc, "error_message", "") or str(exc), 400)
    code = str(getattr(exc, "code", "") or type(exc).__name__)

    def info(kind: str, reason: str, retryable: bool, advice: str = "") -> dict[str, Any]:
        return {"error_kind": kind, "reason": reason, "retryable": retryable,
                "advice": advice, "technical": f"{code}: {message}"[:600]}

    if "Skill 未完整安装" in message:
        return info("skill_missing", "服务端缺少公众号 Skill 文件，这一步无法执行。", False,
                    "请联系管理员安装 Skill 后再试。")
    if "Skill stage tool unavailable" in message:
        return info("stage_tool_missing", "当前版本缺少这个阶段的执行工具。", False,
                    "请换个阶段或升级服务。")
    if "热点抓取" in message:
        return info("topic_source", "抓取热点的脚本超时或被网络拦截。", True,
                    "这通常是一次性的，直接重试即可。")
    if "未返回合法 JSON" in message or "选题不足" in message or "返回了空选题" in message \
            or "去重后可用选题" in message or "文章框架不完整" in message \
            or "低于最低要求" in message or "少于最低要求" in message:
        return info("topic_schema", "模型返回的内容结构不完整，没有通过校验。", True,
                    "直接重试，或把方向写得更具体一点。")
    if "ip 不在令牌允许访问" in message or "ip is not allowed" in message.lower() \
            or code == "ip_not_allowed":
        return info("provider_access", "文字模型拒绝当前服务器的 IP 访问。", False,
                    "需要管理员把这个服务器的 IP 加进模型白名单。")
    if any(marker in message for marker in ("额度不足", "余额不足")) or any(
            marker in message.lower() for marker in ("insufficient balance", "insufficient_quota")):
        return info("provider_balance", "文字模型额度不足。", False,
                    "需要管理员充值后才能继续。")
    if 'Skill 精排版自动修复后仍未通过' in message or 'Skill 排版检查未通过' in message:
        reason = ("排版后的代码块内容或缩进与原文不一致。" if '代码块' in message
                  else "排版结果未完整保留原文。" if '文字不一致' in message
                  else "排版结果中的图片或链接与原文不一致。" if ('图片' in message or '链接' in message)
                  else "排版使用了公众号不支持的字号或行距。" if ('font_size_out_of_range' in message or 'line_height_out_of_range' in message)
                  else "排版的图片地址不符合公众号要求。" if 'image_host_not_wechat' in message
                  else "排版使用了公众号不支持的样式。" if 'css_' in message
                  else "排版结果未通过公众号兼容检查。")
        return info("layout_validation", reason + "原文已保留。", True,
                    "已自动尝试修复；可稍后重试或调整排版要求。")
    if '复制版图片' in message or '图片格式与内容不匹配' in message:
        return info("layout_image", "文章图片无法安全复制到公众号，原文已保留。", True,
                    "请检查图片格式和大小后重新排版。")
    if "自动修稿后仍需处理" in message:
        return info("review_validation", "改稿未通过原文保真检查，已保留原稿。", True,
                    "可缩小修改范围，或先核对文章中的引用和数字。")
    if "局部修改连续两次无法安全定位" in message:
        return info("review_validation", "模型返回的修改没有通过原文定位或保真检查，原文已保留。", True,
                    "可指定需要修改的段落后重试。")
    if "执行时间预算" in message or "time budget" in message.lower():
        return info("timeout", "模型处理超过本次时间预算，原稿已保留。", True, "稍后重试，或缩小修改范围。")
    cause = exc
    for _ in range(5):
        if isinstance(cause, ProviderRequestError):
            return info("provider", _provider_text(message), bool(cause.transient),
                        "原稿已保留；稍后可重试这一步。")
        cause = getattr(cause, '__cause__', None)
        if cause is None:
            break
    if "text API 请求失败" in message:
        return info("provider", _provider_text(message), True, "原稿已保留；稍后可重试这一步。")
    if isinstance(exc, ProviderRequestError) or code in {"http_error", "transport", "invalid_response",
                                                        "provider_unavailable", "timeout"}:
        retryable = bool(getattr(exc, "transient", True))
        return info("provider", _provider_text(message), retryable,
                    "稍等几秒再重试；如果连续失败，请联系管理员检查文字模型配置。")
    if isinstance(exc, TimeoutError):
        return info("timeout", "这一步超过了执行时限。", True, "可以把要求拆小一点再试。")
    if "maximum tool calls" in message:
        return info("tool_limit", "模型在一个阶段里调用工具次数过多，被中止。", True, "重试或换更具体的说法。")
    if "required stage tool was not called" in message:
        return info("tool_missing_call", "模型没有按要求执行这个阶段。", True, "直接重试即可。")
    return info("tool_error", "这一步执行时出错了。", True, "")


def _stage_of(run: dict[str, Any], user_id: str) -> str | None:
    if run.get("stage"):
        return str(run["stage"])
    message = conversation_repository.get_message(
        run["conversation_id"], user_id, run["trigger_message_id"])
    if not message:
        return None
    stage = (message.get("content_json") or {}).get("workflow_stage")
    return stage if isinstance(stage, str) else None


def _user_text(stage: str | None, detail: dict[str, Any]) -> str:
    label = STAGE_LABELS.get(stage or "", "当前阶段")
    lines = [f"「{label}」这一步没有跑完。", f"原因：{detail['reason']}"]
    if detail.get("advice"):
        lines.append(detail["advice"])
    lines.append("本轮积分已自动退回，已完成的阶段不会丢。可以点下面的「重试这一步」。")
    return "\n".join(lines)


def fail_run(run_id: str, user_id: str, exc: BaseException,
             task_id: str | None = None) -> dict[str, Any] | None:
    """Mark a run failed and append the user-visible failure message.

    Idempotent by construction: ``transition_run`` refuses to move a run that is
    already terminal (or whose execution lease moved), so whichever path
    finalises first also owns the message.
    """
    run = conversation_repository.get_run(run_id, user_id)
    if not run:
        return None
    if run["status"] in {"completed", "failed", "cancelled", "waiting_input"}:
        return None
    stage = _stage_of(run, user_id)
    detail = describe(exc)
    try:
        conversation_repository.transition_run(
            run_id, user_id, "failed",
            error_code=detail["error_kind"], error_message=detail["technical"],
            task_id=task_id,
        )
    except (KeyError, ValueError, RuntimeError):
        return None
    try:
        return conversation_repository.add_message(
            run["conversation_id"], user_id, "assistant", _user_text(stage, detail),
            content_json={
                "kind": "run_failed",
                "stage": stage,
                "run_id": run_id,
                "error_code": detail["error_kind"],
                "retryable": detail["retryable"],
            },
        )
    except Exception:  # never let bookkeeping hide the original failure
        return None
