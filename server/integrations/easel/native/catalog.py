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

DISPLAY_NAMES = {
    "skill-account-diagnosis": "账号定位诊断",
    "skill-article-outline": "文章大纲",
    "skill-audience-profiler": "读者画像",
    "skill-carousel-planner": "轮播图策划",
    "skill-content-matrix": "内容矩阵",
    "skill-positioning-analysis": "账号定位分析",
    "skill-strategy-advisor": "内容策略建议",
    "skill-topic-evaluator": "选题评估",
    "skill-voice-builder": "表达风格构建",
    "style-transfer": "文风迁移",
}

DEFAULT_ROOT = Path(__file__).resolve().parents[4] / "vendor" / "easel" / "skills" / "openclaw"


def skill_loader() -> NativeSkillLoader:
    return NativeSkillLoader(Path(os.getenv("EASEL_SKILLS_ROOT") or DEFAULT_ROOT))


def native_manifests() -> list[SkillManifest]:
    loader = skill_loader()
    manifests = []
    for name in APPROVED_TEXT_SKILLS:
        skill = loader.load(name)
        manifests.append(SkillManifest(
            id="easel_" + name.replace("-", "_"), name=DISPLAY_NAMES[name],
            version="4b9c03c", description=skill.description or skill.name,
            capabilities=(skill.category, "easel"), tools=(), root=skill.root,
            manifest_path=skill.root / "SKILL.md",
            pricing={"base_points": 10}, limits={"max_tool_calls": 0, "timeout_seconds": 300},
            routing={"keywords": [], "priority": 0},
            runtime={"engine": "easel_native", "default_artifact": "article" if name == "style-transfer" else "report"},
            trusted=True,
        ))
    return manifests
