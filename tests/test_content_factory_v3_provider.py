import json
from types import SimpleNamespace

import pytest

from server import content_factory_v3_tasks as tasks
from server import content_factory_vision
from server.providers import ModelService


@pytest.fixture(autouse=True)
def provider_settings(monkeypatch):
    monkeypatch.setattr(tasks.workbench.accounts, "provider_settings", lambda **kwargs: {})


def test_single_call_bounded_and_no_retry(monkeypatch):
    calls = []
    def call(self, messages, **kwargs):
        calls.append((self.text_provider.max_output_tokens, kwargs["idempotency_key"]))
        return SimpleNamespace(text='{"title":"ok"}')
    monkeypatch.setattr(ModelService, "create_response", call)
    assert tasks._single_json_call("hello", run_id="abc", step="title") == {"title": "ok"}
    assert calls == [(4096, "factory-v3:title:abc:0")]
    with pytest.raises(ValueError):
        tasks._single_json_call("a" * 120001, run_id="abc", step="title")
    assert len(calls) == 1


def test_single_call_does_not_retry_bad_json(monkeypatch):
    calls = []
    def call(self, messages, **kwargs):
        calls.append(1)
        return SimpleNamespace(text="not JSON")
    monkeypatch.setattr(ModelService, "create_response", call)
    with pytest.raises(ValueError):
        tasks._single_json_call("hello", run_id="abc", step="article")
    assert len(calls) == 1


def test_retry_attempt_uses_a_new_provider_idempotency_key(monkeypatch):
    keys = []
    monkeypatch.setattr(ModelService, "create_response",
                        lambda self, messages, **kwargs: (
                            keys.append(kwargs["idempotency_key"])
                            or SimpleNamespace(text='{"title":"ok"}')))
    tasks._single_json_call("hello", run_id="abc", step="article", attempt=2)
    assert keys == ["factory-v3:article:abc:2"]


def test_measured_tokens_are_written_to_the_v3_call_log(monkeypatch, tmp_path):
    import sqlalchemy as sa
    from server.content_factory_v3_store import metadata, provider_calls
    engine = sa.create_engine(f"sqlite:///{(tmp_path / 'usage.db').as_posix()}")
    metadata.create_all(engine)
    monkeypatch.setattr(tasks.database, 'ENGINE', engine)
    monkeypatch.setattr(ModelService, "create_response",
                        lambda self, messages, **kwargs: SimpleNamespace(
                            text='{"title":"ok"}', input_tokens=120, output_tokens=30))
    tasks._single_json_call("hello", run_id="run-usage", step="title")
    with engine.connect() as connection:
        row = connection.execute(provider_calls.select()).mappings().one()
    assert (row['run_id'], row['step'], row['input_tokens'], row['output_tokens']) == (
        'run-usage', 'title', 120, 30)


def test_vision_review_reports_success_only_with_every_boolean(monkeypatch):
    captured = {}
    checks = {name: True for name in content_factory_vision.CHECK_FIELDS}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {
                "content": json.dumps({"checks": checks, "issues": []})}}]}

    monkeypatch.setattr(content_factory_vision.workbench, "_setting",
                        lambda *args, **kwargs: "vision-model")
    monkeypatch.setattr(content_factory_vision.workbench, "_headers",
                        lambda *args, **kwargs: {})
    monkeypatch.setattr(content_factory_vision.workbench, "_api_url",
                        lambda *args, **kwargs: "https://example.com/chat")
    monkeypatch.setattr(content_factory_vision.workbench, "_verify_ssl",
                        lambda *args, **kwargs: True)

    def post(url, **kwargs):
        captured.update(kwargs["headers"])
        return Response()

    result = content_factory_vision.review(
        b"image", title="标题", image_text="主文案", caption="配文",
        run_id="run-one", attempt=1, post=post)
    assert result["status"] == "success"
    assert captured["Idempotency-Key"] == "factory-v3:vision:run-one:1"
