from __future__ import annotations

import unittest

from server.rate_limit import check_agent_submission


class FakeRedis:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def eval(self, *args):
        self.calls.append(args)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class RateLimitTests(unittest.TestCase):
    def test_all_dimensions_are_consumed_atomically(self):
        client = FakeRedis([1, 0, 60])
        result = check_agent_submission(user_id="u1", ip="127.0.0.1", skill_id="wechat", client=client, now=60)
        self.assertTrue(result.allowed)
        self.assertEqual(3, client.calls[0][1])
        self.assertEqual(3, len(client.calls[0][2:5]))

    def test_rejected_dimension_and_retry_are_returned(self):
        result = check_agent_submission(
            user_id="u1", ip="127.0.0.1", skill_id="wechat",
            client=FakeRedis([0, 3, 17]), now=60,
        )
        self.assertFalse(result.allowed)
        self.assertEqual("skill", result.dimension)
        self.assertEqual(17, result.retry_after)

    def test_redis_outage_fails_open(self):
        result = check_agent_submission(
            user_id="u1", ip="127.0.0.1", skill_id="wechat",
            client=FakeRedis(ConnectionError("down")), now=60,
        )
        self.assertTrue(result.allowed)


if __name__ == "__main__":
    unittest.main()
