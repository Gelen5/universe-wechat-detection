from __future__ import annotations

from pathlib import Path

from .registry import SkillRegistry, get_registry


def load_instructions(skill_id: str, *, registry: SkillRegistry | None = None) -> tuple[str, Path]:
    """Load full Skill instructions only after routing selected one Skill."""
    manifest = (registry or get_registry()).get(skill_id)
    path = manifest.root / "SKILL.md"
    return path.read_text(encoding="utf-8"), path
