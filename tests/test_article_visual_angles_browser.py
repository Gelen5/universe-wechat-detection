from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser, ui


def test_choose_angle_shows_its_plan(ui):
    page, observed = ui
    choices = []
    for title in ["身份反差", "技术探索", "职业转型"]:
        choices.append({"angle_label":title, "angle_reason":"故事角度", "slots":[{"id":"cover", "form":"cover", "headline":title, "source_quote":"真实文章中的原文依据", "status":"pending"}]})
    job = {"id":"abc123", "article":{"title":"测试文章", "account":"", "chars":100}, "plan":{"thesis":"真实故事", "article_type":"story", "alternatives":choices, "selected_angle":None}, "slots":choices[0]["slots"], "images":{}}
    def handle(route):
        if route.request.url.endswith('/angle'):
            job['plan']['selected_angle'] = 1
            job['slots'] = choices[1]['slots']
        route.fulfill(json=job)
    page.route('**/api/article-visual/**', handle)
    page.goto('http://ui.test/article-visual')
    page.locator('#av-url').fill('https://mp.weixin.qq.com/s/test')
    page.locator('#av-analyze').click()
    expect(page.locator('#av-angles')).to_contain_text('选择传播角度')
    expect(page.locator('#av-plan-content')).to_be_hidden()
    expect(page.locator('.av-angle-option').nth(1)).to_be_visible()
    page.locator('.av-angle-option').nth(1).click()
    expect(page.locator('#av-plan-content')).to_be_visible()
    expect(page.locator('#av-slot-list')).to_contain_text('技术探索')
    expect(page.locator('#av-slot-list')).to_contain_text('原文依据')
    assert not observed['errors']


def test_knowledge_article_shows_all_angles_without_opening_details(ui):
    page, _ = ui
    choices = [{"angle_label":str(i), "slots":[{"id":"cover", "form":"cover", "headline":str(i), "status":"pending"}]} for i in range(3)]
    job = {"id":"abc123", "article":{"title":"教程", "chars":50}, "plan":{"article_type":"knowledge", "alternatives":choices, "selected_angle":None}, "slots":choices[0]["slots"], "images":{}}
    page.route('**/api/article-visual/**', lambda route:route.fulfill(json=job))
    page.goto('http://ui.test/article-visual')
    page.locator('#av-url').fill('https://mp.weixin.qq.com/s/test')
    page.locator('#av-analyze').click()
    expect(page.locator('.av-angle-option')).to_have_count(3)
    expect(page.locator('.av-angle-option').nth(2)).to_be_visible()
