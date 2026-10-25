"""Browser regression checks for shared navigation and responsive workspaces.

All requests are intercepted; these tests never call production or model APIs.
"""
import mimetypes
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as runtime:
        executable = os.getenv("CHROME_PATH")
        windows_chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        if not executable and windows_chrome.exists():
            executable = str(windows_chrome)
        instance = runtime.chromium.launch(headless=True, **({"executable_path": executable} if executable else {}))
        yield instance
        instance.close()


@pytest.fixture
def ui(browser):
    context = browser.new_context(viewport={"width": 390, "height": 900})
    state = {"requests": [], "errors": [], "fail_market": False}
    wallet = {"balance": 100, "trial_balance": 100, "paid_balance": 0, "bonus_balance": 0}
    conversation = {"id": "recent-1", "title": "真实会话测试记录", "mode": "manual", "skill_id": "wechat_writer", "updated_at": "2026-10-24T06:00:00Z"}

    def serve(route):
        parsed = urlparse(route.request.url)
        if parsed.hostname != "ui.test":
            route.abort()
            return
        path = parsed.path
        state["requests"].append(path)
        if path.startswith("/api/"):
            if path.startswith("/api/market/") and state["fail_market"]:
                route.fulfill(status=503, json={"detail": "测试索引暂不可用"})
                return
            if path == "/api/auth/me":
                data = {"user": {"id": "test-user", "display_name": "测试用户", "email": "test@example.com", "role": "user"}, "wallet": wallet}
            elif path == "/api/wallet":
                data = {"wallet": wallet}
            elif path == "/api/conversations":
                data = {"conversations": [conversation]}
            elif path == "/api/conversations/recent-1":
                data = {"conversation": conversation}
            elif path.endswith("/messages"):
                data = {"messages": []}
            elif path.endswith("/artifacts"):
                data = {"artifacts": []}
            elif path == "/api/skills":
                data = {"skills": []}
            elif path == "/api/qihaoshou/capabilities":
                data = {"styles": [{"id": "casual", "name": "自然叙述"}], "themes": [{"id": "default", "name": "默认"}], "pricing": [], "text": True, "image": False, "wechat": False}
            elif path == "/api/qihaoshou/sessions":
                data = {"sessions": []}
            elif path == "/api/market/meta":
                data = {"count": 0, "repos": 0, "official": 0, "categories": []}
            elif path.startswith("/api/market/"):
                data = {"items": [], "total": 0, "pages": 1}
            else:
                data = {}
            route.fulfill(json=data)
            return
        if path.startswith("/static/"):
            file = ROOT / path.lstrip("/")
        else:
            name = "bookshelf.html" if path.startswith("/bookshelf") else "market.html" if path == "/market" else "qihaoshou.html" if path == "/qihaoshou" else "index.html"
            file = ROOT / "static" / name
        if not file.is_file():
            route.fulfill(status=404, body="")
            return
        route.fulfill(body=file.read_bytes(), content_type=mimetypes.guess_type(str(file))[0] or "application/octet-stream")

    context.route("**/*", serve)
    page = context.new_page()
    page.on("pageerror", lambda error: state["errors"].append(str(error)))
    yield page, state
    assert not state["errors"], state["errors"]
    context.close()


@pytest.mark.parametrize("path", ["/", "/bookshelf", "/market", "/qihaoshou"])
def test_mobile_navigation_has_named_targets_and_more_menu(ui, path):
    page, _ = ui
    page.goto("http://ui.test" + path)
    nav = page.get_by_role("navigation", name="产品模块", exact=True)
    links = nav.locator("a:visible")
    expect(links).to_have_count(4)
    for link in links.all():
        assert link.get_attribute("aria-label")
        assert link.bounding_box()["width"] >= 44
    more = page.get_by_role("button", name="更多", exact=True)
    more.click()
    expect(page.get_by_role("dialog", name="全部功能")).to_be_visible()
    expect(page.get_by_role("navigation", name="全部功能").get_by_role("link")).to_have_count(11)
    page.keyboard.press("Escape")
    expect(more).to_be_focused()
    expect(more).to_have_attribute("aria-expanded", "false")


def test_writer_has_one_shell_and_correct_mobile_operation_order(ui):
    page, _ = ui
    page.goto("http://ui.test/one-click-writing")
    frame = page.frame_locator("#one-click-writing-frame")
    expect(frame.locator("#q-topic")).to_be_visible()
    expect(frame.locator(".shell-nav")).to_be_hidden()
    boxes = {name: frame.locator("." + name).bounding_box() for name in ("settings", "conversation", "editor")}
    assert boxes["settings"]["y"] < boxes["conversation"]["y"] < boxes["editor"]["y"]
    assert boxes["settings"]["y"] < 300
    assert boxes["settings"]["x"] + boxes["settings"]["width"] <= 391
    page.set_viewport_size({"width": 1440, "height": 900})
    sidebar = page.locator('.app-shell > .v3-topbar').bounding_box()
    workspace = page.locator('#one-click-writing-frame').bounding_box()
    assert workspace['x'] >= sidebar['x'] + sidebar['width']


@pytest.mark.parametrize("width", [390, 768, 1024, 1440])
def test_review_form_fits_viewport(ui, width):
    page, _ = ui
    page.set_viewport_size({"width": width, "height": 900})
    page.goto("http://ui.test/hit-detector")
    form = page.locator("#hit-detector .creator-conversation")
    expect(form).to_be_visible()
    for control in [form, form.locator("textarea"), form.locator('button[type="submit"]')]:
        box = control.bounding_box()
        assert box["x"] >= 0
        assert box["x"] + box["width"] <= width + 1
    if width <= 900:
        textarea = form.locator('textarea')
        textarea.fill('检查一篇真实文章')
        expect(textarea).to_have_value('检查一篇真实文章')
        column = page.locator('#hit-detector .skill-form-col').bounding_box()
        assert textarea.bounding_box()['y'] + textarea.bounding_box()['height'] <= column['y'] + column['height']


