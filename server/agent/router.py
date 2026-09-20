from __future__ import annotations

import json
from dataclasses import dataclass

from ..providers import ModelService
from ..skills.registry import SkillRegistry


@dataclass(frozen=True)
class RouteDecision:
    skill_id: str | None
    confidence: float
    reason: str
    needs_confirmation: bool = False


class SkillRouter:
    def __init__(self, registry: SkillRegistry, model_service: ModelService | None = None):
        self.registry = registry
        self.model_service = model_service

    def route(self, message: str, *, mode: str, bound_skill_id: str | None = None,
              run_id: str | None = None, user_id: str | None = None) -> RouteDecision:
        if mode == "manual":
            if not bound_skill_id:
                raise ValueError("manual conversation has no bound Skill")
            self.registry.get(bound_skill_id)
            return RouteDecision(bound_skill_id, 1.0, "conversation is bound to this Skill")
        keyword = self._keyword_route(message)
        if keyword:
            return keyword
        if not self.model_service:
            return RouteDecision(None, 0.0, "request is ambiguous", True)
        catalog = self.registry.router_catalog()
        response = self.model_service.create_response([
            {"role": "system", "content": "Choose exactly one Skill from the catalog. Return JSON with skill_id, confidence from 0 to 1, reason. If uncertain set skill_id null."},
            {"role": "user", "content": json.dumps({"message": message, "skills": catalog}, ensure_ascii=False)},
        ], timeout=30, run_id=run_id, user_id=user_id)
        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            return RouteDecision(None, 0.0, "router returned invalid response", True)
        skill_id = data.get("skill_id")
        confidence = max(0.0, min(1.0, float(data.get("confidence") or 0)))
        if skill_id not in {item["id"] for item in catalog} or confidence < 0.55:
            return RouteDecision(None, confidence, str(data.get("reason") or "uncertain"), True)
        return RouteDecision(skill_id, confidence, str(data.get("reason") or "model route"))

    def _keyword_route(self, message: str) -> RouteDecision | None:
        text = message.lower()
        rules = (
            ("morning_blessing", ("早安", "祝福图")),
            ("wechat_account_analyzer", ("公众号诊断", "账号为什么没流量", "账号分析")),
            ("wechat_hit_detector", ("爆文检测", "发布前复核", "检查这篇文章")),
            ("xiaohongshu_creator", ("小红书", "红薯笔记")),
            ("wechat_tie_tu", ("贴图号", "微信卡片")),
            ("wechat_writer", ("公众号文章", "公众号选题", "写一篇文章", "配图", "重新排版")),
        )
        available = {item.id for item in self.registry.list()}
        for skill_id, keywords in rules:
            if skill_id in available and any(word in text for word in keywords):
                return RouteDecision(skill_id, 0.9, f"matched product intent: {skill_id}")
        return None
