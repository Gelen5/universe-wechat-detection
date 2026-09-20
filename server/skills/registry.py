from __future__ import annotations

import threading
from pathlib import Path

from .loader import discover_manifests, load_manifest
from .schema import SkillManifest


DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "vendor" / "skills"


class SkillRegistry:
    def __init__(self, roots: tuple[Path, ...] | None = None):
        self.roots = roots or (DEFAULT_ROOT,)
        self._skills: dict[str, SkillManifest] = {}

    def reload(self) -> "SkillRegistry":
        discovered: dict[str, SkillManifest] = {}
        for root in self.roots:
            for path in discover_manifests(root):
                manifest = load_manifest(path)
                if manifest.id in discovered:
                    raise ValueError(f"duplicate Skill id: {manifest.id}")
                discovered[manifest.id] = manifest
        self._skills = discovered
        return self

    def get(self, skill_id: str) -> SkillManifest:
        try:
            return self._skills[skill_id]
        except KeyError as exc:
            raise KeyError(f"unknown Skill: {skill_id}") from exc

    def list(self) -> list[SkillManifest]:
        return sorted(self._skills.values(), key=lambda item: item.id)

    def router_catalog(self) -> list[dict]:
        return [item.router_summary() for item in self.list() if item.trusted]

    def executable(self, skill_id: str) -> SkillManifest:
        manifest = self.get(skill_id)
        if not manifest.trusted:
            raise PermissionError(f"Skill is not trusted for in-process execution: {skill_id}")
        return manifest


_lock = threading.Lock()
_registry: SkillRegistry | None = None


def get_registry(*, refresh: bool = False) -> SkillRegistry:
    global _registry
    with _lock:
        if _registry is None or refresh:
            _registry = SkillRegistry().reload()
        return _registry
