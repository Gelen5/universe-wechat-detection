"""Explicitly approved first batch of text-only Easel Skills."""
from __future__ import annotations

import os
from pathlib import Path

from ....skills.schema import SkillManifest
from .skill_loader import NativeSkillLoader


APPROVED_TEXT_SKILLS = (
    "skill-account-diagnosis", "skill-article-outline", "skill-audience-profiler",
    "skill-carousel-planner", "skill-content-matrix", "skill-positioning-analysis",
    "skill-strategy-advisor", "skill-topic-evaluator", "skill-voice-builder",
    "style-transfer",
)

DEFAULT_ROOT = Path(__file__).resolve().parents[4] / "vendor" / "easel" / "skills" / "openclaw"


def skill_loader() -> NativeSkillLoader:
    return NativeSkillLoader(Path(os.getenv("EASEL_SKILLS_ROOT") or DEFAULT_ROOT))


def native_manifests() -> list[SkillManifest]:
    loader = skill_loader()
    manifests = []
    for name in APPROVED_TEXT_SKILLS:
        skill = loader.load(name)
        manifests.append(SkillManifest(
            id="easel_" + name.replace("-", "_"), name=skill.name,
            version="4b9c03c", description=skill.description or skill.name,
            capabilities=(skill.category, "easel"), tools=(), root=skill.root,
            manifest_path=skill.root / "SKILL.md",
            pricing={"base_points": 10}, limits={"max_tool_calls": 0, "timeout_seconds": 300},
            routing={"keywords": [], "priority": 0},
            runtime={"engine": "easel_native", "default_artifact": "article"},
            trusted=True,
        ))
    return manifests
