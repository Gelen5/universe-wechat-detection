#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compare two article versions by editorial issues, not score movement."""

import argparse
import sys
from pathlib import Path

import detector


def issue_map(result):
    issues = {}
    for item in result.get("compliance", []):
        key = "compliance:" + item["line"]
        issues[key] = {
            "severity": "P0" if item.get("severity") == "block" else "P1",
            "title": item["line"],
            "detail": "命中：" + "、".join(item.get("hits", [])),
        }
    for item in result.get("evidence", []):
        key = "evidence:" + item["title"]
        issues[key] = {
            "severity": "P0" if item.get("severity") == "block" else "P1",
            "title": item["title"],
            "detail": item["detail"],
        }
    for surface in ("substantive", "machine"):
        for item in result.get("content_risk", {}).get(surface, []):
            key = "risk:" + surface + ":" + item["signal"]
            issues[key] = {
                "severity": "P0" if item.get("severity") == "block" else "P1",
                "title": item["signal"],
                "detail": item["action"],
            }
    for key, full in detector.DIM_FULL.items():
        ratio = result["scores"][key] / full
        if ratio < 0.5:
            issue_key = "dimension:" + key
            issues[issue_key] = {
                "severity": "P1",
                "title": detector.DIM_NAMES[key] + "偏低",
                "detail": f'{result["scores"][key]}/{full}',
            }
    return issues


def compare_results(before, after):
    old = issue_map(before)
    new = issue_map(after)
    resolved_keys = old.keys() - new.keys()
    remaining_keys = old.keys() & new.keys()
    introduced_keys = new.keys() - old.keys()
    return {
        "resolved": [old[key] for key in sorted(resolved_keys)],
        "remaining": [new[key] for key in sorted(remaining_keys)],
        "introduced": [new[key] for key in sorted(introduced_keys)],
        "before_gate": before["editorial_gate"],
        "after_gate": after["editorial_gate"],
        "before_score": before["scores"]["total"],
        "after_score": after["scores"]["total"],
    }


def format_markdown(comparison):
    lines = ["# 文章修改复核", ""]
    lines.append(
        f'**编辑结论**：{comparison["before_gate"]["label"]} → '
        f'{comparison["after_gate"]["label"]}'
    )
    lines.append(
        f'**结构参考分**：{comparison["before_score"]} → {comparison["after_score"]}'
        "（分数变化不作为问题已解决的证明）"
    )
    sections = (
        ("已解决", "resolved", "✅"),
        ("仍存在", "remaining", "⚠️"),
        ("新出现", "introduced", "🆕"),
    )
    for heading, key, icon in sections:
        lines.extend(["", "## " + heading])
        items = comparison[key]
        if not items:
            lines.append("- 无")
            continue
        for item in items:
            lines.append(f'- {icon} [{item["severity"]}] {item["title"]}：{item["detail"]}')
    return "\n".join(lines)


def _read(path):
    return Path(path).read_text(encoding="utf-8-sig")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="公众号文章修改前后问题复核")
    parser.add_argument("before_title")
    parser.add_argument("before_article")
    parser.add_argument("after_title")
    parser.add_argument("after_article")
    parser.add_argument("--track", default="auto", choices=["auto"] + list(detector.TRACKS.keys()))
    args = parser.parse_args()
    track = None if args.track == "auto" else args.track
    before = detector.detect(args.before_title, _read(args.before_article), track=track)
    after = detector.detect(args.after_title, _read(args.after_article), track=track)
    print(format_markdown(compare_results(before, after)))


if __name__ == "__main__":
    main()
