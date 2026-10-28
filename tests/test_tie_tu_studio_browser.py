"""Local, mocked UI checks; no production login, APIs or image generation."""
import pytest
import os
from pathlib import Path
from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser, ui  # noqa: F401


@pytest.mark.parametrize('width', [390, 1440])
def test_tie_tu_studio_renders_plan_and_responsive_layout(ui, width):
    page, _ = ui
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto('http://ui.test/tie-tu')
    expect(page.locator('#tie-tu .creator-conversation textarea')).to_be_visible()
    expect(page.locator('#tie-tu .empty-head h2')).to_contain_text('你的卡片会显示在这里')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    if os.getenv('TIE_TU_SCREENSHOT_DIR'):
        page.screenshot(path=str(Path(os.environ['TIE_TU_SCREENSHOT_DIR']) / f'tie-tu-{width}.png'), full_page=True)
    page.evaluate('''() => renderTiePlan({title:'测试计划', ratio:'3:4', content_type_label:'清单',
      angle:'测试角度', copy:'配套文案', session_id:'test-session', conversation_id:'test-conv',
      cards:[{index:1,role:'cover',overlay_text:'封面标题',visual_subject:'茶杯',card_brief:{}},
             {index:2,role:'item',overlay_text:'第二张',visual_subject:'书桌',card_brief:{}}]})''')
    expect(page.locator('#tie-result')).to_be_visible()
    expect(page.locator('#tie-empty')).to_be_hidden()
    expect(page.locator('#tie-images')).to_have_text('确认计划并生成第 1 张试图')
    expect(page.locator('#tie-result .creator-output-card')).to_have_count(2)
    if os.getenv('TIE_TU_SCREENSHOT_DIR'):
        page.screenshot(path=str(Path(os.environ['TIE_TU_SCREENSHOT_DIR']) / f'tie-tu-plan-{width}.png'), full_page=True)
    page.evaluate('''() => renderTiePlan({title:'测试计划', ratio:'3:4', content_type_label:'清单',
      angle:'测试角度', copy:'配套文案', session_id:'test-session', conversation_id:'test-conv',
      images:[{index:1,url:'/static/test.png'}], cards:[{index:1,role:'cover',overlay_text:'封面标题',visual_subject:'茶杯',card_brief:{}},
             {index:2,role:'item',overlay_text:'第二张',visual_subject:'书桌',card_brief:{}}]})''')
    expect(page.locator('#tie-images')).to_have_text('确认试图并生成剩余 1 张')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


def test_style_chip_opens_form_and_fills_style(ui):
    page, _ = ui
    page.set_viewport_size({'width': 1440, 'height': 900})
    page.goto('http://ui.test/tie-tu')
    page.locator('#tie-tu .style-chip').first.click()
    expect(page.locator('#tie-style')).to_have_value('赛博朋克 · 霓虹紫 + 故障感')
    expect(page.locator('#tie-form')).to_be_visible()


def test_form_batch_retry_skips_images_already_generated(ui):
    page, _ = ui
    page.goto('http://ui.test/tie-tu')
    page.evaluate('''() => {
      window.testIndices = [];
      postCreator = async (url, body) => {
        const index = body.card.index;
        window.testIndices.push(index);
        if (index === 3 && window.testIndices.filter(i => i === 3).length === 1) throw new Error('暂时失败');
        return {image: {index, url: '/static/test.png'}};
      };
      renderTiePlan({title:'测试计划', ratio:'3:4', content_type_label:'清单', angle:'', copy:'',
        session_id:'test-session', portrait_enabled:false,
        cards:[1,2,3].map(index => ({index,role:'item',overlay_text:'标题',visual_subject:'茶杯',card_brief:{}}))});
    }''')
    page.locator('#tie-images').click()
    expect(page.locator('#tie-images')).to_have_text('确认试图并生成剩余 2 张')
    page.locator('#tie-images').click()
    expect(page.locator('#tie-images')).to_have_text('确认试图并生成剩余 1 张')
    page.locator('#tie-images').click()
    expect(page.locator('#tie-images')).to_be_hidden()
    assert page.evaluate('window.testIndices') == [1, 2, 3, 3]