def test_standalone_market_loads_immediately_and_can_retry(ui):
    page, state = ui
    state["fail_market"] = True
    page.goto("http://ui.test/market")
    retry = page.get_by_role("button", name="重新加载", exact=True)
    expect(retry).to_be_visible()
    assert "/api/market/meta" in state["requests"]
    state["fail_market"] = False
    retry.click()
    expect(page.get_by_text("没有匹配的 skill", exact=True)).to_be_visible()
    assert "/api/market/skills" in state["requests"]


@pytest.mark.parametrize("label,target,selector", [
    ("公众号", "/workbench", "#workbench-topic"),
    ("小红书", "/xiaohongshu", "#xiaohongshu .creator-conversation textarea"),
    ("贴图号", "/tie-tu", "#tie-tu .creator-conversation textarea"),
])
def test_home_target_forwards_the_draft_without_starting_a_paid_run(ui, label, target, selector):
    page, state = ui
    page.goto("http://ui.test/")
    page.locator(".universe-quick summary").click()
    page.locator("#atelier-draft").fill("给刚开始写公众号的人一个实用建议")
    chip = page.get_by_role("button", name=label, exact=True)
    chip.click()
    expect(chip).to_have_attribute("aria-pressed", "true")
    page.locator("#atelier-start-go").click()
    page.wait_for_url("http://ui.test" + target)
    expect(page.locator(selector)).to_have_value("给刚开始写公众号的人一个实用建议")
    assert not any(path.endswith("/generate") or path.endswith("/chat") for path in state["requests"])


def test_recent_item_opens_its_own_conversation_and_bookshelf_is_a_real_route(ui):
    page, state = ui
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto("http://ui.test/")
    page.locator(".universe-quick summary").click()
    page.get_by_role("link", name="真实会话测试记录", exact=False).click()
    page.wait_for_url("**/workbench?conversation=recent-1")
    page.wait_for_function("localStorage.getItem('universe.conversation.workbench') === 'recent-1'")
    assert "/api/conversations/recent-1" in state["requests"]
    page.locator('.app-tabs a[href="/bookshelf"]').click()
    page.wait_for_url("http://ui.test/bookshelf")
    expect(page.locator('.app-tabs a[href="/bookshelf"]')).to_have_attribute("aria-current", "page")
    expect(page.locator('.app-tabs a[href="/"]')).not_to_have_attribute("aria-current", "page")
    import json
    catalog = json.loads((ROOT / 'static/bookshelf-data.json').read_text(encoding='utf-8'))
    expect(page.locator(".book-link")).to_have_count(len(catalog['books']))


def test_more_menu_can_open_a_secondary_module(ui):
    page, _ = ui
    page.goto('http://ui.test/')
    page.get_by_role('button', name='更多', exact=True).click()
    page.get_by_role('navigation', name='全部功能').get_by_role('link', name='发布前复核', exact=True).click()
    page.wait_for_url('http://ui.test/hit-detector')
    expect(page.get_by_role('dialog', name='全部功能')).not_to_be_visible()
    expect(page.locator('#hit-detector .creator-conversation textarea')).to_be_visible()
    expect(page.get_by_role('button', name='更多', exact=True)).to_have_class('shell-mobile-more active')

@pytest.mark.parametrize('width', [1920,1280,1101,1100,390])
def test_workbench_preserves_dom_and_existing_narrow_layout(ui, width):
    page, _ = ui
    page.set_viewport_size({'width':width,'height':1000})
    page.goto('http://ui.test/workbench')
    if width <= 1100:
        # Mobile is outside this change. Removing the new stylesheet must have
        # no visual effect, regardless of the existing Folio view state.
        expect(page.locator('body')).not_to_have_class('atelier mint-wechat')
        assert page.evaluate('''() => {
            const signature=()=>['#workbench','#creation-assistant','#workbench-result','#workbench-topic']
              .map(selector=>{const c=getComputedStyle(document.querySelector(selector));
                return [c.display,c.visibility,c.width,c.height,c.backgroundColor,c.fontFamily].join('|')}).join(';');
            const before=signature(); document.querySelector('link[href*="wechat-mint.css"]').disabled=true;
            return before===signature();
        }''')
        return
    # Exercise an active conversation, rather than the separate Folio landing screen.
    page.locator('#workbench-chat-thread').evaluate('''el => {
        const item=document.createElement('article'); item.className='chat-message from-user';
        const text=document.createElement('p'); text.textContent='界面回归测试，不调用模型';
        item.append(text); el.append(item);
    }''')
    expect(page.locator('#workbench-topic')).to_be_visible()
    assert page.locator('.conversation-workbench-layout').evaluate('(el)=>[...el.children].filter(x=>["studio-details","creation-assistant","workbench-result"].includes(x.id)).map(x=>x.id)') == ['creation-assistant','workbench-result','studio-details']
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
    if width > 1100:
        expect(page.locator('#studio-details')).to_be_hidden()
        chat=page.locator('#creation-assistant').bounding_box()
        canvas=page.locator('#workbench-result').bounding_box()
        assert chat['x'] + chat['width'] < canvas['x']
        assert chat['width'] >= 300
        assert canvas['width'] >= 340
        assert chat['height'] >= 580
        nav=page.locator('.app-shell > .v3-topbar').bounding_box()
        assert nav['x'] + nav['width'] < chat['x']
        control=page.locator('#workbench-topic')
        assert float(control.evaluate('(el)=>getComputedStyle(el).fontSize').replace('px','')) >= 14
        assert control.bounding_box()['height'] >= 64
