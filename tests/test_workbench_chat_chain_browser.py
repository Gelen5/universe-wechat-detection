"""整条链路必须能在对话流里走完，而不是靠右侧画布的隐藏按钮。"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]


def test_full_chain_driven_from_the_chat_thread():
    messages = []
    artifacts = []
    stages_sent = []

    def add_artifact(kind, content, content_json=None):
        artifacts.append({
            "id": f"artifact-{len(artifacts) + 1}", "type": kind, "title": "测试作品",
            "content": content, "content_json": content_json or {}, "version": 1,
            "run_id": f"run-{len(stages_sent)}", "created_at": "2026-10-20T00:00:01Z",
            "updated_at": "2026-10-20T00:00:01Z",
        })

    def route_request(route):
        request = route.request
        path = urlparse(request.url).path
        if path.startswith("/static/") or path in ("/", "/workbench"):
            file = ROOT / path.lstrip("/") if path.startswith("/static/") else ROOT / "static/index.html"
            if not file.is_file():
                route.fulfill(status=404, body="")
                return
            mime = {".html": "text/html", ".js": "application/javascript", ".css": "text/css"}
            route.fulfill(body=file.read_bytes(), content_type=mime.get(file.suffix, "application/octet-stream"))
            return
        if path == "/api/skills":
            data = {"skills": []}
        elif path == "/api/conversations" and request.method == "POST":
            data = {"conversation": {"id": "conv-1", "mode": "manual", "skill_id": "wechat_writer"}}
        elif path == "/api/conversations/conv-1":
            data = {"conversation": {"id": "conv-1", "mode": "manual", "skill_id": "wechat_writer"}}
        elif path == "/api/conversations/conv-1/messages" and request.method == "POST":
            payload = request.post_data_json
            stage = payload["content_json"]["workflow_stage"]
            stages_sent.append(stage)
            messages.append({"role": "user", "content": payload["content"],
                             "content_json": payload["content_json"]})
            messages.append({"role": "assistant", "content": "当前阶段已完成，请查看作品区。"})
            if stage == "topic":
                add_artifact("topic", "1. 方向甲\n2. 方向乙",
                             {"topics": [{"title": "方向甲"}, {"title": "方向乙"}]})
            elif stage == "outline":
                add_artifact("outline", "1. 开头\n2. 结尾",
                             {"framework": {"name": "SCQA", "outline": ["开头", "结尾"]}})
            elif stage == "writing":
                add_artifact("article", "# 测试文章\n正文")
            elif stage == "deai":
                add_artifact("article", "# 测试文章\n修订正文")
                add_artifact("report", "表达已复核", {"review": {"status": "passed"}})
            elif stage == "typeset":
                add_artifact("html", "<!doctype html><html><body><h1>排版预览</h1></body></html>")
            data = {"run_id": f"run-{len(stages_sent)}"}
        elif path == "/api/conversations/conv-1/messages":
            data = {"messages": messages}
        elif path == "/api/conversations/conv-1/artifacts":
            data = {"artifacts": artifacts}
        elif path.startswith("/api/runs/") and path.endswith("/events"):
            route.fulfill(body='event: run.completed\ndata: {"payload":{}}\n\n',
                          content_type="text/event-stream")
            return
        elif path.startswith("/api/runs/"):
            data = {"run": {"status": "completed"}}
        elif path == "/api/auth/me":
            data = {"user": {"id": "user-1", "display_name": "测试用户", "role": "user"}}
        else:
            data = {}
        route.fulfill(body=json.dumps(data, ensure_ascii=False), content_type="application/json")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True,
            executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("http://workbench.test/**", route_request)
            page.goto("http://workbench.test/workbench")
            page.evaluate("document.querySelector('#auth-modal').hidden = true; setActiveView('workbench')")

            page.locator("#workbench-topic").fill("写一篇给职场人的 AI 工具实测")
            page.locator("#start-workbench").click()

            # 方向只在左侧选题工作区完整展示；对话卡只负责引导，不重复清单。
            page.locator("#workbench-action-card [data-topic-choice]").wait_for(state="detached", timeout=10000)
            page.locator("#workbench-stage-choices [data-topic-choice]").first.wait_for(timeout=10000)
            page.locator("#workbench-stage-choices [data-topic-choice]").first.click()

            for stage in ("outline", "writing", "deai", "typeset"):
                button = page.locator(f'#workbench-action-card [data-next-stage="{stage}"]')
                button.wait_for(timeout=10000)
                button.click()

            page.locator("#workbench-action-card [data-copy-html]").wait_for(timeout=10000)
            assert stages_sent == ["topic", "outline", "writing", "deai", "typeset"], stages_sent
            card = page.locator("#workbench-action-card").inner_text()
            assert "复制 HTML" in card
            assert not errors, errors
        finally:
            browser.close()
