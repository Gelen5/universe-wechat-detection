"""Model-driven intent routing for the WeChat workbench.

The composer must not guess a stage from keywords: "我准备写一篇关于 AI 的文章，
给我下选题" contains 写一篇 but means 选题. One small structured call reads the
message together with the current workbench state and returns the stage to run
(or decides the message is just a question).

Routing never blocks the run: any provider error, timeout or malformed answer
falls back to the stage the user is currently looking at.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

STAGE_LABELS = {
    "topic": "选题",
    "outline": "大纲",
    "writing": "写作",
    "deai": "去 AI 复核",
    "typeset": "排版",
}
RUNNABLE = tuple(STAGE_LABELS)
MIN_CONFIDENCE = 0.55
ROUTER_TIMEOUT = 25

_ALIASES = {
    "选题": "topic", "方向": "topic", "topics": "topic", "title": "topic",
    "大纲": "outline", "框架": "outline", "outlines": "outline",
    "写作": "writing", "正文": "writing", "article": "writing", "write": "writing",
    "去ai": "deai", "去 ai": "deai", "复核": "deai", "review": "deai", "审校": "deai",
    "排版": "typeset", "html": "typeset", "typesetting": "typeset",
    "null": None, "none": None, "answer": None, "": None, "无": None, "提问": None,
}

_SYSTEM = """你是「公众号创作助手」的调度器。你的唯一任务是判断用户这句话要让工作台执行哪一步。
工作台只有五个可执行阶段，顺序固定：topic 选题 → outline 大纲 → writing 写作 → deai 去 AI 复核 → typeset 排版。

必须按用户的真实意图判断，不要按字面关键词：
- “我准备写一篇关于 AI 的文章，给我下选题” → topic（出现了“写一篇”，但请求是选题）
- “就按第 2 个方向写吧” → 当前阶段决定：还没大纲就 outline，已有大纲就 writing
- “太长了，第三段压缩一下” → 有正文时为 deai 或 writing 的局部修改，优先 deai
- “这篇能发吗”“帮我总结一下前面” → null（这只是提问，不执行阶段）
- “再换一批方向” → topic

如果用户明确指定了某个阶段（例如“直接排版”），就返回该阶段。
只输出 JSON，不要 Markdown，不要解释。

JSON 字段：
{"stage":"topic|outline|writing|deai|typeset|null",
 "direction":"用户想写的方向，没提到就空字符串",
 "selected_topic":"用户明确选定或指代的选题标题，没有就空字符串",
 "instruction":"把这句话归一化成对该阶段的一句要求",
 "reason":"给用户看的中文说明，20 字以内，例如“先给你 10 个选题”",
 "confidence":0.0 到 1.0}
"""


@dataclass(frozen=True)
class Intent:
    stage: str | None
    instruction: str = ""
    direction: str = ""
    selected_topic: str = ""
    reason: str = ""
    confidence: float = 0.0
    source: str = "model"  # model | explicit | fallback
    detail: dict[str, Any] = field(default_factory=dict)


def _clip(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _parse(raw: str) -> dict[str, Any] | None:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (raw or "").strip(), flags=re.I)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _normalize_stage(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    key = value.strip().lower()
    if key in STAGE_LABELS:
        return key
    return _ALIASES.get(key, None)


def _prompt(text: str, stage_hint: str, artifacts: list[dict], recent: list[dict]) -> str:
    done = [item.get("type") for item in artifacts if item.get("type")]
    latest: dict[str, dict] = {}
    for item in artifacts:
        current = latest.get(item.get("type") or "")
        if current is None or (item.get("version") or 0) > (current.get("version") or 0):
            latest[item.get("type") or ""] = item
    titles = []
    for topic in (latest.get("topic", {}).get("content_json") or {}).get("topics") or []:
        title = _clip(topic.get("title") if isinstance(topic, dict) else topic, 60)
        if title:
            titles.append(title)
    article = latest.get("article") or {}
    tail = "\n".join(
        f"- {item.get('role')}: {_clip(item.get('content'), 200)}"
        for item in recent[-6:] if item.get("role") in {"user", "assistant"}
    )
    return f"""当前标签：{stage_hint}（{STAGE_LABELS.get(stage_hint, stage_hint)}）
已有产物类型：{", ".join(sorted(set(done))) or "无"}
正文标题：{_clip(article.get("title") or "", 80) or "无"}
最近选题（最多 6 个）：{json.dumps(titles[:6], ensure_ascii=False)}
最近对话：
{tail or "- 无"}

用户这句话：{text}
"""


def _fallback(text: str, stage_hint: str, reason: str) -> Intent:
    return Intent(stage=stage_hint, instruction=text, reason=reason,
                  confidence=0.0, source="fallback", detail={"error": reason})


def resolve_intent(*, model_service, text: str, stage_hint: str, artifacts: list[dict],
            recent: list[dict], run_id: str, user_id: str,
            explicit_stage: str | None = None) -> Intent:
    """Return the stage this message should execute.

    ``explicit_stage`` skips the model entirely: the user pressed a button or a
    stage tab, so there is nothing to interpret.
    """
    if explicit_stage in RUNNABLE:
        return Intent(stage=explicit_stage, instruction=text, source="explicit",
                      reason=f"直接执行{STAGE_LABELS[explicit_stage]}", confidence=1.0)
    hint = stage_hint if stage_hint in RUNNABLE else "topic"
    prompt = _prompt(text, hint, artifacts, recent)
    try:
        response = model_service.create_response(
            [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": prompt}],
            timeout=ROUTER_TIMEOUT, idempotency_key=f"{run_id}:intent",
            run_id=run_id, user_id=user_id,
        )
    except Exception as exc:  # routing must never kill the run
        return _fallback(text, hint, f"意图判断失败：{type(exc).__name__}")
    data = _parse(getattr(response, "text", ""))
    if not data:
        return _fallback(text, hint, "没有看懂这句要做什么，按当前步骤继续")
    stage = _normalize_stage(data.get("stage"))
    try:
        confidence = max(0.0, min(1.0, float(data.get("confidence") or 0)))
    except (TypeError, ValueError):
        confidence = 0.0
    if stage is not None and stage not in RUNNABLE:
        return _fallback(text, hint, "没有识别出阶段，按当前步骤继续")
    # Switching away from the tab (or answering instead of working) needs
    # confidence; continuing the current stage never does.
    if (stage is None or stage != hint) and confidence < MIN_CONFIDENCE:
        return _fallback(text, hint, "不太确定要换步骤，先按当前步骤继续")
    return Intent(
        stage=stage,
        instruction=_clip(data.get("instruction") or text, 2000),
        direction=_clip(data.get("direction"), 300),
        selected_topic=_clip(data.get("selected_topic"), 200),
        reason=_clip(data.get("reason"), 60) or (
            f"执行{STAGE_LABELS[stage]}" if stage else "这是提问，不执行阶段"),
        confidence=confidence,
        source="model",
        detail={"raw": data},
    )
