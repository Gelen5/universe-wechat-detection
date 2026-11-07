"""Standalone de-AI rewrite jobs backed by universe-delete-ai-skill."""
from __future__ import annotations

import json
import math
import os
import re
import uuid
from typing import Any

from . import accounts, workbench

TASK_TYPE = "deai_rewrite"
LANE = "text"
FEATURE = "去 AI 味"
MAX_CHARS = 12000
STEP_DEFS = (
    ("scan", "检测 AI 痕迹", 25),
    ("rewrite", "定向改写", 60),
    ("audit", "保真与可读性复核", 88),
    ("output", "输出结果", 100),
)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        return default


def points_for(text: str) -> int:
    """Three points per started 1,000 characters, bounded for safety."""
    base = max(1, _env_int("DEAI_POINTS_PER_1000", 3))
    minimum = max(1, _env_int("DEAI_MIN_POINTS", 3))
    maximum = max(minimum, _env_int("DEAI_MAX_POINTS", 30))
    size = len((text or "").strip())
    if not size:
        return minimum
    return max(minimum, min(maximum, math.ceil(size / 1000) * base))


def validate(text: str) -> str:
    value = (text or "").strip()
    if len(value) < 20:
        raise ValueError("原文至少需要 20 个字符")
    if len(value) > MAX_CHARS:
        raise ValueError(f"单次最多 {MAX_CHARS} 个字符，请分段处理")
    if re.fullmatch(r"https?://mp\.weixin\.qq\.com/[^\s]+", value, flags=re.I):
        raise ValueError("去 AI 味需要文章正文，请先提取公众号正文后再提交；不要直接粘贴文章链接")
    return value


def _requirements(mode: str, depth: int, version: str) -> str:
    mode_label = "小说" if mode == "novel" else "文章"
    version_label = "自然表达版" if version == "V2" else "综合清理版"
    return (
        "请明确调用 universe-delete-ai-skill，对下面的{0}做保真去 AI 味改写。\n"
        "改写深度：{1}/10。深度越高允许调整的句子和段落结构越多，但事实、数字、"
        "人名、机构、时间、直接引语、立场和因果强度都不得改变。\n"
        "版本取向：{2}。\n"
        "不要补写个人经历、案例、对白或数据。没有把握时保留原句，不要为了像真人而编造。"
    ).format(mode_label, depth, version_label)


_NUMBER_RE = re.compile(r"(?<![0-9A-Za-z_.])\d+(?:\.\d+)?%?")
_URL_RE = re.compile(r"https?://[^\s<>\"'）】。，；！？]+", re.I)
_QUOTE_RE = re.compile(r"“([^”]{2,200})”|「([^」]{2,200})」|\"([^\"]{2,200})\"")


