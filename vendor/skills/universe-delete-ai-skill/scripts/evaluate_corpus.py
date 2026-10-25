"""Run local readability and explicit-signal checks over a Markdown corpus."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

try:
    from .check_ai_tone_signals import analyze as analyze_signals
    from .check_natural_prose import analyze as analyze_prose
except ImportError:  # Direct script execution.
    from check_ai_tone_signals import analyze as analyze_signals
    from check_natural_prose import analyze as analyze_prose


def evaluate(directory: Path, mode: str, limit: int | None = None) -> dict:
    files = sorted(directory.rglob("*.md"))
    if limit is not None:
        files = files[:limit]
    documents: list[dict] = []
    signal_counts: Counter[str] = Counter()
    for path in files:
        text = path.read_text(encoding="utf-8")
        prose = analyze_prose(text, mode=mode)
        signals = analyze_signals(text, mode=mode)
        signal_counts.update(signals["signal_counts"])
        documents.append(
            {
                "path": str(path),
                "chars": prose["chars"],
                "complete_sentence_ratio": prose["complete_sentence_ratio"],
                "signals": len(signals["signals"]),
            }
        )
    count = len(documents)
    return {
        "directory": str(directory),
        "mode": mode,
        "documents": count,
        "average_complete_sentence_ratio": round(
            sum(item["complete_sentence_ratio"] for item in documents) / count, 3
        )
        if count
        else 0,
        "documents_below_0_9_complete_sentence_ratio": sum(
            item["complete_sentence_ratio"] < 0.9 for item in documents
        ),
        "signal_counts": dict(signal_counts),
        "items": documents,
        "note": "Local regression only; this does not submit text to Zhuque.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="批量运行本地自然中文与白名单信号回归")
    parser.add_argument("directory", type=Path)
    parser.add_argument(
        "--mode", choices=("minimal", "standard", "deep"), default="standard"
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = evaluate(args.directory, args.mode, args.limit)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            f"文档 {result['documents']} 篇 | 完整句均值 "
            f"{result['average_complete_sentence_ratio']}"
        )
        for rule_id, count in result["signal_counts"].items():
            print(f"- {rule_id}: {count}")
    return 0 if result["documents"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
