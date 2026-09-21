from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from server.rate_limit import LimitResult
from server.workflow_api import WorkflowCreate, start_workflow


class WorkflowApiTests(unittest.TestCase):
    def test_create_uses_user_ip_and_skill_rate_limit_before_billing(self):
        request = SimpleNamespace(
            state=SimpleNamespace(user={"id": "user-a"}),
            headers={"x-forwarded-for": "203.0.113.9, 127.0.0.1"},
            client=SimpleNamespace(host="127.0.0.1"),
        )
        payload = WorkflowCreate(topic="选题", idempotency_key="workflow-key")
        with patch("server.workflow_api.check_agent_submission",
                   return_value=LimitResult(False, "ip", 23)) as limit, \
             patch("server.workflow_api.create_billed_workflow") as billed:
            with self.assertRaises(HTTPException) as raised:
                start_workflow(payload, request)
        self.assertEqual(429, raised.exception.status_code)
        self.assertEqual("23", raised.exception.headers["Retry-After"])
        self.assertEqual("ip", raised.exception.headers["X-RateLimit-Dimension"])
        limit.assert_called_once_with(
            user_id="user-a", ip="203.0.113.9", skill_id="wechat_writer",
        )
        billed.assert_not_called()


if __name__ == "__main__":
    unittest.main()
