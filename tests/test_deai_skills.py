"""Standalone de-AI tool and imported skill library."""
from __future__ import annotations

import contextlib
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import tests.support  # noqa: F401 - isolate the account database before app import

from server import accounts, deai, deai_tasks, skill_api, skills_catalog, workbench
from server.main import app


def create_client(points: int = 100) -> tuple[TestClient, dict]:
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:10]
    response = client.post(
        "/api/auth/register",
        json={
            "email": f"deai-skill-{suffix}@example.com",
            "password": "testing-pass-123",
            "display_name": "去AI味测试",
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


class TestCatalog:
    def test_library_contains_imported_six_skills(self):
        skills = skills_catalog.list_all()
        assert len(skills) == 6
        names = {item["name"] for item in skills}
        assert "知乎盐选故事创作" in names
        assert "爆款标题" in names
        assert {group["name"] for group in skills_catalog.groups()} == {"创作增强", "视觉生成"}

    def test_story_skill_runs_plan_stage_not_full_novel(self):
        story = next(item for item in skills_catalog.list_all() if item["directoryPath"] == "zhihu-story")
        prompt, _ = skills_catalog.build_prompt(story["id"], "写一个租房发现秘密的故事")
        assert "只执行 Step 0 和 Step 1" in prompt
        assert "不要直接写全文" in prompt

    def test_missing_prompt_gets_local_execution_rules(self):
        title = next(item for item in skills_catalog.list_all() if item["name"] == "爆款标题")
        prompt, _ = skills_catalog.build_prompt(title["id"], "AI 写作")
        assert "30 个可直接使用的标题" in prompt


class TestDeaiBilling:
    def test_points_scale_by_started_thousand_characters(self):
        assert deai.points_for("短文本") == 3
        assert deai.points_for("字" * 1001) == 6
        assert deai.points_for("字" * 20000) == 30

    def test_run_job_marks_all_steps_done(self):
        report = {"gate": "passed", "summary": "完成", "audit": {"status": "success"}}
        with patch.object(workbench, "_review", return_value=("改写后的正文", report)), \
             patch.object(accounts, "progress_job"):
            result = deai.run_job("job-test", {
                "content": "原文内容" * 10,
                "mode": "article",
                "depth": 5,
                "version": "V3.1",
            })
        assert result["content"] == "改写后的正文"
        assert result["progress"] == 100
        assert [step["status"] for step in result["steps"]] == [2, 2, 2, 2]

    def test_anchor_failure_falls_back_to_full_rewrite(self):
        article = "这是一段需要去 AI 味的中文原文，这句话只是用来触发兜底改写流程。"
        with patch.object(
            workbench, "_review",
            side_effect=workbench.ProviderError(
                "去 AI 复核问题未能定位到当前稿的逐字连续片段，已保留原文"
            ),
        ), patch.object(
            deai, "_fallback_rewrite",
            return_value="这是一段更自然的中文原文，这句话只是用来验证兜底改写流程。",
        ), patch.object(accounts, "progress_job"):
            result = deai.run_job("job-fallback", {
                "content": article,
                "mode": "article",
                "depth": 10,
                "version": "V2",
            })
        assert result["gate"] == "fallback_passed"
        assert "全文改写" in result["content"] + result["summary"]
        assert [step["status"] for step in result["steps"]] == [2, 2, 2, 2]

    def test_fallback_rejects_lost_numbers(self):
        with patch.object(workbench, "_text", return_value="改写后丢了关键数字的正文内容。" * 4):
            with pytest.raises(ValueError, match="丢失原文数字"):
                deai._fallback_rewrite(
                    "原文提到增长 42%，这是一段足够长的测试正文，用于验证数字保护。",
                    mode="article", depth=8, version="V3.1",
                )

    def test_worker_success_charges_once(self):
        client, user = create_client(points=100)
        with patch.object(deai, "dispatch", return_value="task-id"):
            created = client.post("/api/deai/tasks", json={
                "content": "这是一段需要去 AI 味的中文原文，用来验证计费和任务状态。" * 4,
                "idempotency_key": "deai-worker-1",
            })
        assert created.status_code == 202, created.text
        job_id = created.json()["job"]["id"]
        assert balance(user["id"]) == 97
        with patch.object(deai, "run_job", return_value={
            "content": "改写结果",
            "original": "原文",
            "progress": 100,
            "steps": [],
            "results": [{"content": "改写结果"}],
        }), patch.object(workbench, "provider_overrides", return_value=contextlib.nullcontext()):
            assert deai_tasks.run.apply(args=[job_id]).get()["status"] == "succeeded"
        assert balance(user["id"]) == 97

    def test_api_requires_login(self):
        client = TestClient(app)
        assert client.get("/api/deai/tasks").status_code == 401
        assert client.get("/api/skill-library").status_code == 401


class TestSkillApi:
    def test_list_and_detail(self):
        client, _ = create_client()
        listing = client.get("/api/skill-library")
        assert listing.status_code == 200
        assert len(listing.json()["skills"]) == 6
        skill_id = listing.json()["skills"][0]["id"]
        detail = client.get(f"/api/skill-library/{skill_id}")
        assert detail.status_code == 200
        assert detail.json()["skill"]["promptPreview"]

    def test_run_uses_catalog_prompt(self):
        client, _ = create_client()
        skill_id = skills_catalog.list_all()[-1]["id"]
        with patch.object(workbench, "_text", return_value="生成结果") as text:
            response = client.post(f"/api/skill-library/{skill_id}/run", json={"input": "AI 写作"})
        assert response.status_code == 200
        assert response.json()["content"] == "生成结果"
        assert "30 个可直接使用的标题" in text.call_args.args[0]
