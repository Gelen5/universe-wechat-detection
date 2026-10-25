from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
"""Desktop mint presentation must preserve the real workspace controls and routes."""
import pytest
from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser, ui


@pytest.mark.parametrize('width', [1101, 1280, 1440, 1920])
def test_desktop_mint_workspace_has_usable_chat_and_output(ui, width):
    page, state = ui
    page.set_viewport_size({'width':width,'height':1000})
    page.goto('http://ui.test/workbench')
    expect(page.locator('body')).to_have_class('atelier mint-wechat')
    expect(page.locator('#workbench-stage-nav button')).to_have_count(5)
    expect(page.locator('#workbench-topic')).to_be_visible()
    expect(page.locator('#folio-landing')).to_be_hidden()
    expect(page.locator('#workbench-chat-thread .from-ai')).to_be_visible()
    boxes = {s:page.locator(s).bounding_box() for s in ('.v3-topbar','#creation-assistant','#workbench-result','.composer-shell')}
    assert boxes['.v3-topbar']['x'] + boxes['.v3-topbar']['width'] < boxes['#creation-assistant']['x']
    assert boxes['#creation-assistant']['x'] + boxes['#creation-assistant']['width'] < boxes['#workbench-result']['x']
    assert boxes['.composer-shell']['y'] + boxes['.composer-shell']['height'] <= boxes['#creation-assistant']['y'] + boxes['#creation-assistant']['height']
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.locator('#workbench-topic').fill('只做桌面视觉验收，不调用模型')
    expect(page.locator('#workbench-topic')).to_have_value('只做桌面视觉验收，不调用模型')
    assert not [p for p in state['requests'] if p == '/api/runs']


def test_mint_is_removed_when_navigating_away_and_does_not_activate_on_mobile(ui):
    page, _ = ui
    page.set_viewport_size({'width':1440,'height':1000})
    page.goto('http://ui.test/workbench')
    expect(page.locator('body')).to_have_class('atelier mint-wechat')
    page.locator('.app-tabs [data-view="home"]').click()
    expect(page.locator('body')).to_have_class('atelier')
    page.locator('.app-tabs [data-view="workbench"]').click()
    expect(page.locator('body')).to_have_class('atelier mint-wechat')
    page.set_viewport_size({'width':390,'height':844})
    expect(page.locator('body')).to_have_class('atelier')
    page.set_viewport_size({'width':1440,'height':1000})
    expect(page.locator('body')).to_have_class('atelier mint-wechat')


def test_existing_history_control_remains_operable(ui):
    page, _ = ui
    page.set_viewport_size({'width':1440,'height':1000})
    page.goto('http://ui.test/workbench')
    page.locator('#recent-workbench-chats').click()
    expect(page.locator('#workbench-chat-history')).to_be_visible()


@pytest.mark.parametrize('width', [1280, 1440, 1920, 2560])
def test_steps_fit_the_header_and_wallet_shares_a_row_with_settings(ui, width):
    page, _ = ui
    page.set_viewport_size({'width':width,'height':1229})
    page.goto('http://ui.test/workbench')
    expect(page.locator('.pd-pageact .pd-pill')).to_be_hidden()
    expect(page.locator('.v3-topbar .right .stat')).to_be_visible()
    page.locator('.v3-topbar .right .stat b').evaluate("el=>el.textContent='99,859'")
    wallet = page.locator('.v3-topbar .right .stat').bounding_box()
    toggle = page.get_by_role('button', name='打开设置菜单').bounding_box()
    assert wallet['x'] + wallet['width'] <= toggle['x']
    assert abs((wallet['y']+wallet['height']/2)-(toggle['y']+toggle['height']/2)) < 2
    rail = page.locator('#workbench-stage-nav').bounding_box()
    heading = page.locator('.studio-heading').bounding_box()
    assert abs(rail['x']-heading['x']) < 1
    assert abs(rail['width']-heading['width']) < 1
    for button in page.locator('#workbench-stage-nav button').all():
        rect = button.bounding_box()
        assert rect['y'] >= rail['y']
        assert rect['y'] + rect['height'] <= rail['y'] + rail['height']
    assert page.evaluate('document.documentElement.scrollHeight<=innerHeight+1')


