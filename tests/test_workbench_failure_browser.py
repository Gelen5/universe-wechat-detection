"""失败必须出现在对话流里，并且能原地重试（这条路径以前完全没有覆盖）。"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
FAILURE_TEXT = ("「选题」这一步没有跑完。\n原因：抓取热点的脚本超时或被网络拦截。\n"
                "这通常是一次性的，直接重试即可。\n"
                "本轮积分已自动退回，已完成的阶段不会丢。可以点下面的「重试这一步」。")


def test_failed_stage_is_visible_and_retryable():
    messages = []
    sent = []
    runs = {}

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
            sent.append(payload)
            messages.append({"role": "user", "content": payload["content"],
                             "content_json": payload["content_json"]})
            run_id = f"run-{len(sent)}"
            if len(sent) == 1:
                messages.append({
                    "role": "assistant", "content": FAILURE_TEXT,
                    "content_json": {"kind": "run_failed", "stage": "topic", "run_id": run_id,
                                     "error_code": "topic_source", "retryable": True},
                })
            runs[run_id] = "failed" if len(sent) == 1 else "completed"
            data = {"run_id": run_id}
        elif path == "/api/conversations/conv-1/messages":
            data = {"messages": messages}
        elif path == "/api/conversations/conv-1/artifacts":
            data = {"artifacts": []}
        elif path.startswith("/api/runs/") and path.endswith("/events"):
            run_id = path.split("/")[-2]
            event = "run.failed" if runs.get(run_id) == "failed" else "run.completed"
            route.fulfill(body=f'event: {event}\ndata: {{"payload":{{}}}}\n\n',
                          content_type="text/event-stream")
            return
        elif path.startswith("/api/runs/"):
            run_id = path.split("/")[-1]
            data = {"run": {"id": run_id, "status": runs.get(run_id, "completed"),
                            "error_code": "topic_source", "error_kind": "topic_source"}}
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

            failure = page.locator(".chat-message.is-failure").first
            failure.wait_for(timeout=10000)
            assert "选题" in failure.inner_text()
            assert "积分" in failure.inner_text()
            page.locator('[data-retry-stage="topic"]').first.wait_for(timeout=5000)

            page.locator('[data-retry-stage="topic"]').first.click()
            page.wait_for_function("() => true")
            page.wait_for_timeout(800)
            assert len(sent) == 2, sent
            # 重试沿用原方向，不能被"给我一些可以写的选题"这种默认句覆盖
            assert sent[0]["content_json"]["topic_direction"] == sent[1]["content_json"]["topic_direction"]
            assert sent[1]["content_json"]["workflow_stage"] == "topic"
            assert not errors, errors
        finally:
            browser.close()
