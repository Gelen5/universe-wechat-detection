"""Advisory natural-prose gate for Chinese long-form drafts.

This is not an AI detector and must not be used as proof of authorship.
It reports local readability/template-risk signals before a human or
black-box review.  The numbers are comparison aids, not Zhuque internals.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import Counter
from pathlib import Path

try:
    from .check_ai_tone_signals import analyze as analyze_explicit_signals
except ImportError:  # Direct script execution.
    from check_ai_tone_signals import analyze as analyze_explicit_signals


SENTENCE_RE = re.compile(r"[^。！？!?；;]+[。！？!?；;]?")
FORMULA_PATTERNS = {
    "可能的翻案句": re.compile(
        r"(?:不是|并非|不在于|与其说|看似|表面(?:上)?).{0,40}"
        r"(?:而是|在于|不如说|实则|其实)"
    ),
    "对称判断句": re.compile(
        r"(?:不等于|不代表|不能说明).{0,55}"
        r"(?:也不等于|也不代表|更不代表|也不能说明)"
    ),
    "对称代价句": re.compile(
        r".{0,16}有.{0,16}的(?:代价|成本|好处|难处)"
        r"[，,；;].{0,16}有.{0,16}的(?:代价|成本|好处|难处)"
    ),
}
PARAGRAPH_END_JUDGMENT_MARKERS = (
    "所以",
    "这说明",
    "这意味着",
    "这反倒说明",
    "这大概才是",
    "更现实的是",
    "真正",
    "归根结底",
    "说到底",
    "不等于",
    "不代表",
    "从来不是",
)
TERMINAL_CHARS = "。！？!?；;\"”’』」）)"


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text)


def split_sentences(text: str) -> list[str]:
    """Split on terminal punctuation while treating line breaks as boundaries."""
    items: list[str] = []
    for line in re.split(r"[\r\n]+", text):
        items.extend(SENTENCE_RE.findall(line))
    return [item.strip() for item in items if item.strip()]


def paragraph_stats(text: str) -> tuple[list[str], list[int]]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    counts = [len(split_sentences(p)) for p in paragraphs]
    return paragraphs, counts


def coefficient_of_variation(values: list[int]) -> float:
    if len(values) < 2:
        return 0.0
    mean = statistics.mean(values)
    return statistics.pstdev(values) / mean if mean else 0.0


def analyze(text: str, mode: str = "standard") -> dict:
    # Markdown headings are format, not prose sentences.
    prose = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )
    paragraphs, paragraph_sentence_counts = paragraph_stats(prose)
    sentences = split_sentences(prose)
    clean_sentences = [normalize(s) for s in sentences]
    sentence_lengths = [len(s) for s in clean_sentences]
    short_sentences = [s for s in clean_sentences if len(s) <= 8]
    sentence_openings = [s[:5] for s in clean_sentences if len(s) >= 5]
    opening_counts = Counter(sentence_openings)
    repeated_openings = {k: v for k, v in opening_counts.items() if v >= 3}
    explicit_report = analyze_explicit_signals(text, mode=mode)
    explicit_signals = explicit_report["signals"]
    marker_counts = {
        key: value
        for key, value in explicit_report["signal_counts"].items()
        if key
        in {
            "translation_leading_connector",
            "translation_this_means",
            "banned_opener",
        }
    }
    formula_pattern_counts: dict[str, int] = {}
    for name, pattern in FORMULA_PATTERNS.items():
        count = len(pattern.findall(text))
        if count:
            formula_pattern_counts[name] = count
    punctuation_counts = {
        "破折号": text.count("——") + text.count("—"),
        "冒号": text.count("：") + text.count(":"),
    }
    single_sentence_paragraphs = sum(c == 1 for c in paragraph_sentence_counts)
    paragraph_lengths = [len(normalize(p)) for p in paragraphs]
    average_paragraph_chars = (
        statistics.mean(paragraph_lengths) if paragraph_lengths else 0
    )
    punctuationless = [
        s for s in clean_sentences if len(s) >= 12 and s[-1] not in TERMINAL_CHARS
    ]
    complete_sentence_ratio = (
        1 - len(punctuationless) / len(sentences) if sentences else 1.0
    )
    marker_total = sum(marker_counts.values())
    marker_density = (
        marker_total / len(normalize(prose)) * 1000 if normalize(prose) else 0.0
    )
    paragraph_end_judgments: list[str] = []
    for paragraph in paragraphs:
        paragraph_sentences = [normalize(s) for s in split_sentences(paragraph)]
        if not paragraph_sentences:
            continue
        ending = paragraph_sentences[-1]
        has_marker = any(
            marker in ending for marker in PARAGRAPH_END_JUDGMENT_MARKERS
        )
        has_formula = any(
            pattern.search(ending) for pattern in FORMULA_PATTERNS.values()
        )
        if has_marker or has_formula:
            paragraph_end_judgments.append(ending)
    paragraph_end_judgment_ratio = (
        len(paragraph_end_judgments) / len(paragraphs) if paragraphs else 0.0
    )

    warnings: list[str] = []
    if sentences and len(short_sentences) / len(sentences) > 0.30:
        warnings.append("短句比例过高，检查是否把完整句子切碎")
    if (
        paragraphs
        and single_sentence_paragraphs / len(paragraphs) > 0.85
        and average_paragraph_chars < 45
    ):
        warnings.append("短单句段过多，检查是否在表演节奏")
    observations: list[str] = list(explicit_report["observations"])
    if repeated_openings and mode == "deep":
        warnings.append("多个句子使用相同开头，检查是否形成模板排比")
    if len(punctuationless) > 1 or (
        sentences and len(punctuationless) / len(sentences) > 0.05
    ):
        warnings.append("存在较长句子没有句末标点，检查是否真的需要省略")
    if len(sentences) >= 12 and coefficient_of_variation(sentence_lengths) < 0.20:
        observations.append("句长变化较小；只作节奏观察，不单独作为改写理由")
    if len(paragraphs) >= 8 and coefficient_of_variation(paragraph_lengths) < 0.25:
        observations.append("段落长度变化较小；只作节奏观察，不单独作为改写理由")
    if mode in {"standard", "deep"} and formula_pattern_counts.get("对称判断句", 0) >= 2:
        warnings.append("对称判断句连续出现，检查是否在批量制造完整金句")
    if (
        mode in {"standard", "deep"}
        and len(paragraphs) >= 6
        and len(paragraph_end_judgments) >= 3
        and paragraph_end_judgment_ratio >= 0.40
    ):
        warnings.append("较多段落以抽象判断收束，检查是否每段都被解释得过于闭环")
    if explicit_signals:
        warnings.append("命中可定位的白名单复核规则，只修改对应位置并保留其余文字")

    review_items: list[dict[str, str]] = []
    for sentence in clean_sentences:
        reasons: list[str] = []
        if len(sentence) >= 80:
            reasons.append("长句")
        if len(sentence) >= 12 and sentence[-1] not in TERMINAL_CHARS:
            reasons.append("无句末标点")
        if sentence[:5] in repeated_openings and mode == "deep":
            reasons.append("重复开头")
        if mode in {"standard", "deep"} and any(
            pattern.search(sentence) for pattern in FORMULA_PATTERNS.values()
        ):
            reasons.append("公式化判断")
        if mode in {"standard", "deep"} and sentence in paragraph_end_judgments:
            reasons.append("段尾抽象判断")
        if reasons:
            review_items.append({"reason": "+".join(reasons), "text": sentence})
    for signal in explicit_signals:
        review_items.append(
            {
                "reason": f"{signal['rule_id']}:{signal['confidence']}",
                "text": signal["text"],
            }
        )
    review_items = review_items[:12]

    return {
        "chars": len(normalize(text)),
        "mode": mode,
        "paragraphs": len(paragraphs),
        "sentences": len(sentences),
        "average_paragraph_chars": round(average_paragraph_chars, 1),
        "short_sentence_ratio": round(
            len(short_sentences) / len(sentences), 3
        ) if sentences else 0,
        "single_sentence_paragraph_ratio": round(
            single_sentence_paragraphs / len(paragraphs), 3
        ) if paragraphs else 0,
        "complete_sentence_ratio": round(complete_sentence_ratio, 3),
        "sentence_length": {
            "mean": round(statistics.mean(sentence_lengths), 1)
            if sentence_lengths else 0,
            "min": min(sentence_lengths) if sentence_lengths else 0,
            "max": max(sentence_lengths) if sentence_lengths else 0,
            "cv": round(coefficient_of_variation(sentence_lengths), 3),
        },
        "paragraph_length_cv": round(
            coefficient_of_variation(paragraph_lengths), 3
        ),
        "transition_marker_density_per_1000_chars": round(marker_density, 3),
        "paragraph_end_judgment_ratio": round(
            paragraph_end_judgment_ratio, 3
        ),
        "paragraph_end_judgments": paragraph_end_judgments[:12],
        "repeated_sentence_openings": repeated_openings,
        "template_marker_counts": marker_counts,
        "formula_pattern_counts": formula_pattern_counts,
        "punctuation_counts": punctuation_counts,
        "long_sentences_without_terminal_punctuation": len(punctuationless),
        "review_items": review_items,
        "explicit_signals": explicit_signals,
        "observations": observations,
        "warnings": warnings,
        "note": "Advisory only; this report is not an AI-authorship decision.",
    }


def compare(current: dict, baseline: dict) -> dict:
    keys = (
        "chars",
        "paragraphs",
        "sentences",
        "complete_sentence_ratio",
        "short_sentence_ratio",
        "single_sentence_paragraph_ratio",
        "transition_marker_density_per_1000_chars",
        "paragraph_end_judgment_ratio",
    )
    return {
        "baseline": {key: baseline.get(key) for key in keys},
        "delta_current_minus_baseline": {
            key: round(current.get(key, 0) - baseline.get(key, 0), 3)
            for key in keys
        },
        "note": "A lower local-risk signal is not automatically a better article; read both versions.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="检查中文稿件的可读性与模板风险（仅供人工复核）"
    )
    parser.add_argument("path", type=Path)
    parser.add_argument(
        "--compare",
        type=Path,
        help="与另一份稿件做局部指标对比，当前稿件作为 current",
    )
    parser.add_argument(
        "--mode", choices=("minimal", "standard", "deep"), default="standard"
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = analyze(args.path.read_text(encoding="utf-8"), mode=args.mode)
    if args.compare:
        baseline = analyze(args.compare.read_text(encoding="utf-8"), mode=args.mode)
        result["comparison"] = compare(result, baseline)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"字数: {result['chars']}")
        print(f"段落: {result['paragraphs']} | 句子: {result['sentences']}")
        print(f"完整句比例: {result['complete_sentence_ratio']}")
        print(f"短句比例: {result['short_sentence_ratio']}")
        print(f"单句段比例: {result['single_sentence_paragraph_ratio']}")
        print(f"段尾抽象判断比例: {result['paragraph_end_judgment_ratio']}")
        print(f"句长变异系数: {result['sentence_length']['cv']}")
        for warning in result["warnings"]:
            print(f"提示: {warning}")
        if result.get("review_items"):
            print("重点复核句:")
            for item in result["review_items"]:
                print(f"- [{item['reason']}] {item['text']}")
        if not result["warnings"]:
            print("未发现明显的结构性风险；仍需人工朗读和黑盒检测回归。")
        if "comparison" in result:
            print("已输出当前稿与基线稿的指标差异。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
