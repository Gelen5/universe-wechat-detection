"""点击「选这版，生成原创图」→ 必须落在「03 成图交付」并开始计时。

真实体验里这一步以前会停在「01 拆解报告」：生成结果被 prepend 到 #viral-remix-result
（面板外），只有 MutationObserver 偶尔把节点搬进成图交付，且整块重绘会重置回 01。
这个测试锁住：点击后立刻切到 03、面板里有计时器、出图后仍停在 03、成图与配文都在面板内。

运行：cd 仓库根 && python tests/test_remix_output_tab.py
依赖：playwright（pip install playwright && playwright install chromium）
"""
import functools
import http.server
import io
import json
import socketserver
import threading
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PORT = 8130
FIXTURE_PATH = "/__remix_fixture.png"


def _fixture_bytes(colour):
    stream = io.BytesIO()
    Image.new("RGB", (60, 80), colour).save(stream, "PNG")
    return stream.getvalue()


FIXTURES = {FIXTURE_PATH: _fixture_bytes("#21744c")}


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        body = FIXTURES.get(self.path.split("?")[0])
        if body is None:
            return super().do_GET()
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # 静音访问日志
        pass


FAKE_RESULT = {
    "content_guess": "测试对标图",
    "analysis": {
        "visual_anchor": "大字标题", "hierarchy": "上中下", "composition": "居中",
        "palette": "米色", "emotion": "被点醒", "hook": "数字反差",
        "texture": "纸质", "platform_language": "小红书",
    },
    "missing": "无",
    "ideas": [{
        "id": "A", "name": "方案A", "summary": "换角度",
        "keep": "结构", "change": "画面", "why_original": "不同主体",
    }],
    "copy_directions": ["方向一"],
    "tags": ["#测试"],
    "order": ["1"],
    "pages": [],
    "claims": [],
}

FAKE_IMAGE = {
    "url": FIXTURE_PATH,
    "index": 1,
    "prompt": "test prompt",
    "check_passed": True,
    "check": "ok",
    "copy_directions": ["方向一"],
    "tags": ["#测试"],
    "images": [
        {"url": FIXTURE_PATH, "index": 1, "prompt": "p1", "check_passed": True, "check": "ok"},
        {"url": FIXTURE_PATH, "index": 2, "prompt": "p2", "check_passed": True, "check": "ok"},
    ],
}

BOOT = """
([result, image, delayMs]) => {
    currentAccount = { id: 'test-account', display_name: 'T' };
    document.querySelectorAll('.account-modal, #auth-modal').forEach(n => n.hidden = true);
    document.querySelectorAll('main section[id]').forEach(n => { n.hidden = n.id !== 'viral-remix'; });
    const view = document.querySelector('#viral-remix');
    view.hidden = false;
    let p = view.parentElement;
    while (p && p !== document.body) { p.hidden = false; p = p.parentElement; }
    // 模拟真实生图耗时，才能观察到成图交付里的计时器。
    window.postCreator = () => new Promise(resolve => setTimeout(() => resolve({ image }), delayMs));
    window.renderViralRemix(result, 'sess-test');
}
"""
SELECTED = """() => [...document.querySelectorAll('#viral-remix .remix-result-tabs button')]
    .findIndex(b => b.getAttribute('aria-selected') === 'true')"""
CLICK_TAB = "i => document.querySelectorAll('#viral-remix .remix-result-tabs button')[i].click()"
CLICK_GENERATE = "() => document.querySelector('#viral-remix .viral-generate').click()"
WAIT_TEXT = "() => document.querySelector('#remix-output-panel .remix-output-wait .wait-elapsed')?.textContent || ''"
COUNTS = """() => ({
    images: document.querySelectorAll('#remix-output-panel .viral-generated').length,
    delivery: document.querySelectorAll('#remix-output-panel .viral-delivery').length,
    stray: document.querySelectorAll('#viral-remix-result > .viral-generated').length,
    wait: document.querySelectorAll('#remix-output-panel .remix-output-wait').length,
    reportHidden: document.querySelector('#remix-report-panel').hidden,
    outputHidden: document.querySelector('#remix-output-panel').hidden,
    downloads: [...document.querySelectorAll('#remix-output-panel .viral-generated a')].map(a => a.getAttribute('download')),
})"""


