from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from .schema import SkillManifest, ToolManifest


ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,79}$")


class SkillManifestError(ValueError):
    pass


def discover_manifests(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(root.glob("*/skill.json"))


def load_manifest(path: Path) -> SkillManifest:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SkillManifestError(f"cannot read Skill manifest {path}: {exc}") from exc
    _validate(data, path)
    configured_root = str(data.get("source_env") or "").strip()
    effective_root = Path(os.getenv(configured_root, "")).expanduser() if configured_root else path.parent
    if configured_root and not str(effective_root):
        effective_root = path.parent
    if not (effective_root / "SKILL.md").is_file():
        fallback = path.parent
        if (fallback / "SKILL.md").is_file():
            effective_root = fallback
        else:
            raise SkillManifestError(f"Skill {data['id']} has no SKILL.md at {effective_root}")
    tools = tuple(ToolManifest(name=item["name"], description=item["description"],
                               parameters=item.get("parameters") or {}) for item in data.get("tools", []))
    return SkillManifest(
        id=data["id"], name=data["name"], version=data["version"],
        description=data["description"].strip(), capabilities=tuple(data.get("capabilities", [])),
        tools=tools, root=effective_root.resolve(), manifest_path=path.resolve(),
        pricing=data.get("pricing") or {}, model_policy=data.get("model_policy") or {},
        limits=data.get("limits") or {}, trusted=data.get("trusted") is True,
    )


def _validate(data: dict[str, Any], path: Path) -> None:
    required = ("id", "name", "version", "description")
    missing = [key for key in required if not isinstance(data.get(key), str) or not data[key].strip()]
    if missing:
        raise SkillManifestError(f"{path} missing text fields: {', '.join(missing)}")
    if not ID_PATTERN.fullmatch(data["id"]):
        raise SkillManifestError(f"invalid Skill id: {data['id']}")
    if not isinstance(data.get("capabilities", []), list) or not all(
        isinstance(value, str) and value.strip() for value in data.get("capabilities", [])
    ):
        raise SkillManifestError(f"Skill {data['id']} capabilities must be text list")
    names: set[str] = set()
    for tool in data.get("tools", []):
        if not isinstance(tool, dict) or not isinstance(tool.get("name"), str) or not tool["name"].strip():
            raise SkillManifestError(f"Skill {data['id']} has invalid tool")
        if tool["name"] in names:
            raise SkillManifestError(f"Skill {data['id']} has duplicate tool {tool['name']}")
        names.add(tool["name"])
        if not isinstance(tool.get("description"), str) or not tool["description"].strip():
            raise SkillManifestError(f"tool {tool['name']} needs description")
        if not isinstance(tool.get("parameters", {}), dict):
            raise SkillManifestError(f"tool {tool['name']} parameters must be JSON Schema")
        parameters = tool.get("parameters") or {}
        if parameters.get("type") != "object" or not isinstance(parameters.get("properties"), dict):
            raise SkillManifestError(
                f"tool {tool['name']} parameters must define an object schema with properties"
            )
        required = parameters.get("required", [])
        if not isinstance(required, list) or not all(
            isinstance(value, str) and value in parameters["properties"] for value in required
        ):
            raise SkillManifestError(f"tool {tool['name']} has invalid required parameters")
