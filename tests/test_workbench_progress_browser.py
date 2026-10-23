"""长任务必须看得见进度：热点/搜索/生成/保存 + 已等待时长。"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]


def test_progress_steps_are_visible_while_running():
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
            messages.append({"role": "user", "content": request.post_data_json["content"],
                             "content_json": request.post_data_json["content_json"]})
            data = {"run_id": "run-1"}
        elif path == "/api/conversations/conv-1/messages":
            data = {"messages": messages}
        elif path == "/api/conversations/conv-1/artifacts":
            data = {"artifacts": []}
        elif path.startswith("/api/runs/") and path.endswith("/events"):
            # 故意不发 run.completed：模拟"还在跑"，让进度面板保持可见
            body = (
                'event: stage.resolved\n'
                'data: {"payload":{"stage":"topic","reason":"先给你一批选题",'
                '"source":"model","confidence":0.99}}\n\n'
                'event: tool.started\n'
                'data: {"payload":{"tool_name":"search_topics"}}\n\n'
                'event: tool.progress\n'
                'data: {"payload":{"step":"hotspots","status":"available","count":12}}\n\n'
                'event: tool.progress\n'
                'data: {"payload":{"step":"search","status":"ok","count":3}}\n\n'
                'event: tool.progress\n'
                'data: {"payload":{"step":"generating","status":"running"}}\n\n'
            )
            route.fulfill(body=body, content_type="text/event-stream")
            return
        elif path.startswith("/api/runs/"):
            data = {"run": {"status": "running", "stage": "topic"}}
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

            card = page.locator("#workbench-action-card")
            card.locator(".chat-steps").wait_for(timeout=10000)
            page.locator("#chat-elapsed").wait_for(timeout=5000)

            done = page.locator('.chat-steps li[data-state="done"]')
            page.wait_for_function("() => document.querySelectorAll('.chat-steps li[data-state=\\'done\\']').length >= 2",
                                   timeout=10000)
            assert done.count() >= 2

            steps_text = card.inner_text()
            assert "抓取热点" in steps_text and "搜索参考" in steps_text and "生成方向" in steps_text
            assert "生成中" in page.locator("#workbench-progress-detail").inner_text()
            assert "已等待" in page.locator("#chat-elapsed").inner_text()
            assert not errors, errors
        finally:
            browser.close()
