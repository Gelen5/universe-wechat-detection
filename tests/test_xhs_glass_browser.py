import os
from pathlib import Path
import pytest
from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser, ui

@pytest.mark.parametrize('width', [390, 1440])
def test_xhs_workspace(ui, width):
    page, state = ui
    page.set_viewport_size({'width':width, 'height':900})
    page.goto('http://ui.test/xiaohongshu')
    expect(page.locator('#xiaohongshu')).to_be_visible()
    expect(page.locator('#xiaohongshu .creator-conversation textarea')).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    expect(page.locator('#xiaohongshu .xhs-glass-guide-item')).to_have_count(3)
    page.locator('#xiaohongshu .creator-conversation textarea').fill('给职场新人做一份会议记录图文')
    page.locator('#xiaohongshu .creator-form-mode summary').click()
    expect(page.locator('#xhs-topic')).to_be_visible()
    page.locator('#xiaohongshu .creator-form-mode summary').click()
    dest=os.getenv('XHS_SHOTS')
    if dest: page.screenshot(path=str(Path(dest)/f'xhs-empty-{width}.png'), full_page=True)
    page.evaluate('''() => renderXhsPackage({selected_title:'用 AI 整理会议记录的三个方法',angle:'从工作场景切入',titles:[{text:'会议记录别再只做摘要',keyword:'效率',reason:'具体场景'},{text:'让会议记录变成待办清单',keyword:'工作',reason:'实用'}],cards:[{index:1,role:'封面',headline:'会议记录怎么整理',message:'把讨论变成行动',action:'聚焦主题'},{index:2,role:'内容',headline:'先确认任务',message:'明确负责人',action:'核对信息'}],body:'先整理事实，再核对待办。',pinned_comment:'你平时怎么整理？',cta:'欢迎分享',precheck:{status:'待检查',issues:[]}})''')
    expect(page.locator('#xhs-result')).to_be_visible()
    expect(page.locator('#xhs-empty')).to_be_hidden()
    assert page.locator('#xhs-result .title-option').first.bounding_box()['width'] > (120 if width == 390 else 150)
    expect(page.locator('#xiaohongshu .creator-conversation textarea')).to_have_attribute('placeholder', __import__('re').compile('AI'))
    expect(page.locator('#xhs-images')).to_have_text('生成 2 张图片')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    if dest: page.screenshot(path=str(Path(dest)/f'xhs-result-{width}.png'), full_page=True)
