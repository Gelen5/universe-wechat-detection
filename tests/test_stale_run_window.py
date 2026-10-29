import unittest
from datetime import datetime, timedelta, timezone

from tests.test_agent_tasks import AgentTaskTests
from server import conversation_repository, database
from server.models import AgentRun


class StaleRunWindowTests(AgentTaskTests):
    def test_default_recovery_waits_for_three_missed_heartbeats(self):
        conversation_repository.claim_run(self.run['id'], 'old-task')
        with database.session_scope() as db:
            row = db.get(AgentRun, self.run['id'])
            row.heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=150)
        self.assertEqual([], conversation_repository.recover_stale_runs())
        with database.session_scope() as db:
            row = db.get(AgentRun, self.run['id'])
            row.heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=210)
        self.assertEqual([self.run['id']], conversation_repository.recover_stale_runs())


if __name__ == '__main__':
    unittest.main()
