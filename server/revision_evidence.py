"""Deterministic edit evidence. These counts are not writing-quality scores."""
import difflib
import hashlib
import re
import unicodedata
from collections import Counter


def revision_evidence(before: str, after: str) -> dict:
    def words(value):
        return ''.join(c for c in value if not c.isspace()
                       and not unicodedata.category(c).startswith('P'))

    matcher = difflib.SequenceMatcher(None, before, after, autojunk=False)
    spans = [op for op in matcher.get_opcodes() if op[0] != 'equal']
    return {
        'before_sha256': hashlib.sha256(before.encode()).hexdigest(),
        'after_sha256': hashlib.sha256(after.encode()).hexdigest(),
        'before_chars': len(before), 'after_chars': len(after),
        'removed_chars': sum(i2 - i1 for _, i1, i2, _, _ in spans),
        'added_chars': sum(j2 - j1 for _, _, _, j1, j2 in spans),
        'text_changed': words(before) != words(after),
        'similarity': round(matcher.ratio(), 4),
        'meaning': '字符差异证据，不代表文章质量或检测器分数',
    }


def orphaned_list_error(before: str, after: str) -> str | None:
    """Catch collapsing an introduced multi-paragraph list but leaving its colon.

    Conservative structural check, not a semantic fidelity guarantee. A rewrite
    may compress the list if it also repairs the introductory paragraph.
    """
    blocks = list(re.finditer(r'\S[^\n]*(?:\n(?!\s*\n)[^\n]+)*', before))
    for index, block in enumerate(blocks[:-1]):
        intro = block.group().rstrip()
        if not intro.endswith(('：', ':')) or after.count(intro) != 1:
            continue
        following = []
        for item in blocks[index + 1:]:
            value = item.group().strip()
            if value.startswith('#') or value.endswith(('。', '！', '？', '.', '!', '?')):
                # A final list entry can end with a full stop.
                if following:
                    following.append(value)
                break
            following.append(value)
        if len(following) < 2:
            continue
        start = after.index(intro) + len(intro)
        tail = after[start:].lstrip()
        first = re.split(r'\n\s*\n', tail, maxsplit=1)[0]
        # If every original entry survives, unchanged lists always pass.
        if all(value in after for value in following):
            continue
        if not first or (first.endswith(('。', '！', '？', '.', '!', '?'))
                         and not any(mark in first for mark in ('；', ';', '\n'))):
            return '列举引导语仍以冒号结尾，但后续多项内容被压成单句；保留各项或连同引导语一起修复'
    return None


def introduced_duplicate_error(before: str, after: str) -> str | None:
    def paragraphs(value):
        return Counter(p.strip() for p in re.split(r'\n\s*\n', value)
                       if len(p.strip()) >= 20 and not p.lstrip().startswith('#'))
    old, new = paragraphs(before), paragraphs(after)
    if any(count > 1 and count > old[paragraph] for paragraph, count in new.items()):
        return '局部改稿新增了完全相同的重复段落；不得把相邻段落复制进替换片段'
    return None
