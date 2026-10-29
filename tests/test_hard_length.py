import contextlib, unittest
from pathlib import Path
from unittest.mock import patch
from tests import support  # noqa
from server import skill_host, workbench
from server.main import app as _app  # noqa

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / 'vendor' / 'skills' / 'weChat-autoCreate'

class HardLengthTests(unittest.TestCase):
    def test_draft_prompt_starts_with_the_hard_band(self):
        with patch.object(workbench, 'SKILL_DIR', SKILL):
            state = skill_host.new_state('写一篇关于素材库的观点文，约1200字')
        with patch.object(workbench, 'provider_overrides', contextlib.nullcontext), \
             patch.object(workbench, '_text', return_value='{}') as text:
            skill_host._generate(state, 'draft')('BODY')
        prompt = text.call_args.args[0]
        self.assertTrue(prompt.startswith('【硬性要求】'), prompt[:40])
        self.assertIn('960', prompt)
        self.assertIn('1440', prompt)

    def test_draft_without_length_has_no_banner(self):
        with patch.object(workbench, 'SKILL_DIR', SKILL):
            state = skill_host.new_state('写一篇观点文')
        with patch.object(workbench, 'provider_overrides', contextlib.nullcontext), \
             patch.object(workbench, '_text', return_value='{}') as text:
            skill_host._generate(state, 'draft')('BODY')
        self.assertNotIn('【硬性要求】', text.call_args.args[0])

if __name__ == '__main__':
    unittest.main()
