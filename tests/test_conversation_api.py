from __future__ import annotations

import uuid
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from tests import support  # noqa: F401
from server import conversation_repository, database
from server.main import app
from server.models import Base


class ConversationApiTests(unittest.TestCase):
    def setUp(self):
        engine = database.build_engine()
        Base.metadata.create_all(engine, checkfirst=True)
        database.ENGINE = engine
        database.SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
        self.client = TestClient(app)
        response = self.client.post("/api/auth/login", json={
            "email": "admin@example.com", "password": "testing-pass-123"})
        assert response.status_code == 200, response.text
        self.user_id = response.json()["user"]["id"]

    def tearDown(self):
        self.client.close()
        database.ENGINE.dispose()

    def create(self, **values):
        payload = {"title": "公众号创作", "mode": "manual", "skill_id": "wechat_writer", **values}
        response = self.client.post("/api/conversations", json=payload)
        self.assertEqual(201, response.status_code, response.text)
        return response.json()["conversation"]

    def test_create_and_restore_conversation(self):
        conversation = self.create()
        restored = self.client.get(f"/api/conversations/{conversation['id']}")
        self.assertEqual(200, restored.status_code)
        self.assertEqual("wechat_writer", restored.json()["conversation"]["skill_id"])

    def test_manual_mode_requires_known_skill(self):
        missing = self.client.post("/api/conversations", json={"mode": "manual"})
        unknown = self.client.post("/api/conversations", json={"mode": "manual", "skill_id": "missing"})
        self.assertEqual(422, missing.status_code)
        self.assertEqual(422, unknown.status_code)

    def test_send_is_async_and_idempotent_without_duplicate_message(self):
        conversation = self.create()
        key = uuid.uuid4().hex
        with patch("server.conversation_api.dispatch_run", return_value="task-1") as dispatch:
            first = self.client.post(f"/api/conversations/{conversation['id']}/messages",
                                     headers={"Idempotency-Key": key}, json={"content": "第三个"})
            second = self.client.post(f"/api/conversations/{conversation['id']}/messages",
                                      headers={"Idempotency-Key": key}, json={"content": "第三个"})
        self.assertEqual(202, first.status_code, first.text)
        self.assertEqual(first.json()["run_id"], second.json()["run_id"])
        self.assertFalse(first.json()["idempotent_replay"])
        self.assertTrue(second.json()["idempotent_replay"])
        dispatch.assert_called_once()
        history = self.client.get(f"/api/conversations/{conversation['id']}/messages").json()["messages"]
        self.assertEqual(1, len([item for item in history if item["role"] == "user"]))

    def test_enqueue_failure_marks_run_failed(self):
        conversation = self.create()
        with patch("server.conversation_api.dispatch_run", side_effect=RuntimeError("redis down")):
            response = self.client.post(f"/api/conversations/{conversation['id']}/messages",
                headers={"Idempotency-Key": uuid.uuid4().hex}, json={"content": "写文章"})
        self.assertEqual(503, response.status_code)

    def test_cancel_and_owner_isolation(self):
        conversation = self.create()
        with patch("server.conversation_api.dispatch_run", return_value="task"):
            created = self.client.post(f"/api/conversations/{conversation['id']}/messages",
                headers={"Idempotency-Key": uuid.uuid4().hex}, json={"content": "写文章"}).json()
        cancelled = self.client.post(f"/api/runs/{created['run_id']}/cancel")
        self.assertEqual("cancelled", cancelled.json()["run"]["status"])

        other = TestClient(app)
        email = f"other-{uuid.uuid4().hex[:8]}@example.com"
        registered = other.post("/api/auth/register", json={
            "email": email, "password": "testing-pass-123", "display_name": "Other"})
        self.assertEqual(200, registered.status_code, registered.text)
        self.assertEqual(404, other.get(f"/api/conversations/{conversation['id']}").status_code)
        self.assertEqual(404, other.get(f"/api/runs/{created['run_id']}").status_code)
        self.assertEqual(404, other.get(f"/api/runs/{created['run_id']}/events").status_code)
        other.close()

    def test_sse_replays_from_last_event_id_and_finishes_for_terminal_run(self):
        conversation = self.create()
        with patch("server.conversation_api.dispatch_run", return_value="task"):
            created = self.client.post(
                f"/api/conversations/{conversation['id']}/messages",
                headers={"Idempotency-Key": uuid.uuid4().hex},
                json={"content": "写文章"},
            ).json()
        events = conversation_repository.events_after(
            created["run_id"], self.user_id)
        conversation_repository.transition_run(
            created["run_id"], self.user_id, "completed")

        response = self.client.get(
            f"/api/runs/{created['run_id']}/events",
            headers={"Last-Event-ID": str(events[0]["id"])},
        )
        self.assertEqual(200, response.status_code, response.text)
        self.assertNotIn("event: run.created", response.text)
        self.assertIn("event: run.queued", response.text)
        self.assertIn("event: run.completed", response.text)
        self.assertEqual("no-cache, no-transform", response.headers["cache-control"])

    def test_artifact_revision_is_append_only_and_owner_isolated(self):
        conversation = self.create()
        with patch("server.conversation_api.dispatch_run", return_value="task"):
            created = self.client.post(
                f"/api/conversations/{conversation['id']}/messages",
                headers={"Idempotency-Key": uuid.uuid4().hex}, json={"content": "写文章"},
            ).json()
        first = conversation_repository.create_artifact(
            created["run_id"], self.user_id, "article", title="文章", content="第一版")
        revised = self.client.post(
            f"/api/artifacts/{first['id']}/versions", json={"content": "第二版"})
        self.assertEqual(201, revised.status_code, revised.text)
        self.assertEqual(2, revised.json()["artifact"]["version"])
        versions = self.client.get(f"/api/artifacts/{first['id']}/versions").json()["artifacts"]
        self.assertEqual(["第一版", "第二版"], [item["content"] for item in versions])

        other = TestClient(app)
        registered = other.post("/api/auth/register", json={
            "email": f"artifact-{uuid.uuid4().hex[:8]}@example.com",
            "password": "testing-pass-123", "display_name": "Other"})
        self.assertEqual(200, registered.status_code, registered.text)
        self.assertEqual(404, other.get(f"/api/artifacts/{first['id']}").status_code)
        self.assertEqual(404, other.post(
            f"/api/artifacts/{first['id']}/versions", json={"content": "越权"}).status_code)
        other.close()


if __name__ == "__main__":
    unittest.main()
