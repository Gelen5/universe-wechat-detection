"""Regression: the chat action card must follow the artifact chain.

Supplying the topic in the first message skips candidate selection, so such a
conversation has an outline (and later an article) but no topic artifact. The
card used to stop at "outline ready" forever, and before that it fell back to
"tell me what to write" even though the draft already existed.
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def _artifact(kind: str, content: str, index: int, content_json=None):
    return {
        "id": f"artifact-{index}", "type": kind, "title": "测试作品",
        "content": content, "content_json": content_json or {}, "version": 1,
        "run_id": f"run-{index}",
        "created_at": f"2026-10-20T00:00:{index:02d}Z",
        "updated_at": f"2026-10-20T00:00:{index:02d}Z",
    }


def _open_workbench(artifacts, messages):
    """Serve the shell and the conversation API, then render the workbench."""
    def route_request(route):
        request = route.request
        path = urlparse(request.url).path
        if path.startswith("/static/") or path in ("/", "/workbench"):
            file = ROOT / path.lstrip("/") if path.startswith("/static/") else ROOT / "static/index.html"
            if not file.is_file():
                route.fulfill(status=404, body="")
                return
            mime = {".html": "text/html", ".js": "application/javascript", ".css": "text/css"}
            route.fulfill(body=file.read_bytes(),
                          content_type=mime.get(file.suffix, "application/octet-stream"))
            return
        if path == "/api/conversations" and request.method == "POST":
            data = {"conversation": {"id": "conv-1", "mode": "manual", "skill_id": "wechat_writer"}}
        elif path == "/api/conversations/conv-1":
            data = {"conversation": {"id": "conv-1", "mode": "manual", "skill_id": "wechat_writer"}}
        elif path == "/api/conversations/conv-1/messages":
            data = {"messages": messages}
        elif path == "/api/conversations/conv-1/artifacts":
            data = {"artifacts": artifacts}
        elif path == "/api/auth/me":
            data = {"user": {"id": "user-1", "display_name": "测试用户", "role": "user"}}
        elif path == "/api/skills":
            data = {"skills": []}
        else:
            data = {}
        route.fulfill(body=json.dumps(data, ensure_ascii=False), content_type="application/json")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=CHROME)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("http://workbench.test/**", route_request)
            page.goto("http://workbench.test/workbench?conversation=conv-1")
            page.evaluate("document.querySelector('#auth-modal').hidden = true; setActiveView('workbench')")
            card = page.locator("#workbench-action-card")
            card.wait_for(timeout=10000)
            # The card renders once before artifacts arrive; wait until the
            # loaded artifacts have replaced the empty-state text.
            page.wait_for_function(
                """() => {
                    const card = document.querySelector('#workbench-action-card');
                    return card && !card.innerText.includes('先告诉我你想写什么');
                }""",
                timeout=10000,
            )
            text = card.inner_text()
            assert not errors, errors
            return text
        finally:
            browser.close()


USER_MESSAGE = [{"role": "user", "content": "写一篇给 30 岁职场人的 AI 工具实测",
                 "content_json": {}}]


def test_outline_without_topic_offers_writing():
    text = _open_workbench(
        [_artifact("outline", "1. 开头\n2. 结尾", 1,
                   {"framework": {"name": "SCQA", "outline": ["开头", "结尾"]}})],
        USER_MESSAGE,
    )
    assert "下一步" in text and "写作" in text, text
    assert "先告诉我你想写什么" not in text, text


def test_written_article_without_topic_moves_on_to_deai():
    text = _open_workbench(
        [
            _artifact("outline", "1. 开头\n2. 结尾", 1,
                      {"framework": {"name": "SCQA", "outline": ["开头", "结尾"]}}),
            _artifact("article", "# 标题\n\n正文内容", 2),
        ],
        USER_MESSAGE,
    )
    # The bug: this kept saying "大纲已就绪" after the draft was finished.
    assert "大纲已就绪" not in text, text
    assert "下一步" in text and "去 AI" in text, text
