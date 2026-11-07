"""爆文复刻：链接安全、正文解析、事实守卫、去 AI 味与异步计费。"""
from __future__ import annotations

import contextlib
import json
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import tests.support  # noqa: F401 - isolate the account database before app import

from server import accounts, viral_article, viral_article_tasks, workbench
from server.main import app


def create_client(points: int = 100) -> tuple[TestClient, dict]:
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:10]
    response = client.post(
        "/api/auth/register",
        json={
            "email": f"viral-article-{suffix}@example.com",
            "password": "testing-pass-123",
            "display_name": "爆文复刻测试",
        },
    )
    assert response.status_code == 200, response.text
    user = response.json()["user"]
    with accounts._connect() as connection:
        connection.execute(
            "UPDATE wallets SET balance=?, trial_balance=?, bonus_balance=0, paid_balance=0 "
            "WHERE user_id=?",
            (points, points, user["id"]),
        )
    return client, user


def balance(user_id: str) -> int:
    return int(accounts.wallet_summary(user_id)["balance"])


class TestUrlContract:
    def test_deduplicates_fragments_and_limits_to_ten(self):
        raw = (
            "https://Example.com/a#section\n"
            "https://example.com/a\n"
            + "\n".join(f"https://example.com/post-{i}" for i in range(12))
        )
        urls = viral_article.extract_urls(raw)
        assert len(urls) == 10
        assert urls[0] == "https://example.com/a"
        assert len(set(urls)) == len(urls)

    @pytest.mark.parametrize("value", [
        "http://127.0.0.1/a",
        "http://localhost/a",
        "http://10.0.0.2/a",
        "https://user:pass@example.com/a",
        "https://example.com:99999/a",
        "ftp://example.com/a",
    ])
    def test_rejects_unsafe_or_invalid_links(self, value):
        with pytest.raises(ValueError):
            viral_article.extract_urls(value)


class TestArticleParsing:
    def test_extracts_title_body_metadata_and_images(self):
        paragraphs = "".join(
            f"<p>第{i}段正文，说明一个具体事实和读者关心的问题。</p>" for i in range(8)
        )
        html = f"""
        <html><head>
          <title>页面标题</title>
          <meta property="og:title" content="完整文章标题">
          <meta name="author" content="作者甲">
          <meta property="article:published_time" content="2026-11-07">
        </head><body>
          <article><h1>完整文章标题</h1>{paragraphs}
            <img data-src="/images/one.jpg" alt="配图一">
          </article>
        </body></html>
        """
        article = viral_article.parse_article_html(html, "https://example.com/post")
        assert article["title"] == "完整文章标题"
        assert article["author"] == "作者甲"
        assert article["platform"] == "其他图文站点"
        assert "第7段正文" in article["content_markdown"]
        assert article["images"] == [
            {"url": "https://example.com/images/one.jpg", "alt": "配图一"}
        ]
        assert len(article["content_sha256"]) == 64

    def test_login_wall_without_body_is_rejected(self):
        with pytest.raises(ValueError, match="正文过短|反爬"):
            viral_article.parse_article_html(
                "<html><body><p>请登录后查看完整内容</p></body></html>",
                "https://example.com/post",
            )


class TestFactGuard:
    def test_numbers_absent_from_sources_are_flagged(self):
        sources = [{
            "source_url": "https://example.com/source",
            "title": "来源",
            "content_markdown": "来源提到增长 42%。",
        }]
        content = "正文保留 42% 的增长率，但结论变成了99%的覆盖率。"
        assert viral_article.unsupported_numbers(content, sources, []) == ["99%"]

    def test_deai_rolls_back_when_it_invents_a_number(self):
        sources = [{
            "source_url": "https://example.com/source",
            "title": "来源",
            "content_markdown": "来源只提到增长 42%。",
        }]
        original = "原稿表达。" * 80 + "增长 42%。"
        invented = "更自然的表达。" * 80 + "增长 42%，又新增 99%。"
        with patch.object(viral_article, "_chat_json", return_value={"content": invented}):
            content, warning = viral_article.remove_ai_flavor_text(original, sources, [])
        assert content == original
        assert "未核实数字" in warning

    def test_deai_rolls_back_when_it_drops_a_source_number(self):
        sources = [{
            "source_url": "https://example.com/source",
            "title": "来源",
            "content_markdown": "来源只提到增长 42%。",
        }]
        original = "原稿表达。" * 80 + "增长 42%。"
        rewritten = "更自然的表达。" * 80 + "增长明显。"
        with patch.object(viral_article, "_chat_json", return_value={"content": rewritten}):
            content, warning = viral_article.remove_ai_flavor_text(original, sources, [])
        assert content == original
        assert "丢失了原文数字" in warning


