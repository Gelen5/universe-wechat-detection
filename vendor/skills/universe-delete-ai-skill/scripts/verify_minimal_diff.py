"""Verify that minimal-mode edits stay inside explicitly flagged source spans."""

from __future__ import annotations

import argparse
import difflib
import json
from pathlib import Path

try:
    from .check_ai_tone_signals import analyze
except ImportError:  # Direct script execution.
    from check_ai_tone_signals import analyze


def _merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[list[int]] = []
    for start, end in sorted(spans):
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(start, end) for start, end in merged]


def _covered(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    if start == end:
        return any(span_start <= start < span_end for span_start, span_end in spans)
    return any(span_start <= start and end <= span_end for span_start, span_end in spans)


def verify(original: str, revision: str) -> dict:
    report = analyze(original, mode="minimal")
    allowed_spans = _merge_spans(
        [(item["start"], item["end"]) for item in report["signals"]]
    )
    violations: list[dict] = []
    changes: list[dict] = []
    matcher = difflib.SequenceMatcher(a=original, b=revision, autojunk=False)
    for tag, a1, a2, b1, b2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        item = {
            "tag": tag,
            "original_start": a1,
            "original_end": a2,
            "original_text": original[a1:a2],
            "revision_text": revision[b1:b2],
        }
        changes.append(item)
        if not _covered(a1, a2, allowed_spans):
            violations.append(item)
    return {
        "status": "pass" if not violations else "review_required",
        "allowed_spans": allowed_spans,
        "changes": changes,
        "violations": violations,
        "note": "Minimal mode permits edits only inside sentences or lines flagged by explicit rules.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="检查最小改写是否误改未命中文字")
    parser.add_argument("original", type=Path)
    parser.add_argument("revision", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = verify(
        args.original.read_text(encoding="utf-8"),
        args.revision.read_text(encoding="utf-8"),
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"minimal diff: {result['status']}")
        for item in result["violations"]:
            print(f"- 未命中区域发生改动: {item['original_text']!r}")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