def test_sidebar_settings_button_reuses_existing_menu_and_supports_keyboard(ui):
    page, _ = ui
    page.set_viewport_size({'width':1440,'height':1000})
    page.goto('http://ui.test/workbench')
    toggle = page.get_by_role('button', name='打开设置菜单')
    toggle.focus(); page.keyboard.press('Enter')
    expect(page.locator('#settings-menu')).to_be_visible()
    expect(toggle).to_have_attribute('aria-expanded', 'true')
    menu = page.locator('#settings-menu').bounding_box()
    assert menu['x'] >= 0
    assert menu['x'] + menu['width'] <= 1440
    page.keyboard.press('Escape')
    expect(page.locator('#settings-menu')).to_be_hidden()
    expect(toggle).to_be_focused()
    expect(toggle).to_have_attribute('aria-expanded', 'false')
    page.locator('.app-tabs [data-view="home"]').click()
    expect(toggle).to_be_hidden()


@pytest.mark.parametrize('width', [1101, 1280, 1440, 1920, 2560])
def test_adaptive_workspace_uses_available_width_without_stretching_reading(ui, width):
    page, _ = ui
    page.set_viewport_size({'width':width,'height':1229})
    page.goto('http://ui.test/workbench')
    nav = page.locator('.v3-topbar').bounding_box()
    workspace = page.locator('#workbench').bounding_box()
    chat = page.locator('#creation-assistant').bounding_box()
    canvas = page.locator('#workbench-result').bounding_box()
    assert 24 <= workspace['x'] - nav['x'] - nav['width'] <= 40
    assert 24 <= width - workspace['x'] - workspace['width'] <= 40
    assert abs(canvas['x'] + canvas['width'] - workspace['x'] - workspace['width']) < 1
    assert chat['width'] <= 561
    assert float(page.locator('.app-tabs [data-view="workbench"] > span').first.evaluate('e=>getComputedStyle(e).fontSize').replace('px','')) >= 15
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    assert float(page.locator('#workbench-stage-nav small').first.evaluate('e=>getComputedStyle(e).fontSize').replace('px','')) >= 12
    assert float(page.locator('.chat-message p').first.evaluate('e=>getComputedStyle(e).fontSize').replace('px','')) >= 16
    article = '## 阅读宽度测试\n\n' + '这是一份临时排版测试稿，不会提交给模型或保存到真实会话。' * 10
    page.locator('#article-editor').evaluate('''(el,text)=>{
        el.value=text; el.dispatchEvent(new Event('input',{bubbles:true}));
        el.closest('.editor-wrap').hidden=false;
    }''', article)
    expect(page.locator('.folio-doc p').first).to_be_visible()
    assert page.locator('.editor-wrap').bounding_box()['width'] <= 861
    assert float(page.locator('.folio-doc p').first.evaluate('e=>getComputedStyle(e).fontSize').replace('px','')) >= 17


