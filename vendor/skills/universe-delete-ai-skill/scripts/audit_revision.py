"""Run the two-pass local audit for an original and a revised prose draft."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from .check_ai_tone_signals import analyze as analyze_signals
    from .check_natural_prose import analyze as analyze_prose
    from .check_protected_spans import collect
except ImportError:  # Direct script execution.
    from check_ai_tone_signals import analyze as analyze_signals
    from check_natural_prose import analyze as analyze_prose
    from check_protected_spans import collect


def missing_spans(original: str, revision: str) -> dict[str, list[str]]:
    before = collect(original)
    after = collect(revision)
    return {
        category: [value for value in values if value not in after[category]]
        for category, values in before.items()
        if any(value not in after[category] for value in values)
    }


def audit(original: str, revision: str, mode: str) -> dict:
    original_signals = analyze_signals(original, mode=mode)
    revision_signals = analyze_signals(revision, mode=mode)
    return {
        "mode": mode,
        "original": {
            "signals": original_signals["signal_counts"],
            "signal_total": len(original_signals["signals"]),
            "readability": analyze_prose(original, mode=mode),
        },
        "revision": {
            "signals": revision_signals["signal_counts"],
            "signal_total": len(revision_signals["signals"]),
            "readability": analyze_prose(revision, mode=mode),
        },
        "missing_protected_spans": missing_spans(original, revision),
        "note": "Local two-pass audit only; it does not predict or submit to Zhuque.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="对原稿和改稿执行二次本地审计")
    parser.add_argument("original", type=Path)
    parser.add_argument("revision", type=Path)
    parser.add_argument(
        "--mode", choices=("minimal", "standard", "deep"), default="standard"
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = audit(
        args.original.read_text(encoding="utf-8"),
        args.revision.read_text(encoding="utf-8"),
        args.mode,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            f"{args.mode} 二次审计 | 信号 {result['original']['signal_total']}"
            f" -> {result['revision']['signal_total']}"
        )
        if result["missing_protected_spans"]:
            print("需要回读的保护片段:")
            for category, values in result["missing_protected_spans"].items():
                print(f"- {category}: {', '.join(values)}")
        else:
            print("未发现保护片段缺失；仍需人工回读主体、动作、因果和语气。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
