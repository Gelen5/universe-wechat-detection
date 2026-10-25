"""Locate explicit Chinese AI-tone cleanup signals in one finished draft.

This is a rule-based editing aid, not an authorship detector.  It reports
source spans that a writer may review.  Minimal mode deliberately restricts
its output to explicit, locally identifiable rules so unmatched text can stay
untouched.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable


SENTENCE_RE = re.compile(r"[^。！？!?；;]+[。！？!?；;]?")
PROSE_SKIP_PREFIXES = ("#", "|", "```", ">", "- ", "* ", "![")

FLIP_PATTERN = re.compile(
    r"(?:不是|并非|不在于|与其说|看似|表面(?:上)?|你以为).{0,45}"
    r"(?:而是|在于|不如说|实则|其实)"
)
SYMMETRIC_JUDGMENT_PATTERN = re.compile(
    r"(?:不等于|不代表|不能说明).{0,55}"
    r"(?:也不等于|也不代表|更不代表|也不能说明)"
)
SYMMETRIC_COST_PATTERN = re.compile(
    r".{0,16}有.{0,16}的(?:代价|成本|好处|难处)"
    r"[，,；;].{0,16}有.{0,16}的(?:代价|成本|好处|难处)"
)
PROMPT_COLON_PATTERN = re.compile(
    r"(?:一句话(?:总结|说|概括)|简单说|说白了|总结|小结|结论|"
    r"核心(?:是|在于|观点)?|关键(?:是|在于)?|重点(?:是)?|"
    r"原因(?:如下|有|在于)?|问题(?:是|在于)?|答案(?:是)?|"
    r"本质(?:是|上)?|定义(?:是)?|具体(?:来说|如下|包括)?|"
    r"换句话说|也就是说|我的(?:观点|判断|结论)|建议(?:是)?)[：:]"
)
IDEALIZED_ROLE_PATTERN = re.compile(
    r"(?:像|如同|好比|相当于)\s*(?:一个|一位)\s*"
    r"(?:永不[^，。]{0,8}|智慧的|全能的|贴身的|随叫随到的)?"
    r"(?:导师|秘书|助手|顾问|管家|审查员|实习生)"
)
NOMINALIZED_ACTION_PATTERN = re.compile(
    r"(?:完成|实现|进行|开展)了?(?:对)?[^，。\n]{0,12}的"
    r"(?:优化|提升|调整|分析|改造|升级)"
)
LONG_PREMODIFIER_PATTERN = re.compile(
    r"(?:一个|一种|一套|这种|这个)[^，。、；：！？\n]{15,}的[一-鿿]{2,6}"
)
WHEN_FRONT_PATTERN = re.compile(r"^当[^，。\n]{2,24}(?<!的时候)时，")
TOPIC_SHELL_PATTERN = re.compile(
    r"^(?:对于[^，。\n]{2,18}来说|对[^，。\n]{2,18}而言|"
    r"就[^，。\n]{2,18}而言|关于[^，。\n]{2,15}[，,]|"
    r"在[^，。\n]{2,15}方面[，,])"
)
LEADING_CONNECTOR_PATTERN = re.compile(
    r"^(?:然而|因此|此外|与此同时|换言之|总而言之)[，、,]"
)
THIS_MEANS_PATTERN = re.compile(r"^(?:这意味着|这表明|这说明|换句话说)")
BANNED_OPENER_PATTERN = re.compile(r"^(?:说白了|说穿了|先说结论)[，、,:：]?")
COMMENT_START_PATTERN = re.compile(
    r"^(?:听起来|看起来|看上去|听上去|值得注意的是|不难看出|"
    r"细看|再看|回过头看|问题在于|原因在于|结果是|有意思的是|"
    r"更重要的是|关键在于|真正的)"
)
ANAPHOR_START_PATTERN = re.compile(
    r"^(?:这|那|其|此|上面|前面|刚才|以上|该|它|他|她|同样|类似|"
    r"相比|反过来|但|不过|所以|于是|而|另外|除此|与此)"
)
ORDERED_HEADING_PATTERN = re.compile(
    r"^\s*(?:#{1,6}\s+|\*\*\s*)"
    r"(?:[一二三四五六七八九十]+[、，.]|第[一二三四五六七八九十]+[章节步、，.])"
)
LIST_LINE_PATTERN = re.compile(
    r"^\s*(?:[-*+]\s+|\d+[.)、]\s*|[一二三四五六七八九十]+[、，.]\s*)"
)
DENSE_ENUMERATION_EXEMPT_PATTERN = re.compile(
    r"法律|法规|规定|条例|条款|法条|名单|参数|配置项|财务科目"
)
REVELATION_DASH_PATTERN = re.compile(
    r"(?:答案|核心|关键|结论|原因|本质|在于|就是|只有|意味着|找到|选择)"
    r"[^。！？]{0,24}——"
)
PERFORMED_INSIGHT_PATTERN = re.compile(
    r"(?:真正值得(?:注意|看的|说的是)|有意思的是|你可能(?:不知道|没想过)|"
    r"这才是(?:重点|关键)|值得一提的是)"
)
INFO_MERCIAL_HOOK_PATTERN = re.compile(
    r"^(?:关键是|问题来了|重点来了|真正的问题是|你知道吗)[：:？?]?$"
)
SOCIAL_CTA_CLOSER_PATTERN = re.compile(
    r"(?:欢迎留言|记得收藏|建议收藏|别忘了收藏|关注(?:我|我们)?(?:并)?回复|"
    r"你会感谢我|以后会用得上|转发给(?:你|身边)的)"
)
RECAP_FLATTERY_PATTERN = re.compile(
    r"(?:这段话|这个例子|这个故事|这句话).{0,12}"
    r"(?:说得|讲得|总结得).{0,8}(?:很|非常)?(?:好|准确|到位|清楚)"
)
STACKED_NEGATION_PATTERN = re.compile(
    r"(?:不是|并非|不在于|没有)\s*[^。！？!?]{0,24}"
    r"(?:不是|并非|不在于|没有)\s*[^。！？!?]{0,24}"
    r"(?:不是|并非|不在于|没有)"
)
HEDGE_STACK_PATTERN = re.compile(
    r"(?:可能|也许|或许|大概|未必|似乎).{0,18}"
    r"(?:可能|也许|或许|大概|未必|似乎)"
)
SAME_OPENER_PATTERN = re.compile(r"^(.{2,6})，")
AI_PLACEHOLDER_PATTERN = re.compile(
    r"(?:\[(?:待填写|填写|插入|补充|来源|姓名|标题|日期|TODO|TBD)[^\]\n]{0,50}\]"
    r"|(?:19|20)\d{2}-XX-XX|<!--\s*(?:TODO|补充|插入|填写)[^>]{0,80}-->)",
    re.IGNORECASE,
)
AI_CITATION_MARKUP_PATTERN = re.compile(
    r"(?:citeturn\d+(?:search|news|navigation)\d+|"
    r"contentReference\s*\[oaicite:[^\]]+\]|oai_citation|"
    r"\[attached_file:\d+\]|grok_card)",
    re.IGNORECASE,
)
AI_UTM_SOURCE_PATTERN = re.compile(
    r"[?&](?:utm_source|referrer)=(?:chatgpt|openai|copilot|claude|"
    r"grok|gemini|perplexity)(?:\.com|\.ai)?\b",
    re.IGNORECASE,
)
SPEECH_PATTERN = re.compile(r"说|问|回答|喊|写道|表示|吐槽")
PARAGRAPH_END_MARKERS = (
    "所以",
    "这说明",
    "这意味着",
    "这反倒说明",
    "这大概才是",
    "更现实的是",
    "归根结底",
    "说到底",
    "不等于",
    "不代表",
    "从来不是",
)

RULE_META = {
    "flip_rhetoric": ("medium", "直接判断是否比先立误解再翻案更准确", False),
    "dense_enumeration": ("medium", "三项以上顿号罗列，确认是否确有完整列举需要", False),
    "adjacent_isomorphic_sentences": ("medium", "相邻句骨架近似，确认是否像批量填句", False),
    "revelation_dash": ("medium", "破折号用于普通判断或揭晓，按原作者标点习惯复核", False),
    "performed_insight": ("medium", "洞察提示语可能只是在宣布接下来要说重点", False),
    "infomercial_hook": ("medium", "单独的悬念提示语没有提供信息，确认是否应直接陈述", False),
    "social_cta_closer": ("medium", "社交诱导式收尾可能替代了具体结论", False),
    "recap_flattery": ("medium", "复述并夸赞前文，确认是否增加了新信息", False),
    "stacked_negation": ("medium", "连续否定后揭晓容易形成模板化倒装", False),
    "hedge_stack": ("medium", "多个不确定词叠加，保留有证据的限定即可", False),
    "same_opener_run": ("medium", "连续句子使用相同句首，确认是否形成排比模板", False),
    "ai_placeholder": ("high", "未填占位符属于发布前硬问题，应补充真实内容或删除", True),
    "ai_citation_markup": ("high", "检测到模型内部引用残留，应删除或替换为真实来源", True),
    "ai_utm_source": ("high", "链接带有 AI 工具追踪参数，只删除追踪参数并保留有效链接", True),
    "prompt_colon": ("high", "提示语本身可能空转，删除提示语或改用正常句子", True),
    "empty_list_intro": ("high", "这一行只宣布下方有列表，没有提供内容", True),
    "ordered_headings": ("high", "连续编号小标题可能把说明文字挤到次要位置", True),
    "idealized_role_metaphor": ("medium", "理想化职业喻体可能只是在重复功能", False),
    "nominalized_action": ("medium", "恢复原文已有动作，避免用抽象名词盖住具体行为", False),
    "banned_opener": ("high", "删掉空转起手式，直接给出原判断", True),
    "translation_long_premodifier": ("medium", "前置定语过长，必要时在原段内拆开", False),
    "translation_when_front": ("medium", "句首时间从句过长，确认是否需要保留时点外壳", False),
    "translation_topic_shell": ("medium", "话题外壳可能可以改成直接主语", False),
    "translation_leading_connector": ("medium", "句首连接词只在确需路标时保留", False),
    "translation_this_means": ("medium", "确认是否只是复述上一句", False),
    "paragraph_zero_subject_comment": ("medium", "段首评论缺少回指对象，补回指或点明对象", False),
    "symmetric_judgment": ("medium", "连续对称判断容易形成成套金句", False),
    "symmetric_cost": ("medium", "对称代价句需要材料支撑，不做同义对仗", False),
    "paragraph_overclosure": ("medium", "较多段落以抽象判断收束，检查是否过度闭环", False),
}


def _is_prose_line(line: str) -> bool:
    stripped = line.lstrip()
    return bool(stripped) and not stripped.startswith(PROSE_SKIP_PREFIXES)


def sentence_records(text: str) -> list[dict]:
    records: list[dict] = []
    offset = 0
    paragraph = -1
    in_paragraph = False
    for line_number, line_with_end in enumerate(text.splitlines(keepends=True), 1):
        line = line_with_end.rstrip("\r\n")
        if not line.strip():
            in_paragraph = False
            offset += len(line_with_end)
            continue
        if _is_prose_line(line):
            if not in_paragraph:
                paragraph += 1
                in_paragraph = True
            for match in SENTENCE_RE.finditer(line):
                raw = match.group(0)
                stripped = raw.strip()
                if not stripped:
                    continue
                left = len(raw) - len(raw.lstrip())
                start = offset + match.start() + left
                records.append(
                    {
                        "text": stripped,
                        "start": start,
                        "end": start + len(stripped),
                        "line": line_number,
                        "paragraph": paragraph + 1,
                    }
                )
        else:
            in_paragraph = False
        offset += len(line_with_end)
    return records


def _signal(rule_id: str, record: dict, *, text: str | None = None) -> dict:
    confidence, reason, auto_fix = RULE_META[rule_id]
    return {
        "rule_id": rule_id,
        "confidence": confidence,
        "location": f"第{record['paragraph']}段第{record['line']}行",
        "text": text if text is not None else record["text"],
        "start": record["start"],
        "end": record["end"],
        "reason": reason,
        "auto_fix_allowed": auto_fix,
    }


def _signature(sentence: str) -> tuple[int, bool, bool, int]:
    compact = re.sub(r"\s+", "", sentence)
    return (
        compact.count("，"),
        "：" in compact,
        "（" in compact or "(" in compact,
        len(compact) // 15,
    )


def _line_offsets(text: str) -> Iterable[tuple[int, int, str]]:
    offset = 0
    for line_number, line_with_end in enumerate(text.splitlines(keepends=True), 1):
        line = line_with_end.rstrip("\r\n")
        yield line_number, offset, line
        offset += len(line_with_end)


def analyze(text: str, mode: str = "standard") -> dict:
    if mode not in {"minimal", "standard", "deep"}:
        raise ValueError(f"unknown mode: {mode}")

    records = sentence_records(text)
    signals: list[dict] = []

    for record in records:
        sentence = re.sub(r"\s+", "", record["text"])
        checks = (
            ("flip_rhetoric", FLIP_PATTERN),
            ("dense_enumeration", re.compile(r"(?:[^、，。]{1,18}、){2,}")),
            ("prompt_colon", PROMPT_COLON_PATTERN),
            ("idealized_role_metaphor", IDEALIZED_ROLE_PATTERN),
            ("nominalized_action", NOMINALIZED_ACTION_PATTERN),
            ("banned_opener", BANNED_OPENER_PATTERN),
            ("translation_long_premodifier", LONG_PREMODIFIER_PATTERN),
            ("translation_when_front", WHEN_FRONT_PATTERN),
            ("translation_topic_shell", TOPIC_SHELL_PATTERN),
            ("translation_leading_connector", LEADING_CONNECTOR_PATTERN),
            ("translation_this_means", THIS_MEANS_PATTERN),
        )
        for rule_id, pattern in checks:
            if pattern.search(sentence):
                if (
                    rule_id == "dense_enumeration"
                    and DENSE_ENUMERATION_EXEMPT_PATTERN.search(sentence)
                ):
                    continue
                signals.append(_signal(rule_id, record))
        if REVELATION_DASH_PATTERN.search(sentence):
            signals.append(_signal("revelation_dash", record))
        for rule_id, pattern in (
            ("performed_insight", PERFORMED_INSIGHT_PATTERN),
            ("infomercial_hook", INFO_MERCIAL_HOOK_PATTERN),
            ("social_cta_closer", SOCIAL_CTA_CLOSER_PATTERN),
            ("recap_flattery", RECAP_FLATTERY_PATTERN),
            ("stacked_negation", STACKED_NEGATION_PATTERN),
            ("hedge_stack", HEDGE_STACK_PATTERN),
        ):
            if pattern.search(sentence):
                signals.append(_signal(rule_id, record))
        if mode in {"standard", "deep"}:
            if SYMMETRIC_JUDGMENT_PATTERN.search(sentence):
                signals.append(_signal("symmetric_judgment", record))
            if SYMMETRIC_COST_PATTERN.search(sentence):
                signals.append(_signal("symmetric_cost", record))

    by_paragraph: dict[int, list[dict]] = defaultdict(list)
    for record in records:
        by_paragraph[record["paragraph"]].append(record)

    for paragraph, items in by_paragraph.items():
        opener_counts = Counter(
            match.group(1) for item in items
            if (match := SAME_OPENER_PATTERN.search(item["text"]))
        )
        if any(count >= 3 for count in opener_counts.values()):
            matching = [
                item for item in items
                if (match := SAME_OPENER_PATTERN.search(item["text"]))
                and opener_counts[match.group(1)] >= 3
            ]
            combined = dict(matching[0])
            combined["end"] = matching[-1]["end"]
            combined["text"] = " | ".join(item["text"] for item in matching)
            signals.append(_signal("same_opener_run", combined))
        for first, second in zip(items, items[1:]):
            if (
                len(first["text"]) >= 12
                and len(second["text"]) >= 12
                and _signature(first["text"]) == _signature(second["text"])
                and _signature(first["text"])[0] >= 1
                and not SPEECH_PATTERN.search(first["text"] + second["text"])
                and difflib.SequenceMatcher(
                    None, first["text"], second["text"], autojunk=False
                ).ratio()
                >= 0.35
            ):
                combined = dict(first)
                combined["end"] = second["end"]
                combined["text"] = f"{first['text']} {second['text']}"
                signals.append(_signal("adjacent_isomorphic_sentences", combined))

        first = items[0]
        compact = re.sub(r"\s+", "", first["text"])
        if (
            paragraph > 1
            and COMMENT_START_PATTERN.search(compact)
            and not ANAPHOR_START_PATTERN.search(compact)
        ):
            signals.append(_signal("paragraph_zero_subject_comment", first))

    lines = list(_line_offsets(text))
    artifact_patterns = (
        ("ai_placeholder", AI_PLACEHOLDER_PATTERN),
        ("ai_citation_markup", AI_CITATION_MARKUP_PATTERN),
        ("ai_utm_source", AI_UTM_SOURCE_PATTERN),
    )
    for line_number, offset, line in lines:
        for rule_id, pattern in artifact_patterns:
            for match in pattern.finditer(line):
                record = {
                    "text": match.group(),
                    "start": offset + match.start(),
                    "end": offset + match.end(),
                    "line": line_number,
                    "paragraph": line_number,
                }
                signals.append(_signal(rule_id, record))
    ordinal_lines = [
        (number, offset, line)
        for number, offset, line in lines
        if ORDERED_HEADING_PATTERN.search(line)
    ]
    if len(ordinal_lines) >= 3:
        for line_number, offset, line in ordinal_lines:
            record = {
                "text": line.strip(),
                "start": offset,
                "end": offset + len(line),
                "line": line_number,
                "paragraph": line_number,
            }
            signals.append(_signal("ordered_headings", record))

    for index, (line_number, offset, line) in enumerate(lines):
        if not line.rstrip().endswith(("：", ":")):
            continue
        next_line = ""
        for _, _, candidate in lines[index + 1 :]:
            if candidate.strip():
                next_line = candidate
                break
        if next_line and LIST_LINE_PATTERN.search(next_line):
            record = {
                "text": line.strip(),
                "start": offset,
                "end": offset + len(line),
                "line": line_number,
                "paragraph": line_number,
            }
            signals.append(_signal("empty_list_intro", record))

    observations: list[str] = []
    if records:
        lengths = [len(re.sub(r"\s+", "", r["text"])) for r in records]
        observations.append(
            f"句长范围 {min(lengths)}-{max(lengths)} 字；只作节奏观察，不作为改写理由"
        )

    if mode == "deep" and len(by_paragraph) >= 6:
        endings: list[dict] = []
        for items in by_paragraph.values():
            ending = items[-1]
            compact = re.sub(r"\s+", "", ending["text"])
            if any(marker in compact for marker in PARAGRAPH_END_MARKERS):
                endings.append(ending)
        ratio = len(endings) / len(by_paragraph)
        if len(endings) >= 3 and ratio >= 0.40:
            start = endings[0]
            end = endings[-1]
            combined = dict(start)
            combined["end"] = end["end"]
            combined["text"] = " | ".join(item["text"] for item in endings[:6])
            signals.append(_signal("paragraph_overclosure", combined))
        observations.append(f"段尾抽象判断观察比例 {ratio:.3f}")

    # Keep one signal per rule and exact source span.
    deduped: list[dict] = []
    seen: set[tuple[str, int, int]] = set()
    for signal in sorted(signals, key=lambda item: (item["start"], item["rule_id"])):
        key = (signal["rule_id"], signal["start"], signal["end"])
        if key not in seen:
            seen.add(key)
            deduped.append(signal)

    # Historical patterns remain advisory. No signal authorizes an automatic
    # rewrite, and quoted/fenced content must not be mistaken for prose.
    protected = [(m.start(), m.end()) for m in re.finditer(
        r'(?ms)^\s*(`{3,}|~{3,})[^\n]*\n.*?^\s*\1\s*$|`[^`\n]+`|“[^”]*”|「[^」]*」', text)]
    deduped = [item for item in deduped if not any(
        item['start'] < end and item['end'] > start for start, end in protected)]
    for item in deduped:
        item['auto_fix_allowed'] = False
        item['evidence_level'] = 'experimental_editorial_candidate'
    counts = Counter(item["rule_id"] for item in deduped)
    return {
        "mode": mode,
        "chars": len(re.sub(r"\s+", "", text)),
        "sentences": len(records),
        "signal_counts": dict(counts),
        "signals": deduped,
        "observations": observations,
        "note": "Advisory only; explicit signals are editing locations, not proof of AI authorship.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="定位中文成稿中的白名单式去AI味复核信号")
    parser.add_argument("path", type=Path)
    parser.add_argument(
        "--mode", choices=("minimal", "standard", "deep"), default="standard"
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = analyze(args.path.read_text(encoding="utf-8"), mode=args.mode)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"模式: {result['mode']} | 句子: {result['sentences']}")
        for signal in result["signals"]:
            print(
                f"- [{signal['confidence']}] {signal['rule_id']} "
                f"{signal['location']}: {signal['text']}"
            )
        if not result["signals"]:
            print("未命中白名单清理规则；不要仅凭主观AI感修改其他文字。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
