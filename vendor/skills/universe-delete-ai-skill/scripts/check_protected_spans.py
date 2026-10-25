"""保真回读：检查改稿是否意外丢失原稿中的关键事实片段。

This is a preservation check, not an AI detector. It deliberately reports
possible changes for human review instead of trying to decide whether a
rewrite is good. Numbers, dates, URLs, code spans, and quoted text are
high-value spans; punctuation around them may legitimately change.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


PATTERNS = {
    "number_or_date": re.compile(
        r"(?<![A-Za-z0-9_])(?:\d+(?:\.\d+)?(?:%|元|块|岁|年|月|日|分钟|小时|份|次)?|"
        r"\d{1,4}[年/月日-]\d{1,2}(?:[月日-]\d{1,2})?)(?![A-Za-z0-9_])"
    ),
    "url": re.compile(r"https?://[^\s)）>]+"),
    "code_span": re.compile(r"`[^`\n]+`"),
    "quoted_text": re.compile(r"[“‘「『][^”’」』\n]{1,120}[”’」』]"),
    "qualifier": re.compile(
        r"可能|通常|据说|大概|往往|有时|未必|不一定|约|接近|至少|最多|"
        r"仅仅|仅|只是|只|尚未|并非"
    ),
    "named_entity_hint": re.compile(
        r"[一-鿿A-Za-z0-9·_-]{2,24}(?:公司|集团|大学|学院|研究院|"
        r"委员会|法院|政府|银行|医院|出版社|平台|实验室|App|Skill)"
    ),
}


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def collect(text: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for name, pattern in PATTERNS.items():
        values = []
        for match in pattern.findall(text):
            value = normalize_space(match)
            if value and value not in values:
                values.append(value)
        result[name] = values
    return result


def check_manifest(revision: str, manifest_path: Path | None) -> dict:
    if manifest_path is None:
        return {"required_missing": {}, "forbidden_found": []}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required_missing: dict[str, list[str]] = {}
    for category, values in manifest.get("required", {}).items():
        missing = [value for value in values if value not in revision]
        if missing:
            required_missing[category] = missing
    forbidden_found = [
        value for value in manifest.get("forbidden_additions", []) if value in revision
    ]
    return {
        "required_missing": required_missing,
        "forbidden_found": forbidden_found,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="检查原稿与改稿的关键事实片段是否保留")
    parser.add_argument("original", type=Path)
    parser.add_argument("revision", type=Path)
    parser.add_argument(
        "--manifest",
        type=Path,
        help="可选事实账 JSON，包含 required 分类和 forbidden_additions 列表",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    original = collect(args.original.read_text(encoding="utf-8"))
    revision = collect(args.revision.read_text(encoding="utf-8"))
    missing = {
        name: [value for value in values if value not in revision.get(name, [])]
        for name, values in original.items()
    }
    missing = {name: values for name, values in missing.items() if values}
    manifest_check = check_manifest(
        args.revision.read_text(encoding="utf-8"), args.manifest
    )
    needs_review = bool(
        missing
        or manifest_check["required_missing"]
        or manifest_check["forbidden_found"]
    )
    result = {
        "original": str(args.original),
        "revision": str(args.revision),
        "original_spans": original,
        "revision_spans": revision,
        "missing_spans": missing,
        "manifest": str(args.manifest) if args.manifest else None,
        "manifest_check": manifest_check,
        "status": "review_required" if needs_review else "no_missing_spans_found",
        "note": "缺失片段或事实账命中只代表需要人工回读，仍需核对主体、动作、因果和判断强度。",
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"保真回读: {result['status']}")
        for name, values in missing.items():
            print(f"- {name}: {', '.join(values)}")
        for name, values in manifest_check["required_missing"].items():
            print(f"- manifest {name}: {', '.join(values)}")
        if manifest_check["forbidden_found"]:
            print(f"- forbidden additions: {', '.join(manifest_check['forbidden_found'])}")
        if not missing:
            print("未发现数字、链接、代码片段或引号内容缺失；仍需人工核对主体和语义关系。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
