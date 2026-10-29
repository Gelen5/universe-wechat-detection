import unittest
from pathlib import Path
from unittest.mock import patch
from tests import support  # noqa
from server import skill_host, workbench
from server.main import app as _app  # noqa

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / 'vendor' / 'skills' / 'weChat-autoCreate'

class StateSyncTests(unittest.TestCase):
    def setUp(self):
        self.p = patch.object(workbench, 'SKILL_DIR', SKILL); self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_second_different_request_is_a_new_creation(self):
        state = skill_host.new_state('写一篇关于素材库的观点文')
        state.draft = '旧文章'
        self.assertTrue(skill_host.is_new_creation(state, '写一篇关于时间管理的观点文，约1200字'))

    def test_same_request_continues_the_creation(self):
        state = skill_host.new_state('写一篇关于素材库的观点文')
        state.draft = '旧文章'
        self.assertFalse(skill_host.is_new_creation(state, '写一篇关于素材库的观点文，要求口语化'))

    def test_revision_reopens_review(self):
        state = skill_host.new_state('写一篇')
        state.draft = '旧稿'
        _s, _wf, _rt = skill_host._modules()
        state.nodes['review'].status = 'passed'
        state.quality_report = {'gate': 'passed'}
        skill_host.apply_revision(state, '新稿')
        self.assertEqual('新稿', state.draft)
        self.assertEqual('pending', state.nodes['review'].status)
        self.assertEqual({}, state.quality_report)

if __name__ == '__main__':
    unittest.main()
