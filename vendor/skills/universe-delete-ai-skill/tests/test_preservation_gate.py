"""Synthetic invariants, not real authorship/detector examples."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from scripts.preservation import (MAX_CHARS, DIMENSIONS, apply_plan, build_manifest,
                                  diff, digest, gate, review_template, structure)
from scripts.revision_workflow import run


def fixture(before='团队完成了对流程的优化。', after='团队优化了流程。', entities=None):
    text = '材料已核对。\n\n' + before + '\n\n项目继续运行。\n\n记录保持完整。\n\n作者保留判断。'
    start = text.index(before)
    plan = {'base_sha256': digest(text), 'change_type': 'one_local_edit', 'edits': [
        {'start': start, 'end': start + len(before), 'original': before, 'replacement': after, 'reason': 'synthetic fixture'}]}
    candidate = apply_plan(text, plan)
    manifest = build_manifest(text, entities)
    review = review_template(text, candidate, manifest, plan)
    review.update(reviewer='synthetic_test_fixture_NOT_real_review', reviewer_type='llm', reviewed_at='2026-09-06', entities_complete=True)
    review['dimensions'] = {x: {'status': 'PASS', 'evidence': 'Synthetic test stub only.'} for x in DIMENSIONS}
    for change in review['change_reviews']:
        change.update(status='PASS', reason='Synthetic stub, not a quality claim.')
    return text, candidate, manifest, plan, review


class GateTests(unittest.TestCase):
    def test_local_edit_pass(self):
        self.assertEqual(gate(*fixture())['status'], 'PASS')

    def test_missing_review_not_pass(self):
        args = list(fixture()); args[-1] = None
        self.assertEqual(gate(*args)['status'], 'REVIEW_REQUIRED')

    def test_empty_and_long_input(self):
        for text in ('', ' ', '中' * (MAX_CHARS + 1)):
            with self.assertRaises(ValueError): build_manifest(text)
        self.assertTrue(diff('甲' * 6000, '甲' * 5999 + '乙')['heuristic_alignment'])

    def test_protected_mutations(self):
        pairs = [('收入100元。', '收入200元。'), ('到期2026-09-06。', '到期2026-09-07。'),
                 ('访问https://example.com/a。', '访问https://example.com/b。'),
                 ('他说“明天见”。', '他说“明天去”。'), ('"hello"是原话。', '"hi"是原话。'),
                 ('可能支持。', '一定支持。'), ('没有批准。', '批准。'),
                 ('金额100元和100元。', '金额100元。'), ('共三百人。', '共四百人。'),
                 ('使用`x = 1`。', '使用`x = 2`。')]
        for a, b in pairs:
            with self.subTest(a=a): self.assertEqual(gate(*fixture(a, b))['status'], 'FAIL')

    def test_same_name_multiple_occurrences(self):
        data = fixture('李清照看书，李清照写字。', '李清照看书，她写字。', ['李清照'])
        self.assertEqual(gate(*data)['status'], 'FAIL')

    def test_entity_replaced(self):
        self.assertEqual(gate(*fixture('李清照看书。', '赵明诚看书。', ['李清照']))['status'], 'FAIL')

    def test_markdown_structure(self):
        for a, b in [('# 原标题', '# 新标题'), ('- 保留项目', '- 新项目'), ('> 引用原文', '> 引用改写'),
                     ('```python\nx = 1\n```', '```python\nx = 2\n```'),
                     ('| 列 | 值 |', '| 新列 | 值 |')]:
            with self.subTest(a=a): self.assertEqual(gate(*fixture(a, b))['status'], 'FAIL')
        self.assertEqual(structure('### 标题\n- 一\n> 原话\n```py\nx=1\n```'),
                         ['heading:### 标题', 'list:- 一', 'quote:> 原话', 'fence:```', 'fence_end'])

    def test_unchanged_mixed_markdown(self):
        text = '# 标题\r\n\r\n- 中文 API\r\n\r\n> 引号“原话”。\r\n\r\n```py\nx=1\r\n```'
        self.assertEqual(apply_plan(text, {'base_sha256': digest(text), 'change_type': 'none', 'edits': []}), text)
        self.assertEqual(diff(text, text)['ratios']['chars'], 0)

    def test_tampered_manifest_review_and_plan(self):
        for kind in ('manifest', 'review', 'plan'):
            args = list(fixture())
            if kind == 'manifest': args[2]['protected_spans'] = [{'text': 'fake'}]
            if kind == 'review': args[4]['revision_sha256'] = 'stale'
            if kind == 'plan': args[3]['base_sha256'] = 'stale'
            with self.subTest(kind=kind): self.assertEqual(gate(*args)['status'], 'FAIL')

    def test_review_cannot_ignore_change(self):
        args = list(fixture()); args[4]['change_reviews'] = []
        self.assertEqual(gate(*args)['status'], 'REVIEW_REQUIRED')

    def test_over_budget(self):
        args = fixture('长篇原文的内容。' * 12, '完全重新写的内容。' * 12)
        self.assertTrue(any('change_budget' in x for x in gate(*args)['errors']))

    def test_insert_without_plan(self):
        args = list(fixture()); args[1] += '新增事实。'
        self.assertIn('revision_outside_plan', gate(*args)['errors'])

    def test_punctuation_loss_requires_review(self):
        args = fixture('文字的意思完整且需要句号。', '文字的意思完整且需要句号')
        self.assertNotEqual(gate(*args)['status'], 'PASS')

    def test_entity_swap_review_rolls_back(self):
        args = fixture('她告发了他。', '他告发了她。')
        args[-1]['dimensions']['entities'] = {'status': 'FAIL', 'evidence': 'Synthetic actor/object swapped.'}
        result = run(args[0], args[2], [{'plan': args[3], 'review': args[4]}])
        self.assertEqual(result['final_text'], args[0])
        self.assertEqual(result['rollback_count'], 1)

    def test_causal_drift_rolls_back(self):
        args = fixture('因为停电，设备停机。', '因为设备停机，所以停电。')
        args[-1]['dimensions']['causality'] = {'status': 'FAIL', 'evidence': 'Synthetic causal direction reversed.'}
        result = run(args[0], args[2], [{'plan': args[3], 'review': args[4]}])
        self.assertEqual(result['final_text'], args[0])

    def test_bad_readability_blocks_feedback(self):
        args = fixture(); args[-1]['dimensions']['readability'] = {'status': 'FAIL', 'evidence': 'Synthetic grammar degradation.'}
        result = run(args[0], args[2], [{'plan': args[3], 'review': args[4],
                                        'detector_feedback': {'text_sha256': digest(args[1]), 'risk': 0.1,
                                                              'checked_at': 'test', 'source': 'synthetic', 'comparison_id': 'case-1'}}],
                     baseline_feedback={'text_sha256': digest(args[0]), 'risk': 0.9,
                                        'checked_at': 'test', 'source': 'synthetic', 'comparison_id': 'case-1'})
        self.assertEqual(result['rollback_count'], 1)

    def test_no_improvement_two_round_stop(self):
        args = fixture()
        feedback = {'text_sha256': digest(args[1]), 'risk': .9, 'checked_at': 'test', 'source': 'synthetic',
                    'comparison_id': 'case-2'}
        result = run(args[0], args[2], [{'plan': args[3], 'review': args[4], 'detector_feedback': feedback}] * 3,
                     baseline_feedback={'text_sha256': digest(args[0]), 'risk': .9,
                                        'checked_at': 'test', 'source': 'synthetic', 'comparison_id': 'case-2'})
        self.assertEqual(len(result['rounds']), 2)
        self.assertEqual(result['stop_reason'], 'two_rounds_no_improvement')
        self.assertEqual(result['final_text'], args[0])

    def test_invalid_feedback_rolls_back(self):
        args = fixture()
        result = run(args[0], args[2], [{'plan': args[3], 'review': args[4],
                                        'detector_feedback': {'text_sha256': 'wrong', 'risk': .1,
                                                              'checked_at': 'test', 'source': 'manual', 'comparison_id': 'case-3'}}],
                     baseline_feedback={'text_sha256': digest(args[0]), 'risk': .9,
                                        'checked_at': 'test', 'source': 'manual', 'comparison_id': 'case-3'})

    def test_feedback_requires_same_manual_session(self):
        args = fixture()
        feedback = {'text_sha256': digest(args[1]), 'risk': .1, 'checked_at': 'test',
                    'source': 'manual', 'comparison_id': 'different'}
        result = run(args[0], args[2], [{'plan': args[3], 'review': args[4], 'detector_feedback': feedback}],
                     baseline_feedback={'text_sha256': digest(args[0]), 'risk': .9, 'checked_at': 'test',
                                        'source': 'manual', 'comparison_id': 'baseline'})
        self.assertEqual(result['stop_reason'], 'invalid_detector_feedback')
        self.assertEqual(result['final_text'], args[0])
        self.assertEqual(result['stop_reason'], 'invalid_detector_feedback')
        self.assertEqual(result['final_text'], args[0])

    def test_offline_stops_after_one(self):
        args = fixture()
        self.assertEqual(len(run(args[0], args[2], [{'plan': args[3], 'review': args[4]}] * 3)['rounds']), 1)

    def test_null_review_rolls_back_without_crash(self):
        args = fixture()
        result = run(args[0], args[2], [{'plan': args[3], 'review': None}])
        self.assertEqual(result['rollback_count'], 1)
        self.assertEqual(result['final_text'], args[0])

    def test_no_rounds_still_validates_input(self):
        with self.assertRaises(ValueError): run('', {}, [])
        args = fixture()
        self.assertEqual(run(args[0], args[2], [])['stop_reason'], 'no_revision_requested')

    def test_gate_cli_and_workflow_cli(self):
        args = fixture()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for filename, value in [('original.md', args[0]), ('revision.md', args[1]), ('manifest.json', args[2]),
                                    ('plan.json', args[3]), ('review.json', args[4]), ('rounds.json', [{'plan': args[3], 'review': args[4]}])]:
                (root / filename).write_text(value if isinstance(value, str) else json.dumps(value), encoding='utf-8', newline='')
            call = subprocess.run([sys.executable, 'scripts/semantic_gate.py', str(root/'original.md'), str(root/'revision.md'),
                                   '--manifest', str(root/'manifest.json'), '--plan', str(root/'plan.json'), '--review', str(root/'review.json')], capture_output=True)
            self.assertEqual(call.returncode, 0, call.stderr)
            workflow = [sys.executable, 'scripts/revision_workflow.py', str(root/'original.md'), '--manifest', str(root/'manifest.json'),
                        '--rounds', str(root/'rounds.json'), '--output', str(root/'final.md')]
            self.assertEqual(subprocess.run(workflow, capture_output=True).returncode, 0)
            self.assertEqual((root/'final.md').read_text(encoding='utf-8'), args[1])
            self.assertNotEqual(subprocess.run(workflow, capture_output=True).returncode, 0)

if __name__ == '__main__':
    unittest.main()
