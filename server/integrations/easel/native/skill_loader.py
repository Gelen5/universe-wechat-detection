from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class NativeSkill:
    id: str
    name: str
    description: str
    category: str
    instructions: str
    metadata: dict[str, Any]
    root: Path
    references: tuple[Path, ...]
    scripts: tuple[Path, ...]


class NativeSkillLoader:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def list_ids(self) -> tuple[str, ...]:
        if not self.root.is_dir():
            return ()
        return tuple(sorted(path.parent.name for path in self.root.glob("*/SKILL.md")))

    def load(self, skill_id: str) -> NativeSkill:
        if not skill_id or not all(ch.isascii() and (ch.isalnum() or ch == "-") for ch in skill_id):
            raise ValueError("invalid Easel Skill id")
        skill_root = (self.root / skill_id).resolve()
        if skill_root.parent != self.root:
            raise ValueError("Skill path escapes Easel root")
        path = skill_root / "SKILL.md"
        if not path.resolve().is_relative_to(skill_root):
            raise ValueError("Skill instructions escape Easel root")
        source = path.read_text(encoding="utf-8-sig")
        if not source.startswith("---\n"):
            raise ValueError(f"Skill {skill_id} has no YAML frontmatter")
        parts = source.split("---\n", 2)
        if len(parts) != 3:
            raise ValueError(f"Skill {skill_id} has malformed YAML frontmatter")
        metadata = yaml.safe_load(parts[1])
        if not isinstance(metadata, dict):
            raise ValueError(f"Skill {skill_id} has invalid YAML metadata")
        instructions = parts[2].strip()
        if not instructions:
            raise ValueError(f"Skill {skill_id} has empty instructions")
        def assets(folder: str) -> tuple[Path, ...]:
            parent = skill_root / folder
            return tuple(sorted(path for path in parent.rglob("*") if path.is_file()
                                and path.resolve().is_relative_to(skill_root))) if parent.is_dir() else ()
        return NativeSkill(
            id=skill_id, name=str(metadata.get("name") or skill_id),
            description=str(metadata.get("description") or "").strip(),
            category=str(metadata.get("layer") or metadata.get("category") or "unclassified"),
            instructions=instructions, metadata=metadata, root=skill_root,
            references=assets("references"), scripts=assets("scripts"),
        )
