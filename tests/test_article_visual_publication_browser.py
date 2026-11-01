import pytest
from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser, ui  # noqa: F401


@pytest.mark.parametrize('width', [390, 1440])
def test_publication_gallery_generate_edit_and_restore(ui, width):
    page, observed = ui
    page.set_viewport_size({'width': width, 'height': 900})
    publication = {'titles': ['图片相关标题', '第二个标题', '第三个标题'], 'body': '与图片相关的配文', 'tags': ['图片主题']}
    job = {'id': 'abc123', 'article': {'title': '测试文章', 'chars': 50},
           'plan': {'thesis': '主题', 'article_type': 'knowledge', 'alternatives': []},
           'slots': [{'id': 'cover', 'form': 'cover', 'headline': '封面', 'status': 'done'}],
           'images': {'cover': {'file': 'cover.png'}}}
    methods = []
    def serve(route):
        if route.request.url.split('?')[0].endswith('/publication'):
            methods.append(route.request.method)
            if route.request.method == 'PUT':
                job['publication'] = route.request.post_data_json
            else:
                job['publication'] = publication.copy()
            route.fulfill(json={'publication': job['publication']})
        elif '/images/' in route.request.url:
            route.fulfill(status=200, content_type='image/png', body=b'')
        else:
            route.fulfill(json=job)
    page.route('**/api/article-visual/**', serve)
    page.goto('http://ui.test/article-visual?job=abc123')
    page.locator('#av-tabs [data-tab="gallery"]').click()
    panel = page.locator('#av-publication')
    expect(panel.get_by_text('生成标题和文案', exact=True)).to_be_visible()
    panel.get_by_text('生成标题和文案', exact=True).click()
    expect(panel.locator('input[aria-label="标题 1"]')).to_have_value('图片相关标题')
    panel.locator('textarea').fill('编辑后的配文')
    panel.get_by_text('保存修改', exact=True).click()
    expect(panel.get_by_text('修改已保存')).to_be_visible()
    page.reload()
    page.locator('#av-tabs [data-tab="gallery"]').click()
    expect(panel.locator('textarea')).to_have_value('编辑后的配文')
    assert methods == ['POST', 'PUT']
    assert not observed['errors']
