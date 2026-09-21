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
            self.registry.executable(bound_skill_id)
            return RouteDecision(bound_skill_id, 1.0, "conversation is bound to this Skill")
        keyword = self._keyword_route(message)
        if keyword:
            return keyword
        if not self.model_service:
            if bound_skill_id:
                self.registry.executable(bound_skill_id)
                return RouteDecision(bound_skill_id, 0.6, "use previous Skill as a soft prior")
            return RouteDecision(None, 0.0, "request is ambiguous", True)
        catalog = self.registry.router_catalog()
        response = self.model_service.create_response([
            {"role": "system", "content": "Choose exactly one Skill from the catalog. Return JSON with skill_id, confidence from 0 to 1, reason. If uncertain set skill_id null."},
            {"role": "user", "content": json.dumps({"message": message, "skills": catalog,
                                                       "last_skill_id": bound_skill_id}, ensure_ascii=False)},
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
        skills = sorted(
            (item for item in self.registry.list() if item.trusted),
            key=lambda item: int(item.routing.get("priority") or 0), reverse=True,
        )
        for skill in skills:
            keywords = tuple(str(value).lower() for value in skill.routing.get("keywords", []))
            if any(word in text for word in keywords):
                return RouteDecision(skill.id, 0.9, f"matched manifest routing: {skill.id}")
        return None
