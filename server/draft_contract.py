"""Explicit draft constraints and conservative, evidence-aware output clues."""
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class DraftContract:
    article_type: str
    length: str
    forbid_personal: bool
    forbid_dialogue: bool
    forbid_psychology: bool
    allow_hypothetical: bool
    sources: str


def contract_from(requirements: str, strategy: dict) -> DraftContract:
    text = requirements or ''
    forbidden = re.search(r'(?:不|禁止|不得|避免|不能|勿|不要)[^。\n]{0,36}(?:虚构|编造|杜撰|模拟)', text)
    strict = bool(forbidden)
    length = re.findall(r'\d{2,5}\s*[—–\-~～至到]\s*\d{2,5}\s*字', text)
    return DraftContract(str(strategy.get('article_type') or 'unspecified'), length[-1] if length else '',
                         strict and bool(re.search(r'经历|亲历|人物|故事', text)),
                         strict and bool(re.search(r'对话|对白|引语', text)),
                         strict and bool(re.search(r'心理|想法|动机|对话|对白', text)),
                         bool(re.search(r'(?:允许|可以|可用)[^。\n]{0,10}(?:假设|示例|例子)', text))
                         and not bool(re.search(r'(?:不|禁止|不得|避免)[^。\n]{0,12}(?:假设|示例|例子)', text)),
                         '仅用户提供的材料或可核查来源；真实引语逐字保留')


def output_violations(article: str, contract: DraftContract, evidence: str) -> list[dict]:
    findings = []
    patterns = []
    if contract.forbid_psychology:
        patterns.append(('unprovided_psychology', r'[^。！？\n]{0,40}(?:一方|另一方|一个人|另一个人|对方|伴侣|丈夫|妻子)[^。！？\n]{0,16}(?:想说|心里想|心想|听到的却是|觉得自己|认为自己)[^。！？\n]{0,60}[。！？]?'))
    if contract.forbid_dialogue:
        patterns.append(('unprovided_dialogue', r'[^。！？\n]{0,30}(?:一方|另一方|一个人|另一个人|对方|伴侣|丈夫|妻子)[^。！？\n]{0,20}(?:说|问|回答|听到)[：:]?\s*[“「][^”」\n]{1,100}[”」]'))
    if contract.forbid_personal:
        patterns.append(('unprovided_experience', r'[^。！？\n]{0,25}(?:我朋友|我同事|我亲身|我的经历|我曾经遇到)[^。！？\n]{0,70}[。！？]?'))
    for kind, pattern in patterns:
        for match in re.finditer(pattern, article):
            quote = match.group().strip()
            if quote and quote not in evidence and all(x['quote'] != quote for x in findings):
                findings.append({'kind': kind, 'quote': quote})
    return findings[:8]
