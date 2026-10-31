from pathlib import Path
from urllib.parse import urlparse,parse_qs
import mimetypes
import pytest
from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser
ROOT=Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('width',[1440,390])
def test_admin_navigation_filter_drawer(browser,width):
    page=browser.new_page(viewport={'width':width,'height':1000})
    errors=[]; calls=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    user={'id':'u1','display_name':'示例用户','email':'demo@example.test','created_at':'2026-10-31T01:00:00Z','last_login_at':'2026-10-31T02:00:00Z','last_active_at':'2026-10-31T02:30:00Z','balance':6,'task_count':1,'failed_tasks':1}
    task={'id':'job1','user_id':'u1','display_name':'示例用户','email':'demo@example.test','feature':'贴图创作','status':'failed','created_at':'2026-10-31T02:00:00Z','points':5,'billing_status':'refunded','error':'上游超时'}
    def serve(route):
        parsed=urlparse(route.request.url);calls.append(route.request.url)
        if parsed.path=='/api/admin/activity':
            q=parse_qs(parsed.query)
            route.fulfill(json={'summary':{'registered_total':196,'new':1,'active':1,'creators':1,'tasks':1,'failed':1,'total':1},'trend':[{'date':'2026-10-31','new':1,'active':1}],'features':{'贴图创作':1},'rows':[task if q.get('view')==['tasks'] else user],'total':1,'page':1,'page_size':25,'updated_at':'2026-10-31T02:00:00Z','activity_started':'2026-10-31T00:00:00Z'})
        elif parsed.path.startswith('/api/admin/activity/users/'):
            route.fulfill(json={**user,'usage':{'completed':1},'activity':[{'kind':'login','created_at':user['last_login_at']}],'transactions':[{'amount':-5,'kind':'consume','balance_before':11,'balance_after':6,'note':'生成贴图','created_at':user['last_login_at']}]})
        else:
            file=ROOT/'static'/('admin-activity.html' if parsed.path=='/admin/users' else Path(parsed.path).name)
            route.fulfill(body=file.read_bytes(),content_type=mimetypes.guess_type(str(file))[0] or 'text/plain')
    page.route('**/*',serve)
    page.goto('http://ui.test/admin/users')
    expect(page.locator('#rows')).to_contain_text('demo@example.test')
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.get_by_role('button',name='查看详情',exact=True).click()
    expect(page.locator('#drawer')).to_be_visible()
    expect(page.locator('#detail')).to_contain_text('11 → 6')
    page.keyboard.press('Escape')
    expect(page.locator('#drawer')).not_to_be_visible()
    page.locator('[data-metric=failed]').click()
    expect(page.locator('#rows')).to_contain_text('失败')
    page.get_by_role('button',name='查看详情',exact=True).click()
    expect(page.locator('#drawer')).to_contain_text('上游超时')
    page.locator('#close').click()
    page.locator('[data-metric=active]').click()
    expect(page.locator('#filter-label')).to_contain_text('活跃用户')
    assert any('metric=active' in call for call in calls)
    page.screenshot(path=f'D:/Download/workbench-audit-20261027/admin-activity-{width}.png',full_page=True)
    expect(page.locator('#registered-total')).to_have_text('196')
    page.locator('#search').fill('nobody')
    page.locator('#share-registration').click()
    expect(page.locator('#registration-share')).to_be_visible()
    expect(page.locator('main')).not_to_be_visible()
    expect(page.locator('#share-card')).to_contain_text('196')
    expect(page.locator('#share-card')).to_contain_text('还差 4 个')
    expect(page.locator('#share-card')).to_contain_text('yuzoudiyigongzuotai.cn')
    expect(page.locator('#share-card')).not_to_contain_text('demo@example.test')
    expect(page.locator('#share-card')).not_to_contain_text('测试账号')
    page.screenshot(path=f'D:/Download/workbench-audit-20261027/registration-share-{width}.png')
    page.keyboard.press('Escape')
    expect(page.locator('main')).to_be_visible()
    page.locator('#all-registered').click()
    expect(page.locator('#role')).to_have_value('all')
    expect(page.locator('#search')).to_have_value('')
    expect(page.locator('[data-view=users]')).to_have_class('selected')
    assert any('role=all' in call and 'metric=all' in call for call in calls)
    assert not errors
    page.close()