def serve():
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def main():
    httpd = serve()
    failures = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{PORT}/static/index.html", wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            page.evaluate(BOOT, [FAKE_RESULT, FAKE_IMAGE, 2500])
            page.wait_for_timeout(150)

            if page.evaluate(SELECTED) != 0:
                failures.append(f"初始面板应为 0（拆解报告），实际 {page.evaluate(SELECTED)}")

            # 真实路径：先切到 02 翻新方案，再点其中的生成按钮。
            page.evaluate(CLICK_TAB, 1)
            page.wait_for_timeout(80)
            if page.evaluate(SELECTED) != 1:
                failures.append(f"应能切到 1（翻新方案），实际 {page.evaluate(SELECTED)}")

            page.evaluate(CLICK_GENERATE)
            page.wait_for_timeout(120)

            if page.evaluate(SELECTED) != 2:
                failures.append(f"点击生成后应立即落到 2（成图交付），实际 {page.evaluate(SELECTED)}")
            first = page.evaluate(WAIT_TEXT)
            if "已等待" not in first:
                failures.append(f"成图交付面板里没有出现计时器，实际文本：{first!r}")

            page.wait_for_timeout(1200)
            second = page.evaluate(WAIT_TEXT)
            if second == first:
                failures.append(f"计时器没有走动：{first!r} -> {second!r}")

            page.wait_for_function(
                "() => document.querySelectorAll('#remix-output-panel .viral-delivery').length > 0",
                timeout=15000,
            )
            page.wait_for_timeout(250)

            if page.evaluate(SELECTED) != 2:
                failures.append(f"生成完成后应停在 2（成图交付），实际 {page.evaluate(SELECTED)}")
            counts = page.evaluate(COUNTS)
            if counts["images"] != 2:
                failures.append(f"成图交付应有 2 张原创图，实际 {counts['images']}")
            if counts["delivery"] != 1:
                failures.append(f"成图交付应有 1 份配文块，实际 {counts['delivery']}")
            if counts["stray"]:
                failures.append(f"不应有游离在面板外的成图节点，实际 {counts['stray']}")
            if counts["wait"]:
                failures.append("生成完成后计时块应已移除")
            if not counts["reportHidden"] or counts["outputHidden"]:
                failures.append(
                    f"面板可见性错误：报告隐藏={counts['reportHidden']} 交付隐藏={counts['outputHidden']}"
                )
            if any(not (name or "").endswith(".png") for name in counts["downloads"]):
                failures.append(f"下载文件名不正确：{counts['downloads']}")

            # 同账号重复触发 account-changed（切窗口、钱包刷新）不该把面板重置回 01。
            page.evaluate("() => window.dispatchEvent(new Event('account-changed'))")
            page.wait_for_timeout(250)
            if page.evaluate(SELECTED) != 2:
                failures.append(f"同账号 account-changed 后应保持 2（成图交付），实际 {page.evaluate(SELECTED)}")

            # 再生成一次，仍要回到成图交付。
            page.evaluate(CLICK_TAB, 1)
            if page.evaluate(SELECTED) != 1:
                failures.append("手动点「02 翻新方案」没生效")
            page.evaluate(CLICK_GENERATE)
            page.wait_for_timeout(180)
            if page.evaluate(SELECTED) != 2:
                failures.append(f"第二次生成也应落到 2（成图交付），实际 {page.evaluate(SELECTED)}")
            page.wait_for_function(
                "() => document.querySelectorAll('#remix-output-panel .viral-delivery').length >= 2",
                timeout=15000,
            )
            if page.evaluate(SELECTED) != 2:
                failures.append(f"第二次生成完成后应停在 2（成图交付），实际 {page.evaluate(SELECTED)}")

            if errors:
                failures.append(f"页面 JS 报错：{errors[:3]}")
            browser.close()
    finally:
        httpd.shutdown()

    if failures:
        print("FAILED")
        for item in failures:
            print(" -", item)
        raise SystemExit(1)
    print("PASSED: 点击生成 -> 03 成图交付 -> 计时 -> 出图")


if __name__ == "__main__":
    main()
