"""Inventory Easel dependencies and conservatively classify Skill migration work."""
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

import yaml


FIELDS = (
    "skill_name", "category", "SKILL.md", "references", "scripts",
    "requires_openclaw", "requires_shell", "requires_browser", "requires_ffmpeg",
    "requires_network", "requires_llm", "requires_profile", "requires_publish_account",
    "migration_complexity", "status",
)


def has(text: str, pattern: str) -> bool:
    return bool(re.search(pattern, text, re.IGNORECASE))


def inventory(root: Path) -> list[dict[str, str]]:
    skills_root = root / "skills" / "openclaw"
    if not skills_root.is_dir():
        raise FileNotFoundError(skills_root)
    rows = []
    for path in sorted(skills_root.glob("*/SKILL.md")):
        text = path.read_text(encoding="utf-8-sig")
        if not text.startswith("---\n"):
            raise ValueError(f"missing YAML frontmatter: {path}")
        _, frontmatter, body = text.split("---", 2)
        metadata = yaml.safe_load(frontmatter)
        if not isinstance(metadata, dict):
            raise ValueError(f"invalid YAML frontmatter: {path}")
        references = sorted(p.relative_to(path.parent).as_posix() for p in (path.parent / "references").rglob("*") if p.is_file())
        scripts = sorted(p.relative_to(path.parent).as_posix() for p in (path.parent / "scripts").rglob("*") if p.is_file())
        supporting = "\n".join((path.parent / item).read_text(encoding="utf-8", errors="replace")
                               for item in references if item.endswith((".md", ".txt")))
        source = body + "\n" + supporting
        direct_openclaw = has(source, r"\bopenclaw\b|gateway|AGENTS\.md|SOUL\.md|CONTEXT\.md|persona_prefix|MEMORY\.md")
        shell = has(source, r"\b(?:python3?|bash|sh|node|npx|curl|exec)\s+|subprocess|`[^`]*(?:/scripts/|\\scripts\\)")
        browser = has(source, r"playwright|puppeteer|browser|浏览器|扫码")
        ffmpeg = has(source, r"ffmpeg|ffprobe")
        network = has(source, r"https?://|\bAPI\b|接口|联网|搜索|抓取|爬取")
        profile = has(source, r"\bprofile\b|画像|人设")
        publish = has(source, r"发布到|自动发布|publish|账号登录|登录态|access_token")
        llm = has(source, r"模型|AI\s*生成|大模型|LLM|生成文案|写作")
        # A mention of OpenClaw is not enough to prove a runtime call. Flag the
        # precise reference in the matrix and require review before declaring portable.
        explicit_openclaw = has(source, r"\bopenclaw\s+(?:--|gateway|agent|skills|status)|openclaw\.json|gateway[_./ -]|question\.(?:list|answer)")
        if explicit_openclaw:
            status = "OPENCLAW_SPECIFIC"
        elif direct_openclaw or shell or browser or ffmpeg or network or publish:
            status = "ADAPTER_REQUIRED"
        else:
            status = "PORTABLE"
        complexity = "high" if explicit_openclaw or browser or publish else "medium" if status == "ADAPTER_REQUIRED" else "low"
        rows.append({
            "skill_name": path.parent.name,
            "category": str(metadata.get("layer") or metadata.get("category") or "unclassified"),
            "SKILL.md": path.relative_to(root).as_posix(),
            "references": ";".join(references), "scripts": ";".join(scripts),
            "requires_openclaw": str(explicit_openclaw).lower(),
            "requires_shell": str(shell).lower(), "requires_browser": str(browser).lower(),
            "requires_ffmpeg": str(ffmpeg).lower(), "requires_network": str(network).lower(),
            "requires_llm": str(llm).lower(), "requires_profile": str(profile).lower(),
            "requires_publish_account": str(publish).lower(),
            "migration_complexity": complexity, "status": status,
        })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("easel_root", type=Path)
    parser.add_argument("--output", type=Path, default=Path("docs/EASEL_SKILL_COMPATIBILITY.csv"))
    args = parser.parse_args()
    rows = inventory(args.easel_root.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    counts = {status: sum(row["status"] == status for row in rows)
              for status in ("PORTABLE", "ADAPTER_REQUIRED", "OPENCLAW_SPECIFIC", "UNSUPPORTED")}
    print(f"Scanned {len(rows)} Skills: {counts}")


if __name__ == "__main__":
    main()
