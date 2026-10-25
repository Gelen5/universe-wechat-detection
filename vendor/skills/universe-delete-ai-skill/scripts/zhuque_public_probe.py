"""Read-only probe for Tencent Zhuque's public model metadata and demos.

This script never submits user text and never attempts to bypass CAPTCHA.
It records only the public examples exposed by the official detector page,
so it is a baseline check rather than a pass/fail detector.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone


BASE_URL = "https://matrix.tencent.com/ai-detect"
LABELS = {"0": "human", "1": "ai", "2": "suspected_ai"}


def fetch_json(path: str) -> dict:
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        headers={"User-Agent": "universe-delete-ai-skill-public-probe/1.0"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def summarize_demo(name: str, item: dict) -> dict:
    raw_result = item.get("a") or "{}"
    try:
        result = json.loads(raw_result) if isinstance(raw_result, str) else raw_result
    except json.JSONDecodeError:
        result = {"status": "invalid_demo_result"}
    text = item.get("q") or ""
    segments = result.get("segment_labels") or []
    return {
        "name": name,
        "chars": len(text.replace("\n", "")),
        "confidence": result.get("confidence"),
        "labels_ratio": result.get("labels_ratio", {}),
        "segment_count": len(segments),
        "segments": [
            {
                "order": segment.get("order"),
                "label": LABELS.get(str(segment.get("label")), segment.get("label")),
                "confidence": segment.get("conf"),
                "chars": len(segment.get("text", "").replace("\n", "")),
            }
            for segment in segments
        ],
    }


def probe() -> dict:
    updated = fetch_json("/model/update_time")
    demos = fetch_json("/aigc_text_demos")
    data = demos.get("data") or {}
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source": BASE_URL,
        "model_update": updated.get("data", {}),
        "demo_count": len(data),
        "demos": [summarize_demo(name, item) for name, item in data.items()],
        "limitations": [
            "read-only public baseline; no user text is uploaded",
            "does not reveal model weights, thresholds, or complete scoring logic",
            "does not prove that a draft will pass the current detector",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="读取朱雀官方公开模型时间和示例（只读，不提交用户稿件）"
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = probe()
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"读取朱雀公开基线失败: {exc}")
        return 2

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"模型更新时间: {result['model_update'].get('updateDate', '未知')}")
    print(f"检查时间: {result['checked_at']}")
    print(f"公开示例数: {result['demo_count']}")
    for demo in result["demos"]:
        print(
            f"- {demo['name']}: {demo['chars']}字, "
            f"confidence={demo['confidence']}, "
            f"labels_ratio={demo['labels_ratio']}, "
            f"segments={demo['segment_count']}"
        )
    print("说明: 这是官方公开样例基线，不是用户稿件的通过判定。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
