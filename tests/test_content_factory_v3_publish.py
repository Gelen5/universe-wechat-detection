import base64
import io
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from tests import support  # noqa: F401
from server import database
from server.content_factory_purchase import jobs, metadata, products
from server.content_factory_v3_store import (metadata as v3_metadata, budget_reservations,
                                             ensure_settings, product_details, quality_reports,
                                             runs, settings, stage_candidate)


@pytest.fixture
def engine(tmp_path, monkeypatch):
    value = create_engine(f"sqlite:///{(tmp_path / 'publish.db').as_posix()}",
                          connect_args={"check_same_thread": False})
    metadata.create_all(value)
    v3_metadata.create_all(value)
    monkeypatch.setattr(database, "ENGINE", value)
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=value, expire_on_commit=False))
    return value


def queued_article(engine, *, publish=True, title="沟通不是说服对方"):
    from server.content_factory_v3_tasks import produce_draft
    from server.content_factory_v3_store import queue_production
    day = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    candidate = {"track": "情感", "topic": "家庭沟通",
                 "source": {"id": "one", "title": "来源标题", "url": "https://example.com/a",
                            "observed_at": day}}
    with engine.begin() as connection:
        ensure_settings(connection)
        run = stage_candidate(connection, day=day, product_type="article",
                              candidate=candidate, angle="沟通")
        plan = {"main_title": title,
                "alternative_titles": ["说清需求才容易商量", "给关系留一点空间", "争执后如何继续对话"],
                "strategy": "问题解决", "reason": "围绕沟通"}
        connection.execute(runs.update().where(runs.c.id == run["id"]).values(
            titles_json=json.dumps(plan, ensure_ascii=False), status="title_ready"))
        connection.execute(settings.update().where(settings.c.id == 1).values(
            emergency_stop=False, automatic_selection=True, cost_bound_verified=True,
            automatic_articles=True, automatic_article_publish=publish,
            daily_budget_micros=1000, title_call_bound_micros=100,
            article_call_bound_micros=300, detector_call_bound_micros=50,
            article_limit=1, tracks_json='["情感"]'))
        queue_production(connection, run_id=run["id"], day=day)
    return run["id"]


def quality_result():
    return {
        "scores": {"total": 75},
        "editorial_gate": {"status": "human_review", "blockers": [], "revisions": [], "confirmations": []},
        "source_ledger": [],
        "compliance": [],
        "content_risk": {"substantive": [], "confirm": [], "machine": []},
        "evidence": [],
    }


def test_successful_automatic_article_is_atomically_published(engine, monkeypatch):
    import server.content_factory_v3_tasks as tasks
    run_id = queued_article(engine)
    body = ("沟通不是把对方说服。" + "先确认彼此在意的具体问题，再说清自己能做的部分。" * 45)
    monkeypatch.setattr(tasks, "_single_json_call", lambda *args, **kwargs: {
        "content": body, "summary": "沟通摘要"})
    monkeypatch.setattr(tasks.creator_tools, "detect_article", lambda *args, **kwargs: quality_result())
    monkeypatch.setattr(tasks, "detect", lambda text: {
        "status": "success", "human_ratio": 0.9, "makers_tokens": 10}, raising=False)
    from server import content_factory_detector
    monkeypatch.setattr(content_factory_detector, "detect", lambda text: {
        "status": "success", "human_ratio": 0.9, "makers_tokens": 10})
    result = tasks.produce_draft.run(run_id)
    assert result["status"] == "published"
    with engine.connect() as connection:
        product = connection.execute(products.select().where(
            products.c.id == result["product_id"])).mappings().one()
        state = connection.execute(runs.select().where(runs.c.id == run_id)).mappings().one()
        report = connection.execute(quality_reports.select().where(
            quality_reports.c.run_id == run_id)).mappings().one()
        detail = connection.execute(product_details.select().where(
            product_details.c.run_id == run_id)).mappings().one()
    assert product["status"] == "published" and product["content_fingerprint"]
    assert state["status"] == "published" and state["error"] is None
    assert report["status"] == "eligible"
    assert "alternative_titles" in detail["details_json"]


def test_retry_reuses_the_existing_draft_product(engine, monkeypatch):
    import server.content_factory_v3_tasks as tasks
    from server.content_factory_v3_store import retry_run
    run_id = queued_article(engine)
    day = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    with engine.begin() as connection:
        connection.execute(products.insert().values(
            id="existing-draft", status="draft", product_type="article",
            title="旧标题", track="情感", preview="旧预览", content="旧正文",
            price_points=10, source_id="one", source_title="来源标题",
            source_url="https://example.com/a", source_date=day, created_at=day))
        connection.execute(runs.update().where(runs.c.id == run_id).values(
            status="held", error="production_failed", product_id="existing-draft"))
        assert retry_run(connection, run_id=run_id)["attempt"] == 1
        from server.content_factory_v3_store import queue_production
        queue_production(connection, run_id=run_id, day=day)

    body = ("沟通不是把对方说服。" + "先确认彼此在意的具体问题，再说清自己能做的部分。" * 45)
    monkeypatch.setattr(tasks, "_single_json_call",
                        lambda *args, **kwargs: {"content": body, "summary": "摘要"})
    monkeypatch.setattr(tasks.creator_tools, "detect_article",
                        lambda *args, **kwargs: quality_result())
    from server import content_factory_detector
    monkeypatch.setattr(content_factory_detector, "detect", lambda text: {
        "status": "success", "human_ratio": 0.9, "makers_tokens": 10})

    result = tasks.produce_draft.run(run_id)
    assert result == {"status": "published", "product_id": "existing-draft"}
    with engine.connect() as connection:
        stored = connection.execute(products.select()).mappings().all()
    assert len(stored) == 1
    assert stored[0]["id"] == "existing-draft" and stored[0]["status"] == "published"


