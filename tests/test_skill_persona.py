"""Persona, exemplar and humanness scoring all come from the skill's own files."""
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import support  # noqa: F401 - isolated account database
from server import skill_host, workbench
from server.main import app as _app  # noqa: F401 - initialises the account database

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / 'vendor' / 'skills' / 'weChat-autoCreate'


class PersonaTests(unittest.TestCase):
    def setUp(self):
        self.patch = patch.object(workbench, 'SKILL_DIR', SKILL)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_known_label_loads_a_real_persona_file(self):
        state = skill_host.new_state('写一篇产业观察')
        skill_host.apply_persona(state, '深度观察者')
        profile = state.author_profile
        self.assertIn('产业观察者', profile.name)
        self.assertTrue(profile.language_habits, 'persona expressions should reach the profile')
        self.assertTrue(profile.paragraph_rhythm)

    def test_unknown_label_falls_back_to_the_default_persona(self):
        state = skill_host.new_state('写一篇')
        skill_host.apply_persona(state, '不存在的风格')
        self.assertIn('产业观察者', state.author_profile.name)

    def test_persona_reaches_the_draft_prompt(self):
        state = skill_host.new_state('写一篇')
        skill_host.apply_persona(state, '科技评测')
        with patch.object(workbench, 'provider_overrides', __import__('contextlib').nullcontext), \
             patch.object(workbench, '_text', return_value='{}') as text:
            skill_host._generate(state, 'draft')('prompt')
        self.assertIn('风格参照', text.call_args.args[0])


class ExemplarTests(unittest.TestCase):
    def setUp(self):
        self.patch = patch.object(workbench, 'SKILL_DIR', SKILL)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_seeds_are_read_from_the_skill_with_a_no_copy_warning(self):
        prefix = skill_host.exemplar_prefix()
        self.assertIn('不得复用', prefix)
        self.assertGreater(len(prefix), 100)

    def test_missing_seed_file_is_not_fatal(self):
        with patch.object(workbench, 'SKILL_DIR', Path('/nonexistent')):
            self.assertEqual('', skill_host.exemplar_prefix())


class HumannessTests(unittest.TestCase):
    def test_score_is_a_dict_or_empty_and_never_raises(self):
        with patch.object(workbench, 'SKILL_DIR', Path('/nonexistent')):
            self.assertEqual({}, skill_host.score_article('一段正文'))
        self.assertEqual({}, skill_host.score_article(''))


if __name__ == '__main__':
    unittest.main()
