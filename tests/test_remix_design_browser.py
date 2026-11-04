import pytest
from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser, ui
from tests.test_remix_design import dataset
from server import remix_design


@pytest.mark.parametrize('width',[390,1440])
def test_three_previews_and_history_are_readable(ui,width,tmp_path):
    page,state=ui
    page.set_viewport_size({'width':width,'height':1000})
    page.goto('http://ui.test/viral-remix')
    result={'content_guess':'完整数据图','analysis':{},'ideas':remix_design.plans(dataset()),
            'data_contract':dataset(),'pages':[],'claims':[]}
    page.evaluate('''result=>{currentAccount={id:'test-user'};setActiveView('viral-remix',true);renderViralRemix(result,'qa-session-v2');}''',result)
    page.get_by_role('tab',name='02 翻新方案').click()
    expect(page.locator('.remix-design-preview')).to_have_count(3)
    expect(page.locator('.remix-design-preview').first).to_contain_text('29.3')
    assert page.locator('[name=remix-boundaries]').input_value()=='无额外禁区'
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    for preview in page.locator('.remix-design-preview').all():
        assert preview.evaluate('(e)=>e.scrollHeight<=e.clientHeight+1')
    page.screenshot(path=str(tmp_path/f'previews-{width}.png'),full_page=True)
    # Saved source data remains intact when re-opening history.
    page.evaluate('''result=>renderViralRemix(result,'qa-session-v2')''',result)
    page.get_by_role('tab',name='02 翻新方案').click()
    expect(page.locator('.remix-design-preview')).to_have_count(3)