def test_publish_switch_off_keeps_eligible_draft_held(engine, monkeypatch):
    import server.content_factory_v3_tasks as tasks
    run_id = queued_article(engine, publish=False)
    body = ("沟通不是把对方说服。" + "先确认彼此在意的具体问题，再说清自己能做的部分。" * 45)
    monkeypatch.setattr(tasks, "_single_json_call", lambda *args, **kwargs: {"content": body, "summary": ""})
    monkeypatch.setattr(tasks.creator_tools, "detect_article", lambda *args, **kwargs: quality_result())
    from server import content_factory_detector
    monkeypatch.setattr(content_factory_detector, "detect", lambda text: {
        "status": "success", "human_ratio": 0.9, "makers_tokens": 10})
    result = tasks.produce_draft.run(run_id)
    assert result["status"] == "held"
    with engine.connect() as connection:
        product = connection.execute(products.select().where(
            products.c.id == result["product_id"])).mappings().one()
        state = connection.execute(runs.select().where(runs.c.id == run_id)).mappings().one()
    assert product["status"] == "draft" and state["error"] == "automatic_publish_disabled"


def test_detector_failure_and_duplicate_execution_never_publish(engine, monkeypatch):
    import server.content_factory_v3_tasks as tasks
    run_id = queued_article(engine)
    body = ("沟通不是把对方说服。" + "先确认彼此在意的具体问题，再说清自己能做的部分。" * 45)
    monkeypatch.setattr(tasks, "_single_json_call", lambda *args, **kwargs: {"content": body, "summary": ""})
    monkeypatch.setattr(tasks.creator_tools, "detect_article", lambda *args, **kwargs: quality_result())
    from server import content_factory_detector
    monkeypatch.setattr(content_factory_detector, "detect", lambda text: {
        "status": "failed", "error": "timeout"})
    first = tasks.produce_draft.run(run_id)
    second = tasks.produce_draft.run(run_id)
    assert first["status"] == "held" and second["status"] == "ignored"
    with engine.connect() as connection:
        assert connection.execute(select(products.c.status)).scalars().all() == ["draft"]
        report = connection.execute(quality_reports.select()).mappings().one()
    assert "detector_not_passed" in report["report_json"]


def test_image_publish_requires_vision_and_stores_audit(engine, monkeypatch):
    import server.content_factory_v3_tasks as tasks
    from PIL import Image
    font = Path("C:/Windows/Fonts/msyh.ttc")
    if not font.is_file():
        pytest.skip("Chinese font unavailable")
    monkeypatch.setenv("CONTENT_FACTORY_FONT_PATH", str(font))
    day = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    candidate = {"track": "情感", "topic": "家庭沟通",
                 "source": {"id": "image-one", "title": "来源标题", "url": "https://example.com/a",
                            "observed_at": day}}
    with engine.begin() as connection:
        ensure_settings(connection)
        run = stage_candidate(connection, day=day, product_type="image",
                              candidate=candidate, angle="沟通")
        plan = {"main_title": "好好说话让关系更近", "alternative_titles": ["认真听完对方的话", "争执后如何和好"],
                "image_text": "慢一点说", "caption": "留出说话的空间", "tags": ["家庭", "沟通", "生活"],
                "strategy": "家庭情感", "reason": "围绕对话"}
        connection.execute(runs.update().where(runs.c.id == run["id"]).values(
            titles_json=json.dumps(plan, ensure_ascii=False), status="title_ready"))
        connection.execute(settings.update().where(settings.c.id == 1).values(
            emergency_stop=False, automatic_selection=True, cost_bound_verified=True,
            automatic_images=True, automatic_image_publish=True,
            daily_budget_micros=1000, title_call_bound_micros=100,
            image_call_bound_micros=300, vision_call_bound_micros=50,
            image_limit=1, tracks_json='["情感"]'))
        from server.content_factory_v3_store import queue_production
        queue_production(connection, run_id=run["id"], day=day)
    stream = io.BytesIO()
    # The provider may return an auto-composed square. The pipeline must
    # normalize it to 3:4 before deterministic text layout.
    Image.new("RGB", (300, 300), "navy").save(stream, format="PNG")
    provider_context = {}
    def generate(payload):
        from server.providers import call_context
        provider_context.update(call_context.current())
        return {"data": [{"b64_json": base64.b64encode(stream.getvalue()).decode()}]}
    monkeypatch.setattr(tasks.image_provider, "generate", generate)
    checks = {name: True for name in ("subject_clear", "single_focus", "colors_coherent",
                                     "distortion_free", "text_readable", "title_consistent",
                                     "copyright_safe", "no_watermark", "no_logo",
                                     "no_ip_character", "safe_content")}
    monkeypatch.setattr(tasks, "review_image", lambda *args, **kwargs: {
        "status": "success", "checks": checks, "issues": []})
    monkeypatch.setattr(tasks.creator_tools, "detect_article", lambda *args, **kwargs: quality_result())
    result = tasks.produce_draft.run(run["id"])
    assert result["status"] == "published"
    with engine.connect() as connection:
        report = connection.execute(quality_reports.select().where(
            quality_reports.c.run_id == run["id"])).mappings().one()
        product = connection.execute(products.select().where(
            products.c.id == result["product_id"])).mappings().one()
    assert product["status"] == "published"
    assert '"vision"' in report["report_json"]
    assert provider_context["idempotency_key"] == f"factory-v3:image:{run['id']}:0"