@pytest.mark.parametrize('width', [1101, 1280, 1440, 2560])
def test_topic_results_share_a_centered_readable_rail(ui, width):
    page, _ = ui
    page.set_viewport_size({'width':width,'height':1229})
    topics = [{'title':'为什么越来越多人不接陌生电话：把防骚扰和不漏接重要来电分开处理', 'heat':7, 'fan_score':84, 'competition':'中', 'type':'观点'}, {'title':'AI开始替人处理任务后，普通用户先要管好哪些授权？', 'heat':8, 'fan_score':86, 'competition':'高'}, {'title':'仅提供部分指标的选题', 'fan_score':0}]
    artifact = {'id':'topic-test', 'type':'topic', 'title':'选题建议与检索记录', 'content':'测试选题', 'content_json':{'topics':topics}, 'version':1, 'created_at':'2026-10-25T00:00:00Z'}
    page.route('**/api/conversations/recent-1/artifacts', lambda route:route.fulfill(json={'artifacts':[artifact]}))
    page.goto('http://ui.test/workbench?conversation=recent-1')
    expect(page.locator('.topic-row')).to_have_count(3)
    canvas = page.locator('#workbench-result').bounding_box()
    rail = page.locator('#workbench-stage-choices').bounding_box()
    assert rail['width'] <= 961
    assert abs(rail['x']+rail['width']/2-canvas['x']-canvas['width']/2) < 12
    head = page.locator('.workbench-stage-head').bounding_box()
    assert abs(head['x']-rail['x']) < 1
    assert page.locator('.topic-row').first.evaluate('e=>getComputedStyle(e).textAlign') == 'left'
    assert float(page.locator('.topic-signal-label').first.evaluate('e=>getComputedStyle(e).fontSize').replace('px','')) >= 12
    assert page.locator('.topic-meter').first.evaluate('e=>getComputedStyle(e).display') == 'block'
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    partial = page.locator('.topic-row').nth(2)
    expect(partial.locator('.topic-signal').first).to_contain_text('—')
    expect(partial.locator('.topic-signal').nth(1)).to_contain_text('0 / 100')
    expect(partial.locator('.topic-row-competition')).to_contain_text('未评估')
    meta = page.locator('.topic-row-meta').first
    assert meta.evaluate('e=>getComputedStyle(e).display') == 'grid'
    expect(page.locator('.topic-row-badges').first).to_contain_text('观点')
    expect(page.locator('.topic-signal').first).to_contain_text('7 / 10')
    assert page.locator('.topic-row').first.evaluate('e=>e.scrollWidth<=e.clientWidth')
    if width == 2560:
        page.screenshot(path=str(ROOT / 'output/mint-ui/refined-topics-wide.png'))


@pytest.mark.parametrize('width', [1101, 1440, 2560])
def test_assistant_action_card_keeps_long_selection_and_controls_inside(ui, width):
    page, _ = ui
    page.set_viewport_size({'width':width,'height':1159})
    topic = '地震避险别只记生命三角：家庭版伏地、遮挡、抓牢清单，以及家人之间如何提前约定集合位置和紧急联系办法'
    artifact = {'id':'selected-topic-test','type':'topic','title':'选题建议','content':'测试选题','content_json':{'topics':[{'title':topic,'heat':7,'fan_score':82,'competition':'高'}]},'version':1,'created_at':'2026-10-25T00:00:00Z'}
    page.route('**/api/conversations/recent-1/artifacts',lambda route:route.fulfill(json={'artifacts':[artifact]}))
    page.goto('http://ui.test/workbench?conversation=recent-1')
    page.locator('[data-topic-choice]').first.click()
    card = page.locator('#workbench-action-card')
    expect(card.locator('.chat-selected-topic')).to_have_text(topic)
    expect(card.locator('[data-next-stage="outline"]')).to_be_visible()
    box = card.bounding_box()
    for child in card.locator('strong,p,button').all():
        rect = child.bounding_box()
        assert rect['y'] >= box['y']
        assert rect['y']+rect['height'] <= box['y']+box['height']+1
        assert rect['x']+rect['width'] <= box['x']+box['width']+1
    assert card.evaluate('e=>getComputedStyle(e).flexShrink') == '0'
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    assert not page.locator('#workbench-action-card').get_by_text('去左侧选择方向').count()
    if width == 2560:
        page.screenshot(path=str(ROOT/'output/mint-ui/assistant-action-refined.png'))


@pytest.mark.parametrize('width', [1101, 1440, 2560])
def test_writing_theme_is_present_before_late_theme_script_and_survives_reload(ui, width):
    page, _ = ui
    page.set_viewport_size({'width':width,'height':1159})
    # The late script is unavailable: the first-paint theme must still be present.
    page.route('**/static/wechat-mint.js*', lambda route:route.abort())
    page.goto('http://ui.test/workbench')
    for _ in range(3):
        expect(page.locator('body')).to_have_class('atelier mint-wechat')
        for selector in ('.conversation-panel-head', '.workbench-stage-head'):
            assert page.locator(selector).evaluate('e=>getComputedStyle(e).borderBottomWidth') == '0px'
        assert page.locator('.conversation-panel-head').evaluate('e=>getComputedStyle(e).boxShadow') == 'none'
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.reload()
