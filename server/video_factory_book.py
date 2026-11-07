"""Book planning prompt; caller must obtain and verify its source material."""
from __future__ import annotations
from typing import Callable
from .video_factory_mpt import BookVideoPlan


def book_plan(topic: str, duration: int, sources: list[dict[str, str]], generate_json: Callable[[str], dict]) -> BookVideoPlan:
    if not sources or any(not source.get('url') or not source.get('summary') for source in sources):
        raise ValueError('书目信息需要附带来源和摘要')
    import json
    prompt = ('根据所给资料制作原创中文书单视频分镜，只输出 JSON 对象。不得编造书名作者、版本、原文引语或书中观点；'
              '资料无法证明的事实不要使用。scenes 每项包括 sequence、narration、duration_target、visual_prompt、'
              'evidence_refs（来源 URL），全片包括 topic、title、cover_title、duration_target、scenes。'
              '提供可公开使用的原创视觉设想，不复制书封。旁白应适合指定时长。\n'
              + json.dumps({'topic': topic, 'duration': duration, 'sources': sources}, ensure_ascii=False))
    data = generate_json(prompt)
    plan = BookVideoPlan.model_validate(data)
    if plan.topic != topic or plan.duration_target != duration:
        raise ValueError('计划与请求不一致')
    allowed = {source['url'] for source in sources}
    if any(not scene.evidence_refs or not set(scene.evidence_refs).issubset(allowed) for scene in plan.scenes):
        raise ValueError('分镜缺少有效来源')
    if [s.sequence for s in plan.scenes] != list(range(1,len(plan.scenes)+1)):
        raise ValueError('分镜顺序无效')
    return plan
