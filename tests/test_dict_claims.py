import unittest
from pathlib import Path
from unittest.mock import patch
from tests import support  # noqa
from server import skill_host, workbench

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / 'vendor' / 'skills' / 'weChat-autoCreate'


class DictClaimTests(unittest.TestCase):
    def setUp(self):
        self.p = patch.object(workbench, 'SKILL_DIR', SKILL)
        self.p.start()
        self.state = skill_host.new_state('副业')

    def tearDown(self):
        self.p.stop()

    def test_plain_dict_claims_are_demoted_too(self):
        self.state.evidence_pack.claims = [
            {'claim_id': 'c2', 'text': '行业平均月入过万', 'kind': 'fact',
             'materiality': 'key', 'status': 'unverified'}]
        demoted = skill_host._downgrade_claims(self.state)
        self.assertEqual(['行业平均月入过万'], demoted)
        self.assertEqual('supporting', self.state.evidence_pack.claims[0]['materiality'])


if __name__ == '__main__':
    unittest.main()
