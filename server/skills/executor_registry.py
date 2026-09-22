from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from .executor import ToolExecutor
from .schema import SkillManifest


class ExecutorRegistry:
    """Loads only trusted, Skill-local adapters declared by the manifest."""

    def __init__(self):
        self._cache: dict[tuple[str, str], dict[str, ToolExecutor]] = {}

    def tools(self, manifest: SkillManifest) -> dict[str, ToolExecutor]:
        if not manifest.trusted:
            raise PermissionError(f"untrusted Skill cannot load Python adapter: {manifest.id}")
        adapter = str(manifest.runtime.get("adapter") or "").strip()
        if not adapter or Path(adapter).name != adapter or not adapter.endswith(".py"):
            raise ValueError(f"Skill {manifest.id} needs a local runtime.adapter Python file")
        path = (manifest.manifest_path.parent / adapter).resolve()
        root = manifest.manifest_path.parent.resolve()
        if path.parent != root or not path.is_file():
            raise ValueError(f"Skill {manifest.id} adapter is outside its manifest directory")
        key = (manifest.id, str(path))
        if key not in self._cache:
            module = self._load(manifest.id, path)
            factory = getattr(module, "create_tools", None)
            if not callable(factory):
                raise ValueError(f"Skill {manifest.id} adapter must export create_tools()")
            tools = factory()
            if not isinstance(tools, dict) or not all(callable(value) for value in tools.values()):
                raise ValueError(f"Skill {manifest.id} adapter returned invalid tools")
            declared = {tool.executor for tool in manifest.tools}
            missing = declared - set(tools)
            if missing:
                raise ValueError(f"Skill {manifest.id} adapter missing executors: {sorted(missing)}")
            self._cache[key] = tools
        return self._cache[key]

    @staticmethod
    def _load(skill_id: str, path: Path) -> ModuleType:
        # Celery starts from its console-script directory. Keep the project
        # root importable for trusted adapters that use the vendored Skill
        # namespace (for example ``vendor.skills...``).
        project_root = str(Path(__file__).resolve().parents[2])
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        name = f"universe_skill_adapter_{skill_id}_{abs(hash(path))}"
        spec = importlib.util.spec_from_file_location(name, path)
        if not spec or not spec.loader:
            raise ImportError(f"cannot load Skill adapter: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


_registry = ExecutorRegistry()


def get_executor_registry() -> ExecutorRegistry:
    return _registry
