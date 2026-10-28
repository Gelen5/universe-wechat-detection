"""Writing rules have exactly one source: the vendored Skill references.

``writing_guidance`` may choose and assemble rules, but every rule string it
returns must be byte-identical to text in the reference files, and no server
module may carry a private copy of that wording.
"""
import unittest
from pathlib import Path

from server import writing_guidance as w

ROOT = Path(__file__).resolve().parents[1]
REFS = w.REFERENCES


def _reference_corpus() -> str:
    return '\n'.join(p.read_text(encoding='utf-8') for p in sorted(REFS.iterdir()) if p.is_file())


def _rule_lines(text: str):
    """Substantive rule sentences (long enough that a match is not accidental)."""
    for line in text.replace('\r\n', '\n').split('\n'):
        line = line.strip().lstrip('-# ').strip()
        if len(line) >= 30:
            yield line


class RuleSingleSourceTests(unittest.TestCase):
    def test_every_assembled_rule_exists_in_reference_files(self):
        corpus = _reference_corpus()
        rules = [w.GUIDANCE, w.DRAFT_QUALITY_RULES, *w.GENRE_STRATEGIES.values()]
        for rule in rules:
            with self.subTest(rule=rule[:40]):
                self.assertIn(rule, corpus)

    def test_every_genre_key_has_a_rule(self):
        for strategy in ({'article_type': k} for k in ('tutorial', 'news', 'story', 'emotional_opinion', 'opinion', 'x')):
            self.assertIn(w.genre_key(strategy), w.GENRE_STRATEGIES)

    def test_no_server_module_keeps_a_private_copy_of_rule_wording(self):
        """A rule sentence must not be duplicated inside server/*.py."""
        sentences = set()
        for p in REFS.iterdir():
            if p.suffix in {'.md', '.json'}:
                sentences.update(_rule_lines(p.read_text(encoding='utf-8')))
        offenders = []
        for py in (ROOT / 'server').rglob('*.py'):
            source = py.read_text(encoding='utf-8')
            for sentence in sentences:
                if sentence in source:
                    offenders.append(f'{py.relative_to(ROOT)}: {sentence[:40]}')
        self.assertEqual([], offenders)


if __name__ == '__main__':
    unittest.main()
