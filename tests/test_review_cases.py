"""Replay real production failures against the review node, offline and free.

Every one of these came from a live run that died in review. They stay in the
repo so a future change cannot quietly reintroduce the same deadlock.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server import skill_runtime
from server import workbench as w

FIXTURES = Path(__file__).parent / "fixtures" / "review"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class ReviewCaseReplay(unittest.TestCase):
    maxDiff = None

    def _replay(self, case: dict):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(w, 'OUTPUT_DIR', Path(directory)), \
             patch.object(w, '_review_skill_context', return_value=('Skill rules', [])), \
             patch.object(skill_runtime, 'script', side_effect=[{'signals': []}, {'review_items': []},
                                                                {'signals': []}, {'review_items': []}]), \
             patch.object(skill_runtime, 'length_issue', return_value=None), \
             patch.object(w, '_anti_ai_audit', return_value=case['audit']), \
             patch.object(w, '_json_text', return_value=case['diagnosis']), \
             patch.object(w, '_text', return_value=case['article']), \
             patch.dict('os.environ', {'WECHAT_REVIEW_ROUNDS': '1'}):
            return w._review(case['article'], {'id': case.get('id', 'case'), 'brief': '审稿'})

    def test_title_punctuation_delivers_instead_of_failing(self):
        case = _load('case_title_punctuation.json')
        article, report = self._replay(case)
        self.assertEqual('passed', report['gate'])
        self.assertEqual(case['article'], article)
        self.assertTrue(report['rounds'][0]['diagnosis'].get('title_notes')
                        or report.get('pending_review_notes'))

    def test_wording_opinion_delivers_instead_of_failing(self):
        case = _load('case_waiting_ambiguity.json')
        _article, report = self._replay(case)
        self.assertEqual('passed', report['gate'])
        self.assertTrue(report['pending_review_notes'])

    def test_inference_strength_opinion_delivers_instead_of_failing(self):
        case = _load('case_inference_strength.json')
        _article, report = self._replay(case)
        self.assertEqual('passed', report['gate'])
        self.assertTrue(report['pending_review_notes'])

    def test_lost_quotation_still_blocks(self):
        case = _load('case_missing_protected_span.json')
        with self.assertRaises(w.ProviderError):
            self._replay(case)

    def test_every_fixture_documents_where_it_came_from(self):
        for path in FIXTURES.glob('*.json'):
            with self.subTest(fixture=path.name):
                case = json.loads(path.read_text(encoding='utf-8'))
                self.assertTrue(case.get('note'), '每个用例都要写清楚它来自哪次线上失败')
                self.assertIn(case.get('expect_gate'), {'passed', 'raise'})


if __name__ == '__main__':
    unittest.main()
