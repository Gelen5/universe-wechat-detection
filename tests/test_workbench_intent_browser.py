"""输入框里的阶段由模型判断，前端不再按关键词猜。"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]


def artifacts():
    stamp = "2026-10-20T00:00:01Z"
    return [
        {"id": "a-topic", "type": "topic", "title": "选题", "version": 1,
         "content": "1. 方向甲", "content_json": {"topics": [{"title": "方向甲"}]},
         "run_id": "run-0", "created_at": stamp, "updated_at": stamp},
        {"id": "a-outline", "type": "outline", "title": "大纲", "version": 1,
         "content": "1. 开头\n2. 结尾", "content_json": {"framework": {"name": "SCQA"}},
         "run_id": "run-0", "created_at": stamp, "updated_at": stamp},
        {"id": "a-article", "type": "article", "title": "正文", "version": 1,
         "content": "# 正文", "content_json": {}, "run_id": "run-0",
         "created_at": stamp, "updated_at": stamp},
        {"id": "a-html", "type": "html", "title": "排版", "version": 1,
         "content": "<html><body><h1>排版预览</h1></body></html>", "content_json": {},
         "run_id": "run-0", "created_at": stamp, "updated_at": stamp},
    ]


def test_model_decision_moves_the_tab_and_explains_why():
    posted = []
    messages = []

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
            posted.append(payload)
            messages.append({"role": "user", "content": payload["content"],
                             "content_json": payload["content_json"]})
            messages.append({"role": "assistant", "content": "已理解：先给你 10 个选题",
                             "content_json": {"kind": "stage_note", "stage": "topic"}})
            data = {"run_id": "run-1"}
        elif path == "/api/conversations/conv-1/messages":
            data = {"messages": messages}
        elif path == "/api/conversations/conv-1/artifacts":
            data = {"artifacts": artifacts()}
        elif path.startswith("/api/runs/") and path.endswith("/events"):
            body = (
                'event: stage.resolved\n'
                'data: {"payload":{"stage":"topic","reason":"先给你 10 个选题",'
                '"source":"model","direction":"AI 相关"}}\n\n'
                'event: run.completed\n'
                'data: {"payload":{}}\n\n'
            )
            route.fulfill(body=body, content_type="text/event-stream")
            return
        elif path.startswith("/api/runs/"):
            data = {"run": {"status": "completed", "stage": "topic"}}
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

            # 先站在 03 写作这一步
            page.locator('[data-workbench-stage="writing"]').click()
            assert page.locator("#workbench-stage-title").inner_text() == "写作"

            page.locator("#workbench-topic").fill("我准备写一篇关于AI相关的文章 给我下选题")
            page.locator("#start-workbench").click()

            # 前端必须把"当前标签"当提示发出去，而不是自己按"写一篇"切阶段
            page.wait_for_timeout(600)
            assert posted, "message was not sent"
            assert posted[0]["content_json"]["workflow_stage"] == "writing"
            assert posted[0]["content_json"]["stage_explicit"] is False

            # 模型判定后：tab 跟着模型走，并在对话里说明原因
            page.locator("#workbench-stage-title").get_by_text("选题").wait_for(timeout=10000)
            note = page.locator(".chat-message.is-note").first
            note.wait_for(timeout=5000)
            assert "已理解" in note.inner_text()
            assert not errors, errors
        finally:
            browser.close()
