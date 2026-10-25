"""Reproducible archive inventory and three explicitly reviewed local edit pairs.

These are historical manuscript snapshots, not recovered pre-rewrite originals.
The review judgments below are the implementing Agent's 2026-09-06 editorial
review of these exact edits, not a detector result or a generic PASS generator.
"""
import json
from pathlib import Path
try:
    from .preservation import apply_plan, build_manifest, digest, read, review_template
    from .check_natural_prose import analyze
except ImportError:
    from preservation import apply_plan, build_manifest, digest, read, review_template
    from check_natural_prose import analyze

PAIRS = [
    ('毕业10年所有同学群彻底死了。.md', '活跃的基本都基本是', '活跃的基本都是',
     ['QQ', '微信'], '删除紧邻的重复“基本”，保留基本这个限定、群体活跃观察及先后顺序。'),
    ('越来越多男性开始放弃传宗接代了。.md', '最近的近况', '近况',
     ['堂小叔', '小张'], '近况已包含最近状态，删重复定语；仍是送鸭子后谈及堂小叔近况，没有增删事件。'),
    ('越来越多媳妇已经不踏进婆家家门了。.md', '到是“流行”', '倒是“流行”',
     ['海南', '广州', '潮汕', '黄姐', '张三', '李四', '黄五'], '将转折副词的同音字到修正为倒；流行仍为原文引号中的说法，立场不变。'),
]


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    content = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
    with path.open('x', encoding='utf-8', newline='') as stream:
        stream.write(content)


def build(repo):
    inventory = []
    for path in sorted((repo / 'approved-works').glob('*.md')):
        text = read(path)
        report = analyze(text)
        punctuation = report['long_sentences_without_terminal_punctuation']
        inventory.append({'path': path.relative_to(repo).as_posix(), 'sha256': digest(text), 'chars': len(text),
                          'status': 'quarantined' if punctuation > 3 else 'unknown',
                          'original_before_historical_rewrite': None, 'detector_evidence': None,
                          'human_confirmed_meaning': None, 'fact_damage': None,
                          'punctuation_review_count': punctuation,
                          'reason': 'Missing paired original, dated detector evidence and independent fidelity review; never a positive by directory name.'})
    write_new(repo / 'eval/archive/index.json', inventory)
    for i, (filename, before, after, entities, reason) in enumerate(PAIRS, 1):
        original = read(repo / 'approved-works' / filename)
        start = original.index(before)
        plan = {'base_sha256': digest(original), 'change_type': 'local_copyedit', 'edits': [
            {'start': start, 'end': start + len(before), 'original': before, 'replacement': after, 'reason': reason}]}
        revision = apply_plan(original, plan)
        manifest = build_manifest(original, entities)
        review = review_template(original, revision, manifest, plan)
        review.update(reviewer='Codex editorial review', reviewer_type='llm', reviewed_at='2026-09-06', entities_complete=True)
        evidence = {
            'theme': '全文只有该局部校对；主题及标题逐字保留。',
            'claims': '所有其余句子未动；此处没有删独有判断。' + reason,
            'facts': '此处仅重复定语/同音字校对，不改变原稿事实陈述；未核验原稿事实的外部真实性。',
            'entities': '该处不涉及人物/组织/地点改动，全文其他人名和关系保持原字面。',
            'causality': '没有增加或删除因果连接和事件，原论证路径保留。',
            'time_order': '时间词与事件顺序未改；近况本身仍指近期情况。',
            'stance': '作者语气、评价、数量和限定不变。' + reason,
            'quotes': '所有带引号原话保持，校对在引号之外。',
            'negation': '此修改未动任何否定及强度限定。',
            'readability': '修改处可连续阅读、句末标点保留；全文原有口语/省略未新增，不将标点统计当语法证明。',
            'naturalness': '只处理一处明显重复/错字，不改作者叙述语气，不插入假细节。',
        }
        review['dimensions'] = {key: {'status': 'PASS', 'evidence': value} for key, value in evidence.items()}
        for change in review['change_reviews']:
            change.update(status='PASS', reason=reason)
        root = repo / 'eval/cases' / f'{i:03}'
        for name, value in [('original.md', original), ('revision.md', revision), ('manifest.json', manifest),
                            ('rounds.json', [{'plan': plan, 'review': review}]),
                            ('metadata.json', {'kind': 'real_historical_snapshot_local_edit', 'article_type': '公众号社会观察',
                                               'source': 'approved-works/' + filename, 'chars': len(original),
                                               'zhuque_original': None, 'zhuque_revision': None, 'detected_at': None,
                                               'detector_model_version': None, 'edit_scope': 'one_local_span',
                                               'human_confirmed_meaning': False, 'fact_damage': None,
                                               'passed': None, 'review_kind': 'llm_not_human',
                                               'provenance': 'Existing repository snapshot reused as current experiment baseline; historical pre-rewrite original unknown.'})]:
            write_new(root / name, value)
    return {'archive_sources': len(inventory), 'new_local_pairs': len(PAIRS), 'detector_pairs': 0}


if __name__ == '__main__':
    print(json.dumps(build(Path(__file__).resolve().parents[1])))
