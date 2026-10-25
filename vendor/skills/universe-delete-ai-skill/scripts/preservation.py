"""Conservative, deterministic invariants; NOT an NLP semantic proof."""
from __future__ import annotations

import difflib
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

MAX_CHARS = 50000  # Client safety cap, not a Tencent service limit.
DIMENSIONS = ('theme', 'claims', 'facts', 'entities', 'causality', 'time_order',
              'stance', 'quotes', 'negation', 'readability', 'naturalness')
BUDGETS = {
    'minimal': {'chars': .15, 'sentences': .35, 'paragraphs': .40},
    'standard': {'chars': .35, 'sentences': .65, 'paragraphs': .75},
    'deep': {'chars': 1.0, 'sentences': 1.0, 'paragraphs': 1.0},
}
PATTERNS = {
    'number': r'(?:[$￥¥€£]\s*)?\d[\d,]*(?:\.\d+)?(?:[-/]\d{1,2}){0,2}(?:年\d{1,2}月(?:\d{1,2}日)?)?(?:%|％|万|亿|千|元|美元|年|月|日|岁|分钟|小时|份|次)?',
    'han_number': r'[零〇一二三四五六七八九十百千万亿两]+(?:年|月|日|元|美元|岁|个|人|份|次|小时|分钟)',
    'time': r'\d{1,2}:\d{2}(?::\d{2})?',
    'url': r'https?://[^\s<>“”"）)\]，。；！？]+',
    'quote': r'“[^”]*”|‘[^’]*’|「[^」]*」|『[^』]*』|"[^"\n]*"',
    'code': r'(?ms)^\s*(`{3,}|~{3,})[^\n]*\n.*?^\s*\1\s*$|`[^`\n]+`',
    'negation_qualifier': r'不一定|不等于|不代表|不能|不敢|并非|没有|尚未|未必|不|没|未|可能|大概|部分|多数|全部|一定|至少|最多|通常|据说|也许|或许|似乎|仅仅|仅|只是|约|接近',
    'markdown_link': r'!?\[[^\]\n]*\]\([^\n]*?\)',
    'blockquote': r'(?m)^\s*>[^\n]*',
}


