from __future__ import annotations

import uuid
from typing import Any, Callable

from .. import creator_tools, image_provider, workbench
from .executor import ToolContext
from .tool_result import ArtifactOutput, ToolResult


def required_text(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required")
    return value.strip()


def with_provider(call: Callable[[], Any]):
    with workbench.provider_overrides():
        return call()


def topics_result(topics: Any) -> ToolResult:
    lines = []
    for index, topic in enumerate(topics if isinstance(topics, list) else [topics], 1):
        title = topic.get("title") if isinstance(topic, dict) else str(topic)
        lines.append(f"{index}. {title or ''}")
    return ToolResult({"topics": topics}, (ArtifactOutput(
        type="topic", title="选题建议", content="\n".join(lines),
        content_json={"topics": topics},
    ),))


def article_result(title: str, article: str) -> ToolResult:
    return ToolResult({"title": title, "article": article}, (ArtifactOutput(
        type="article", title=title or "创作稿件", content=article,
    ),))


def report_result(title: str, report: Any) -> ToolResult:
    content = report if isinstance(report, str) else str(report.get("article") or report.get("report") or report)
    data = report if isinstance(report, dict) else {"report": report}
    return ToolResult(data, (ArtifactOutput(type="report", title=title, content=content, content_json=data),))


def image_result(raw: dict[str, Any]) -> ToolResult:
    values = raw.get("images") or raw.get("data") or []
    if isinstance(values, dict):
        values = [values]
    artifacts = tuple(ArtifactOutput(
        type="image", title=f"生成图片 {index + 1}", content_json=item if isinstance(item, dict) else {"url": str(item)},
    ) for index, item in enumerate(values if isinstance(values, list) else []))
    return ToolResult(raw, artifacts)


def generate_images(args: dict[str, Any], context: ToolContext, *, product: str) -> ToolResult:
    draft = args.get("draft")
    if not isinstance(draft, dict) or not isinstance(draft.get("cards"), list):
        raise ValueError("draft with cards is required")
    style = str(args.get("style") or "")
    images = [with_provider(lambda card=card: creator_tools.generate_card_image(
        product, str(draft.get("session_id") or uuid.uuid4().hex), card, style,
        size=str(args.get("size") or draft.get("size") or "768x1024"),
    )) for card in draft["cards"]]
    return image_result({"images": images})


def model_image(args: dict[str, Any], context: ToolContext) -> ToolResult:
    prompt = required_text(args, "prompt")
    size, count = str(args.get("size") or "1024x1024"), int(args.get("count") or 1)
    raw = context.model_service.generate_image(
        prompt, size=size, count=count,
        idempotency_key=context.idempotency_key,
        run_id=context.run_id, user_id=context.user_id,
    )
    return image_result(raw)