def _numeric_tokens(text: str) -> set[str]:
    value = re.sub(r"(?m)^\s*\d+[.)、]\s+", "", text)
    value = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", value)
    value = re.sub(r"\[([^\]]*)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"https?://\S+", "", value, flags=re.I)
    return set(_NUMBER_RE.findall(value))


def _fallback_rewrite(article: str, *, mode: str, depth: int, version: str) -> str:
    """Full-text rewrite used when the skill cannot anchor a local edit.

    The skill's anchored path is intentionally strict; when a long or heavily
    paraphrased article defeats its exact-span repair, this fallback preserves
    the same hard facts while still producing a usable rewrite.
    """
    mode_label = "小说" if mode == "novel" else "文章"
    version_label = "自然表达" if version == "V2" else "综合清理"
    prompt = (
        f"你是一名中文编辑，只对下面的{mode_label}做表达层去 AI 味改写。\n"
        f"改写深度 {depth}/10，版本取向：{version_label}。\n"
        "必须保留全部事实、数字、人名、机构、时间、地点、因果、立场和段落顺序。\n"
        "必须逐字保留所有引号内原文、来源链接和 Markdown 结构。\n"
        "不得新增任何事实、案例、个人经历、对白、数据或结论。\n"
        "打散模板句、连续排比、空泛总结和机械过渡，让长短句和叙事节奏更自然。\n"
        "只输出改写后的完整正文，不要解释，不要输出 JSON 或代码围栏。\n\n"
        f"原文：\n{article}"
    )
    rewritten = workbench._text(prompt).strip()
    if not rewritten:
        raise ValueError("兜底改写没有返回内容")
    compact_original = len(re.sub(r"\s+", "", article))
    compact_rewritten = len(re.sub(r"\s+", "", rewritten))
    if compact_rewritten < max(30, int(compact_original * 0.5)):
        raise ValueError("兜底改写结果过短")
    if compact_rewritten > int(compact_original * 1.8) + 300:
        raise ValueError("兜底改写结果异常过长")
    missing_numbers = sorted(_numeric_tokens(article) - _numeric_tokens(rewritten))
    if missing_numbers:
        raise ValueError("兜底改写丢失原文数字：" + "、".join(missing_numbers[:8]))
    missing_urls = [url for url in _URL_RE.findall(article) if url not in rewritten]
    if missing_urls:
        raise ValueError("兜底改写丢失原文链接")
    original_quotes = [next(value for value in groups if value) for groups in _QUOTE_RE.findall(article)]
    if any(quote not in rewritten for quote in original_quotes):
        raise ValueError("兜底改写改动了原文引语")
    return rewritten


def run_job(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    article = validate(str(payload.get("content") or ""))
    mode = "novel" if str(payload.get("mode")) == "novel" else "article"
    version = "V2" if str(payload.get("version")) == "V2" else "V3.1"
    try:
        depth = max(1, min(10, int(payload.get("depth") or 5)))
    except (TypeError, ValueError):
        depth = 5
    steps = [
        {"key": key, "name": name, "status": "pending", "detail": "", "percent": end}
        for key, name, end in STEP_DEFS
    ]
    by_key = {step["key"]: step for step in steps}

    def write(percent: int, stage: str) -> None:
        accounts.progress_job(
            job_id,
            percent=max(0, min(100, int(percent))),
            stage=stage,
            steps=[
                {
                    "key": step["key"],
                    "name": step["name"],
                    "status": {"pending": 0, "running": 1, "done": 2, "failed": 3}[step["status"]],
                    "detail": step["detail"],
                }
                for step in steps
            ],
        )

    def set_step(key: str, status: str, detail: str, percent: int) -> None:
        by_key[key]["status"] = status
        by_key[key]["detail"] = detail
        write(percent, detail or by_key[key]["name"])

    set_step("scan", "running", "正在运行 AI 痕迹与可读性检测", 10)
    session = {
        "id": f"deai-{uuid.uuid4().hex}",
        "brief": _requirements(mode, depth, version),
        "conversation": [{
            "role": "user",
            "content": _requirements(mode, depth, version) + "\n原文：\n" + article,
        }],
    }

    def progress(_kind: str, data: dict[str, Any] | None = None) -> None:
        label = str((data or {}).get("label") or "正在复核与改稿")
        if "定位" in label:
            set_step("scan", "done", "已完成信号检测，定位到待处理表达", 30)
            set_step("audit", "running", label, 45)
        else:
            set_step("rewrite", "running", label, 65)

    fallback_reason = ""
    try:
        revised, report = workbench._review(article, session, progress)
    except Exception as exc:  # anchored review failed; keep a safe full rewrite
        fallback_reason = str(exc)[:240]
        revised = _fallback_rewrite(
            article, mode=mode, depth=depth, version=version
        )
        report = {
            "gate": "fallback_passed",
            "summary": "技能精确定位未成功，已改用保真全文改写完成",
            "fallback_reason": fallback_reason,
            "warnings": ["精确定位失败，已使用全文改写兜底并校验数字、引语和链接"],
        }
    by_key["scan"]["status"] = "done"
    by_key["scan"]["detail"] = "已完成 AI 痕迹与可读性检测"
    changed = revised != article
    gate = str(report.get("gate") or report.get("fidelity_gate", {}).get("status") or "needs_review")
    if not changed:
        set_step("rewrite", "done", "未发现可安全应用的改动，保留原文", 70)
    else:
        set_step("rewrite", "done", "已完成保真范围内的定向改写", 72)
    set_step(
        "audit",
        "done",
        "已完成保真全文改写与数字、引语、链接校验"
        if fallback_reason
        else ("已完成保真、完整句和篇幅复核" if gate == "passed" else "复核发现待人工确认项"),
        90,
    )
    result = {
        "content": revised,
        "original": article,
        "changed": changed,
        "gate": gate,
        "mode": mode,
        "depth": depth,
        "version": version,
        "summary": str(report.get("summary") or ("已完成改写" if changed else "正文未修改")),
        "warnings": (
            list(report.get("warnings") or [])
            + [str(item.get("reason") or item) for item in (report.get("pending_review_notes") or [])]
        )[:8],
        "fallback_reason": fallback_reason,
        "report": {
            key: report.get(key)
            for key in ("gate", "summary", "audit", "revision_evidence", "fidelity_gate", "manifest")
            if key in report
        },
        "steps": [
            {
                "key": step["key"],
                "name": step["name"],
                "status": {"pending": 0, "running": 1, "done": 2, "failed": 3}[step["status"]],
                "detail": step["detail"],
            }
            for step in steps
        ],
        "progress": 100,
        "results": [{"content": revised}],
    }
    set_step("output", "done", "成稿已输出", 100)
    result["steps"] = [
        {
            "key": step["key"],
            "name": step["name"],
            "status": {"pending": 0, "running": 1, "done": 2, "failed": 3}[step["status"]],
            "detail": step["detail"],
        }
        for step in steps
    ]
    return result


def rewrite_with_skill(
    content: str,
    *,
    mode: str = "article",
    depth: int = 5,
    version: str = "V3.1",
) -> tuple[str, str, dict[str, Any]]:
    """Reusable entry point for other workflows such as viral-article remix."""
    article = validate(content)
    session = {
        "id": f"deai-inline-{uuid.uuid4().hex}",
        "brief": _requirements(mode, depth, version),
        "conversation": [{
            "role": "user",
            "content": _requirements(mode, depth, version) + "\n原文：\n" + article,
        }],
    }
    try:
        revised, report = workbench._review(article, session)
    except Exception as exc:
        revised = _fallback_rewrite(
            article, mode=mode, depth=depth, version=version
        )
        report = {
            "gate": "fallback_passed",
            "summary": "技能精确定位未成功，已改用保真全文改写完成",
            "fallback_reason": str(exc)[:240],
        }
        return revised, "精确定位失败，已使用全文改写兜底并完成数字、引语和链接校验", report
    warning = ""
    if revised == article:
        warning = str(report.get("summary") or "未发现可安全应用的改动，已保留原稿")
    elif str(report.get("gate") or "") != "passed":
        warning = "去 AI 味结果有待人工确认：" + str(report.get("summary") or "")
    return revised, warning, report


def submit(
    user_id: str,
    *,
    request_id: str,
    content: str,
    mode: str,
    depth: int,
    version: str,
) -> dict[str, Any]:
    article = validate(content)
    mode = "novel" if mode == "novel" else "article"
    version = "V2" if version == "V2" else "V3.1"
    depth = max(1, min(10, int(depth or 5)))
    points = points_for(article)
    usage_id = accounts.reserve_points(
        user_id,
        {"points": points, "feature": FEATURE},
        "POST",
        "/api/deai/tasks",
    )
    try:
        job = accounts.create_job(
            user_id,
            TASK_TYPE,
            LANE,
            f"deai:{user_id}:{request_id}",
            usage_id,
            {
                "content": article,
                "mode": mode,
                "depth": depth,
                "version": version,
                "points": points,
            },
        )
    except Exception:
        accounts.refund_usage(usage_id, 500, 0)
        raise
    if not job:
        accounts.refund_usage(usage_id, 500, 0)
        raise RuntimeError("任务创建失败")
    return job


def public(job: dict[str, Any]) -> dict[str, Any]:
    payload = _load_json(job.get("payload_json"))
    result = _load_json(job.get("result_json"))
    status = str(job.get("status") or "queued")
    progress = result.get("progress") if isinstance(result.get("progress"), dict) else {}
    steps = progress.get("steps") or result.get("steps") or []
    if status == "succeeded" and steps:
        steps = [
            {**step, "status": 2}
            if isinstance(step, dict) and step.get("status") == 1
            else step
            for step in steps
        ]
    percent = 100 if status == "succeeded" else int(progress.get("percent") or 0)
    reserved = int(payload.get("points") or points_for(str(payload.get("content") or "")))
    codes = {"queued": 0, "running": 1, "succeeded": 2, "failed": 3, "canceled": 4}
    return {
        "id": job.get("id"),
        "status": status,
        "statusCode": codes.get(status, 0),
        "progress": percent,
        "stage": progress.get("stage") or ("已完成" if status == "succeeded" else "排队中"),
        "steps": steps,
        "content": result.get("content") or "",
        "original": result.get("original") or "",
        "changed": bool(result.get("changed")),
        "gate": result.get("gate") or "",
        "summary": result.get("summary") or "",
        "warnings": result.get("warnings") or [],
        "report": result.get("report") or {},
        "mode": payload.get("mode") or "article",
        "depth": payload.get("depth") or 5,
        "version": payload.get("version") or "V3.1",
        "error": job.get("error") or "",
        "canceled_at": job.get("canceled_at") or "",
        "points": {"reserved": reserved, "charged": reserved if status == "succeeded" else 0},
        "created_at": job.get("created_at"),
        "finished_at": job.get("finished_at"),
    }


def _load_json(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def settle(job: dict[str, Any], *, elapsed_ms: int, success: bool) -> None:
    usage_id = job.get("usage_id")
    if not usage_id:
        return
    if success:
        accounts.settle_usage(usage_id, 200, elapsed_ms)
    else:
        accounts.refund_usage(usage_id, 500, elapsed_ms)


def dispatch(job_id: str) -> str:
    from .deai_tasks import run

    task = run.delay(job_id)
    return str(task.id)