def digest(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def read(path: Path) -> str:
    # Preserve CRLF, whitespace and BOM: offsets refer to exact input code points.
    with path.open(encoding='utf-8', newline='') as stream:
        return stream.read()


def validate_text(text: str) -> None:
    if not isinstance(text, str) or not text.strip():
        raise ValueError('empty_text')
    if len(text) > MAX_CHARS:
        raise ValueError('client_text_limit')


def spans(text: str, entities: list[str]) -> list[dict]:
    result = []
    patterns = dict(PATTERNS)
    for entity in entities:
        if not isinstance(entity, str) or not entity or entity not in text:
            raise ValueError('entity_not_in_original')
        for match in re.finditer(re.escape(entity), text):
            result.append({'kind': 'entity', 'start': match.start(), 'end': match.end(), 'text': match.group()})
    for kind, pattern in patterns.items():
        for match in re.finditer(pattern, text):
            result.append({'kind': kind, 'start': match.start(), 'end': match.end(), 'text': match.group()})
    return sorted(result, key=lambda x: (x['start'], x['end'], x['kind']))


def build_manifest(original: str, entities: list[str] | None = None) -> dict:
    validate_text(original)
    entities = sorted(set(entities or []))
    return {'schema_version': 1, 'original_sha256': digest(original),
            'chars': len(original), 'entities': entities, 'protected_spans': spans(original, entities),
            'entity_review_required': True,
            'note': 'Entity list must be completed by the editor. Regex is not named-entity recognition.'}


def units(text: str, kind: str) -> list[tuple[int, int]]:
    pattern = r'[^。！？!?\n]+[。！？!?]?' if kind == 'sentences' else r'\S(?:.*?\S)?(?=\r?\n[ \t]*\r?\n|\Z)'
    return [(m.start(), m.end()) for m in re.finditer(pattern, text, re.S)]


def diff(original: str, revision: str) -> dict:
    validate_text(original)
    validate_text(revision)
    # Large repetitive prose can make exact matching quadratic. The heuristic is
    # conservative and exposed; ratios are diff estimates, not Levenshtein distance.
    heuristic = max(len(original), len(revision)) > 5000
    matcher = difflib.SequenceMatcher(None, original, revision, autojunk=heuristic)
    changes = [{'tag': tag, 'start': a, 'end': b, 'revision_start': c, 'revision_end': d}
               for tag, a, b, c, d in matcher.get_opcodes() if tag != 'equal']
    ratios = {'chars': min(1., sum(max(x['end'] - x['start'], x['revision_end'] - x['revision_start'])
                                 for x in changes) / max(len(original), len(revision)))}
    counts = {}
    for kind in ('sentences', 'paragraphs'):
        before, after = units(original, kind), units(revision, kind)
        def touched(items, start, end):
            return sum(any((x[start] < b and x[end] > a) or
                           (x[start] == x[end] and a <= x[start] <= b)
                           for x in changes) for a, b in items)
        n = max(touched(before, 'start', 'end'), touched(after, 'revision_start', 'revision_end'))
        ratios[kind] = min(1., n / max(1, len(before), len(after)))
        counts[kind] = {'original': len(before), 'revision': len(after), 'changed': n}
    return {'ratios': ratios, 'counts': counts, 'changes': changes, 'heuristic_alignment': heuristic}


def structure(text: str) -> list[str]:
    tokens, fence = [], None
    for line in text.splitlines():
        stripped = line.lstrip()
        match = re.match(r'(`{3,}|~{3,})', stripped)
        if match:
            token = match.group()
            if fence is None:
                fence = token
                tokens.append('fence:' + token)
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
                tokens.append('fence_end')
            continue
        if fence:
            continue
        for name, pattern in [('heading', r'#{1,6}\s+.*'), ('list', r'(?:[-*+] |\d+[.)] ).*'),
                              ('quote', r'>.*'), ('table', r'\|.*')]:
            if re.match(pattern, stripped):
                # Lock headings, tables and list content by default, not merely count.
                tokens.append(name + ':' + line)
                break
    if fence:
        tokens.append('unclosed_fence')
    return tokens


def review_template(original: str, revision: str, manifest: dict, plan: dict) -> dict:
    changes = diff(original, revision)['changes']
    return {'schema_version': 1, 'original_sha256': digest(original), 'revision_sha256': digest(revision),
            'manifest_sha256': digest(json.dumps(manifest, ensure_ascii=False, sort_keys=True)),
            'plan_sha256': digest(json.dumps(plan, ensure_ascii=False, sort_keys=True)),
            'reviewer': '', 'reviewer_type': 'llm', 'reviewed_at': '', 'entities_complete': False,
            'dimensions': {name: {'status': 'REVIEW_REQUIRED', 'evidence': ''} for name in DIMENSIONS},
            'change_reviews': [{'index': i, 'status': 'REVIEW_REQUIRED',
                               'original': original[x['start']:x['end']],
                               'revision': revision[x['revision_start']:x['revision_end']], 'reason': ''}
                              for i, x in enumerate(changes)]}


def apply_plan(base: str, plan: dict) -> str:
    if plan.get('base_sha256') != digest(base):
        raise ValueError('stale_plan')
    edits = plan.get('edits')
    if not isinstance(edits, list) or not isinstance(plan.get('change_type'), str) or not plan['change_type'].strip():
        raise ValueError('invalid_plan')
    end = -1
    for edit in sorted(edits, key=lambda x: x.get('start', -1)):
        a, b = edit.get('start'), edit.get('end')
        if type(a) is not int or type(b) is not int or not 0 <= a <= b <= len(base) or a <= end:
            raise ValueError('invalid_or_overlapping_edit')
        if edit.get('original') != base[a:b] or not edit.get('reason', '').strip() or not isinstance(edit.get('replacement'), str):
            raise ValueError('invalid_edit_evidence')
        end = b - 1 if a < b else b
    for edit in sorted(edits, key=lambda x: x['start'], reverse=True):
        base = base[:edit['start']] + edit['replacement'] + base[edit['end']:]
    validate_text(base)
    return base


def gate(original: str, revision: str, manifest: dict, plan: dict, review: dict | None,
         mode: str = 'minimal', base: str | None = None) -> dict:
    errors, pending = [], []
    base = original if base is None else base
    try:
        report = diff(original, revision)
        if mode not in BUDGETS:
            raise ValueError('invalid_mode')
        if mode != 'minimal' and not plan.get('escalation_reason', '').strip():
            errors.append('mode_escalation_unjustified')
        expected = build_manifest(original, manifest.get('entities', []))
        if manifest != expected:
            errors.append('stale_or_tampered_manifest')
        if apply_plan(base, plan) != revision:
            errors.append('revision_outside_plan')
        before = [(x['kind'], x['text']) for x in expected['protected_spans']]
        after = [(x['kind'], x['text']) for x in spans(revision, manifest.get('entities', []))]
        if Counter(before) != Counter(after):
            errors.append('protected_span_added_removed_or_changed')
        elif before != after:
            errors.append('protected_span_order_changed')
        # No inline insertion/deletion inside a protected occurrence, even if the
        # same token count elsewhere disguises the change.
        for x in report['changes']:
            if any((x['start'] < p['end'] and x['end'] > p['start']) or
                   (x['start'] == x['end'] and p['start'] < x['start'] < p['end'])
                   for p in expected['protected_spans']):
                errors.append('protected_occurrence_touched')
                break
        if structure(original) != structure(revision):
            errors.append('markdown_structure_changed')
        if mode == 'minimal' and report['counts']['paragraphs']['original'] != report['counts']['paragraphs']['revision']:
            errors.append('minimal_paragraph_count_changed')
        for name, threshold in BUDGETS[mode].items():
            if report['ratios'][name] > threshold:
                errors.append('change_budget_' + name)
        # Removing terminal punctuation is never a detector optimization.
        for x in report['changes']:
            a, b = original[x['start']:x['end']], revision[x['revision_start']:x['revision_end']]
            if re.search(r'[。！？!?]', a) and not re.search(r'[。！？!?]', b):
                pending.append('terminal_punctuation_removed')
        template = review_template(original, revision, manifest, plan)
        if not isinstance(review, dict):
            pending.append('semantic_review_missing')
        else:
            for key in ('schema_version', 'original_sha256', 'revision_sha256', 'manifest_sha256', 'plan_sha256'):
                if review.get(key) != template[key]:
                    errors.append('review_binding_' + key)
            if not review.get('reviewer') or not review.get('reviewed_at') or review.get('reviewer_type') not in ('llm', 'human') or review.get('entities_complete') is not True:
                pending.append('review_identity_or_entity_inventory_missing')
            for name in DIMENSIONS:
                entry = review.get('dimensions', {}).get(name, {})
                if entry.get('status') == 'FAIL':
                    errors.append('semantic_' + name)
                elif entry.get('status') != 'PASS' or not str(entry.get('evidence', '')).strip():
                    pending.append('review_' + name)
            changes = review.get('change_reviews', [])
            if len(changes) != len(template['change_reviews']):
                pending.append('change_review_incomplete')
            else:
                for actual, required in zip(changes, template['change_reviews']):
                    if any(actual.get(k) != required[k] for k in ('index', 'original', 'revision')):
                        errors.append('change_review_binding')
                    if actual.get('status') == 'FAIL':
                        errors.append('semantic_change_drift')
                    elif actual.get('status') != 'PASS' or not str(actual.get('reason', '')).strip():
                        pending.append('change_review_missing')
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        errors.append('invalid_input:' + str(exc))
        report = None
    status = 'FAIL' if errors else ('REVIEW_REQUIRED' if pending else 'PASS')
    return {'status': status, 'errors': sorted(set(errors)), 'pending': sorted(set(pending)), 'diff': report,
            'facts_check': 'PASS' if status == 'PASS' else status,
            'note': 'PASS combines exact checks with a recorded semantic review; it is not independent fact verification.'}