def source(url: str) -> dict:
    return {
        "source_url": url,
        "final_url": url,
        "platform": "其他图文站点",
        "title": "来源标题",
        "author": "",
        "published_at": "",
        "content_markdown": "来源正文，提到增长 42%。" * 12,
        "images": [],
        "content_sha256": "a" * 64,
        "warnings": [],
    }


class TestPipeline:
    def test_partial_fetch_failure_continues_with_available_source(self):
        good = "https://example.com/good"
        bad = "https://example.com/bad"

        def fetch(url):
            if url == bad:
                raise ValueError("页面被拦截")
            return source(url)

        rewritten = {
            "title": "新角度成稿",
            "content": "新角度正文。" * 80 + "保留增长 42%。",
            "facts": [],
            "warnings": [],
            "sources": [{"url": good, "title": "来源标题"}],
            "images": [],
        }
        with patch.object(viral_article, "fetch_article", side_effect=fetch), \
             patch.object(viral_article, "rewrite_sources", return_value=rewritten), \
             patch.object(viral_article, "_write_progress"), \
             patch.object(viral_article, "_check_cancelled"):
            result = viral_article.run_job(
                "job-partial",
                {"urls": [good, bad], "remove_ai_flavor": False},
            )
        assert result["title"] == "新角度成稿"
        assert result["results"][0]["content"].startswith("新角度正文")
        assert any("部分来源抓取失败" in warning for warning in result["warnings"])
        assert [step["key"] for step in result["steps"]] == [
            "fetch", "images", "rewrite", "output",
        ]
        # The final snapshot must not freeze the last step as running.
        assert [step["status"] for step in result["steps"]] == [2, 2, 2, 2]

    def test_succeeded_job_reports_legacy_running_step_as_done(self):
        """Jobs created before the snapshot fix still render as completed."""
        legacy = {
            "id": "job-legacy",
            "status": "succeeded",
            "payload_json": "{}",
            "result_json": json.dumps({
                "title": "旧任务",
                "content": "正文",
                "results": [{"content": "正文"}],
                "progress": {"percent": 100, "steps": [
                    {"key": "fetch", "name": "分析内容", "status": 2},
                    {"key": "output", "name": "输出成稿", "status": 1},
                ]},
            }),
        }
        public = viral_article.public(legacy)
        assert public["progress"] == 100
        assert [step["status"] for step in public["steps"]] == [2, 2]

    def test_running_job_keeps_running_step(self):
        running = {
            "id": "job-running",
            "status": "running",
            "payload_json": "{}",
            "result_json": json.dumps({
                "progress": {"percent": 62, "steps": [
                    {"key": "output", "name": "输出成稿", "status": 1},
                ]},
            }),
        }
        public = viral_article.public(running)
        assert public["steps"][0]["status"] == 1

    def test_all_fetches_failing_raises_and_does_not_rewrite(self):
        with patch.object(viral_article, "fetch_article", side_effect=ValueError("blocked")), \
             patch.object(viral_article, "rewrite_sources") as rewrite, \
             patch.object(viral_article, "_write_progress"), \
             patch.object(viral_article, "_check_cancelled"):
            with pytest.raises(viral_article.ViralArticleError, match="抓取链接失败"):
                viral_article.run_job(
                    "job-failed",
                    {"urls": ["https://example.com/a"], "remove_ai_flavor": False},
                )
        rewrite.assert_not_called()


