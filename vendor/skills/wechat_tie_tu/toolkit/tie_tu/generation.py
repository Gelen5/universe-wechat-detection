"""Prompt and state helpers for host-native Tie-Tu image generation.

The Python toolkit never calls an image provider and never creates a fallback
request that could be mistaken for an API workflow. The agent layer must call
the current host's built-in Image capability, then record the returned file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from .models import CardPlan, TieTuPlan
from .portrait_prompt import render_portrait_prompt
from .workflow import record_batch


def build_card_prompt(plan: TieTuPlan, card: CardPlan) -> str:
    if card.portrait_spec:
        return render_portrait_prompt(card.portrait_spec)
    exact_text = card.overlay_text or (plan.title if card.role == "cover" else card.caption or card.purpose)
    return (
        f"Create a {plan.ratio} vertical image for a WeChat Tie-Tu post. "
        f"Topic: {plan.topic}. Card purpose: {card.purpose}. "
        f"Visual subject: {card.visual_subject}. Composition: {card.composition}. "
        f'Text (verbatim): "{exact_text}". '
        "Render the exact Simplified Chinese text directly in this same image-generation call, "
        "with clear hierarchy and mobile readability. Keep one clear visual focus and a clean text-safe area. "
        "Do not add any extra words, logos or watermarks."
    )


def generate_pilot(plan: TieTuPlan, output_dir: str, provider: Optional[str] = None,
                   generator: Optional[Any] = None) -> Optional[str]:
    if plan.approval_state.stages.get("card_plan") != "approved":
        raise RuntimeError("卡片策划未处于可生成状态")
    raise RuntimeError(
        "图片必须由当前宿主会话的内置 Image 能力生成，再使用 pilot --image 记录；"
        "本 Skill 不调用 CLI/API 图片提供商，也不需要任何 API Key。"
    )


def generate_batch(plan: TieTuPlan, output_dir: str, provider: Optional[str] = None,
                   generator: Optional[Any] = None) -> int:
    if plan.approval_state.stages.get("pilot_image") != "approved":
        raise RuntimeError("请先确认试生成图片：tie-tu approve --stage pilot_image --status approved")
    if provider is not None or generator is not None:
        raise RuntimeError("已禁用 CLI/API 图片提供商；请使用当前宿主会话的内置 Image 能力。")
    generated = 0
    for card in plan.cards:
        if card.image_path and Path(card.image_path).exists():
            generated += 1
        else:
            plan.generation_state.mark_card(card.index, "pending", error="等待当前宿主内置 Image 生成并记录")
    record_batch(
        plan,
        "completed" if generated == len(plan.cards) else "pending",
        "" if generated == len(plan.cards) else "请使用当前宿主内置 Image 逐张生成，再用 pilot --index N --image 记录",
    )
    return generated
