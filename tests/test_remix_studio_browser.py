import pytest
import os
from pathlib import Path
from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser, ui


@pytest.mark.parametrize('width',[390,1440])
def test_guided_create_and_revision(ui,width):
    page,state=ui
    page.set_viewport_size({'width':width,'height':1000})
    calls=[]
    image='/api/creator-tools/assets/tie-tu/studio-test/result.jpg'
    def serve(route):
        payload=route.request.post_data_json
        calls.append((route.request.url,payload))
        route.fulfill(json={'job':{'id':'version-'+str(len(calls)),'status':'succeeded','images':[{'url':image}],'created_at':'2026-11-04T00:00:00Z'}})
    page.route('**/api/remix-studio/create',serve)
    page.route('**/api/remix-studio/*/revise',serve)
    if os.getenv('STUDIO_SAMPLE_IMAGE'):
        page.route('**'+image,lambda route:route.fulfill(body=Path(os.environ['STUDIO_SAMPLE_IMAGE']).read_bytes(),content_type='image/jpeg'))
    page.goto('http://ui.test/viral-remix')
    page.wait_for_function('currentAccount?.id === "test-user"')
    page.locator('#viral-remix-image').set_input_files({'name':'reference.png','mimeType':'image/png','buffer':b'reference'})
    page.get_by_role('button',name='保留全部数据',exact=True).click()
    page.locator('#viral-remix-start').click()
    expect(page.get_by_role('heading',name='哪里还想调整？')).to_be_visible()
    assert calls[0][1]['options']==['facts']
    page.get_by_role('button',name='标题更抓眼球',exact=True).click()
    page.locator('.studio-editor textarea').fill('其他数据不变')
    page.get_by_role('button',name='按要求修改这张图 →').click()
    expect(page.locator('.studio-editor textarea')).to_have_value('')
    assert calls[1][1]['options']==['headline']
    assert calls[1][1]['goal']=='其他数据不变'
    assert '/version-1/revise' in calls[1][0]
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
    if os.getenv('STUDIO_SCREENSHOTS_DIR'):
        directory=Path(os.environ['STUDIO_SCREENSHOTS_DIR']);directory.mkdir(parents=True,exist_ok=True)
        page.screenshot(path=str(directory/f'studio-{width}.png'),full_page=True)
