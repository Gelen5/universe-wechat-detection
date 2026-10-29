import unittest
from pathlib import Path
from unittest.mock import patch
from tests import support  # noqa
from server import skill_host, workbench

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / 'vendor' / 'skills' / 'weChat-autoCreate'


class DowngradeTests(unittest.TestCase):
    def setUp(self):
        self.p = patch.object(workbench, 'SKILL_DIR', SKILL)
        self.p.start()
        self.state = skill_host.new_state('写一篇关于副业的观点文')

    def tearDown(self):
        self.p.stop()

    def _claim(self, cid, materiality='key', status='unverified'):
        self.state.evidence_pack.claims.append(
            skill_host._modules()[0].ClaimRecord(
                claim_id=cid, text=f'主张{cid}', kind='fact',
                materiality=materiality, status=status))

    def test_unsourced_key_claim_is_demoted_not_blocking(self):
        self._claim('c1')
        self._claim('c2', status='verified')
        demoted = skill_host._downgrade_claims(self.state)
        self.assertIn('主张c1', demoted)
        self.assertNotIn('主张c2', demoted)
        self.assertEqual('supporting', self.state.evidence_pack.claims[0].materiality)
        self.assertEqual('key', self.state.evidence_pack.claims[1].materiality)

    def test_downgrade_is_reported_for_the_user(self):
        self._claim('c1')
        skill_host._downgrade_claims(self.state)
        self.assertEqual(['主张c1'], skill_host.downgraded_claims(self.state))
        self.assertTrue(any('缺少可核验来源' in note for note in self.state.evidence_pack.limitations))

    def test_strict_mode_can_be_requested(self):
        with patch.dict('os.environ', {'WECHAT_EVIDENCE_MODE': 'strict'}):
            self.assertEqual('strict', skill_host.evidence_mode())
        with patch.dict('os.environ', {}, clear=True):
            self.assertEqual('auto', skill_host.evidence_mode())


if __name__ == '__main__':
    unittest.main()
