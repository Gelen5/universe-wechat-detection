import json
import tempfile
import unittest
from pathlib import Path
from scripts.audit_repository import link_audit
from scripts.build_evaluation import build
from scripts.run_evaluation import evaluate
from scripts.evaluate_corpus import evaluate as legacy_evaluate
from scripts.ingest_story_sources import as_records, normalize
from scripts.zhuque_public_probe import summarize_demo
from scripts.check_ai_tone_signals import analyze


class HelpersTests(unittest.TestCase):
    def test_evaluation_unknown_not_zero(self):
        report = evaluate(Path('eval/cases'))
        self.assertEqual(report['cases'], 3)
        self.assertEqual(report['local_pass'], 3)
        self.assertEqual(report['detector_pairs'], 0)
        self.assertIsNone(report['mean_improvement'])
        self.assertEqual(report['positives'], 0)

    def test_archive_inventory_has_no_positives(self):
        items = json.loads(Path('eval/archive/index.json').read_text(encoding='utf-8'))
        self.assertEqual(len(items), 12)
        self.assertTrue(all(x['status'] in ('unknown', 'quarantined') for x in items))

    def test_build_corpus_preserves_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'approved-works').mkdir()
            for source in Path('approved-works').glob('*.md'):
                (root/'approved-works'/source.name).write_bytes(source.read_bytes())
            self.assertEqual(build(root)['new_local_pairs'], 3)
            self.assertEqual(evaluate(root/'eval/cases')['local_pass'], 3)
            with self.assertRaises(FileExistsError): build(root)

    def test_story_normalizer_not_verified(self):
        records = as_records({'items': [{'title': '标题', 'url': 'https://example.com'}]})
        item = normalize(records[0], '职场', 'test')
        self.assertEqual(item['status'], 'needs_manual_review')
        self.assertEqual(item['copyright_use'], 'metadata_and_summary_only')

    def test_public_probe_summary(self):
        result = summarize_demo('test', {'q': '原文', 'a': '{invalid'})
        self.assertEqual(result['chars'], 2)
        self.assertEqual(result['segment_count'], 0)

    def test_legacy_corpus_is_only_scan(self):
        self.assertEqual(legacy_evaluate(Path('approved-works'), 'minimal', 2)['documents'], 2)

    def test_current_links_resolve(self):
        root = Path('.')
        self.assertEqual(link_audit((root/'SKILL.md').read_text(encoding='utf-8'), root)['missing'], [])

    def test_missing_link_is_reported(self):
        self.assertEqual(link_audit('[bad](does-not-exist.md)', Path('.'))['missing'], ['does-not-exist.md'])

    def test_code_quote_not_automatically_editable(self):
        for text in ('```text\n说白了，这句话不该改。\n```', '“说白了，这句话不该改。”'):
            self.assertEqual(analyze(text)['signals'], [])
        self.assertFalse(any(x['auto_fix_allowed'] for x in analyze('说白了，成本太高。')['signals']))

    def test_artifact_span_does_not_authorize_whole_line(self):
        text = '保留这句话。[待填写]保留后面的句子。'
        signal = next(x for x in analyze(text)['signals'] if x['rule_id'] == 'ai_placeholder')
        self.assertEqual(text[signal['start']:signal['end']], '[待填写]')

if __name__ == '__main__':
    unittest.main()