class TestApiAndBilling:
    def test_points_follow_remove_ai_flavor_option(self):
        assert viral_article.points_for(False) == 10
        assert viral_article.points_for(True) == 13

    def test_create_payload_idempotency_and_single_charge(self):
        client, user = create_client(points=100)
        body = {
            "urls": ["https://example.com/a"],
            "remove_ai_flavor": False,
            "new_angle": "从普通读者成本切入",
            "target_characters": 1500,
            "idempotency_key": "same-request-001",
        }
        with patch.object(viral_article, "dispatch", return_value="celery-task") as dispatch:
            first = client.post("/api/viral-article/tasks", json=body)
            second = client.post("/api/viral-article/tasks", json=body)
        assert first.status_code == 202, first.text
        assert second.status_code == 202, second.text
        assert first.json()["job"]["id"] == second.json()["job"]["id"]
        assert first.json()["job"]["points"] == {"reserved": 10, "charged": 0}
        assert balance(user["id"]) == 90, "接口层与全局中间件不能重复预扣"
        job = accounts.job(first.json()["job"]["id"], user["id"])
        assert job["payload_json"]
        assert '"remove_ai_flavor": false' in job["payload_json"]
        assert '"points": 10' in job["payload_json"]
        assert dispatch.call_count >= 1

    def test_create_with_remove_ai_flavor_reserves_thirteen_points(self):
        client, user = create_client(points=100)
        with patch.object(viral_article, "dispatch", return_value="celery-task"):
            created = client.post("/api/viral-article/tasks", json={
                "urls": ["https://example.com/a"],
                "remove_ai_flavor": True,
                "idempotency_key": "deai-price-001",
            })
        assert created.status_code == 202, created.text
        assert created.json()["job"]["points"] == {"reserved": 13, "charged": 0}
        assert balance(user["id"]) == 87

    def test_task_is_isolated_between_accounts(self):
        first_client, first_user = create_client(points=100)
        second_client, second_user = create_client(points=100)
        with patch.object(viral_article, "dispatch", return_value="celery-task"):
            created = first_client.post("/api/viral-article/tasks", json={
                "urls": ["https://example.com/a"],
                "idempotency_key": "owner-isolation-1",
            })
        assert created.status_code == 202, created.text
        job_id = created.json()["job"]["id"]
        assert first_client.get(f"/api/viral-article/tasks/{job_id}").status_code == 200
        assert second_client.get(f"/api/viral-article/tasks/{job_id}").status_code == 404
        assert accounts.job(job_id, second_user["id"]) is None
        assert first_user["id"] != second_user["id"]

    def test_cancel_queued_task_refunds_once(self):
        client, user = create_client(points=100)
        with patch.object(viral_article, "dispatch", return_value="celery-task"):
            created = client.post("/api/viral-article/tasks", json={
                "urls": ["https://example.com/a"],
                "idempotency_key": "cancel-queued-1",
            })
        assert created.status_code == 202, created.text
        job_id = created.json()["job"]["id"]
        usage_id = accounts.job(job_id, user["id"])["usage_id"]
        assert balance(user["id"]) == 87
        assert created.json()["job"]["points"]["reserved"] == 13
        first = client.post(f"/api/viral-article/tasks/{job_id}/cancel")
        second = client.post(f"/api/viral-article/tasks/{job_id}/cancel")
        assert first.status_code == 200
        assert first.json()["job"]["status"] == "canceled"
        assert first.json()["job"]["points"] == {"reserved": 13, "charged": 0}
        assert second.status_code == 200
        assert balance(user["id"]) == 100
        assert accounts.usage_state(usage_id) == "refunded"

    def test_worker_failure_marks_failed_and_refunds(self):
        client, user = create_client(points=100)
        with patch.object(viral_article, "dispatch", return_value="celery-task"):
            created = client.post("/api/viral-article/tasks", json={
                "urls": ["https://example.com/a"],
                "idempotency_key": "worker-failure-1",
            })
        assert created.status_code == 202, created.text
        job_id = created.json()["job"]["id"]
        usage_id = accounts.job(job_id, user["id"])["usage_id"]
        with patch.object(viral_article, "run_job", side_effect=RuntimeError("模型调用失败")), \
             patch.object(workbench, "provider_overrides", return_value=contextlib.nullcontext()):
            result = viral_article_tasks.run.apply(args=[job_id]).get()
        assert result["status"] == "failed"
        current = accounts.job(job_id, user["id"])
        assert current["status"] == "failed"
        assert current["error"] == "模型调用失败"
        assert balance(user["id"]) == 100
        assert accounts.usage_state(usage_id) == "refunded"

    def test_worker_duplicate_settlement_is_idempotent(self):
        client, user = create_client(points=100)
        with patch.object(viral_article, "dispatch", return_value="celery-task"):
            created = client.post("/api/viral-article/tasks", json={
                "urls": ["https://example.com/a"],
                "idempotency_key": "worker-duplicate-1",
            })
        job_id = created.json()["job"]["id"]
        usage_id = accounts.job(job_id, user["id"])["usage_id"]
        with patch.object(viral_article, "run_job", return_value={
            "title": "标题",
            "content": "正文" * 200,
            "results": [{"content": "正文" * 200}],
            "progress": 100,
        }), patch.object(workbench, "provider_overrides", return_value=contextlib.nullcontext()):
            assert viral_article_tasks.run.apply(args=[job_id]).get()["status"] == "succeeded"
            assert viral_article_tasks.run.apply(args=[job_id]).get()["status"] == "succeeded"
        assert balance(user["id"]) == 87
        assert accounts.usage_state(usage_id) == "completed"
        current = viral_article.public(accounts.job(job_id, user["id"]))
        assert current["points"] == {"reserved": 13, "charged": 13}
