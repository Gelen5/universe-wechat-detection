"""Normalize public search results into a review queue.

This helper intentionally stores metadata and a short summary only. It does
not download or archive full copyrighted articles. Feed it JSON or JSONL
results exported from ``opencli weixin search ... -f json`` and review the
output before adding a source to the knowledge base.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def as_records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in ("results", "data", "items", "articles"):
            if isinstance(value.get(key), list):
                return [item for item in value[key] if isinstance(item, dict)]
        return [value]
    return []


def clean_text(value: Any, limit: int = 800) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def normalize(item: dict[str, Any], sector: str, source: str) -> dict[str, Any]:
    title = clean_text(item.get("title") or item.get("name"), 160)
    url = clean_text(item.get("url") or item.get("link"), 500)
    summary = clean_text(item.get("summary") or item.get("description"), 800)
    published = clean_text(item.get("publish_time") or item.get("date"), 80)
    reading = clean_text(
        item.get("read_evidence") or item.get("views") or item.get("reading"), 120
    )
    return {
        "title": title,
        "url": url,
        "sector": sector,
        "published": published,
        "summary": summary,
        "read_evidence": reading,
        "source": source,
        "status": "needs_manual_review",
        "copyright_use": "metadata_and_summary_only",
        "review_questions": [
            "是否能在来源页确认真实人物/事件，而不是营销故事？",
            "10万+是否有原始后台、官方页面或可靠报道支撑？",
            "是否可以只抽取动作链和叙事结构，而不复制原文？",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="把公开搜索结果整理成真实故事素材审阅队列")
    parser.add_argument("input", type=Path, help="JSON/JSONL 搜索结果文件")
    parser.add_argument("output", type=Path, help="输出 JSONL 文件")
    parser.add_argument("--sector", default="未分类")
    parser.add_argument("--source", default="opencli-weixin-search")
    args = parser.parse_args()

    raw = args.input.read_text(encoding="utf-8")
    try:
        records = as_records(json.loads(raw))
    except json.JSONDecodeError:
        records = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.extend(as_records(json.loads(line)))
            except json.JSONDecodeError:
                continue

    normalized = [normalize(item, args.sector, args.source) for item in records]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in normalized),
        encoding="utf-8",
    )
    print(json.dumps({"records": len(normalized), "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
