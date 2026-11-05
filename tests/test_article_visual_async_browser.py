from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser, ui  # noqa: F401


def test_background_task_restores_after_refresh(ui):
    page, observed = ui
    job = {'id': 'abc123', 'article': {'title': '测试文章', 'account': '', 'chars': 20},
           'plan': {'thesis': '主题', 'article_type': 'knowledge', 'alternatives': [], 'selected_angle': None},
           'slots': [{'id': 'cover', 'form': 'cover', 'headline': '封面', 'status': 'pending'}], 'images': {}}
    state = {'ready': False, 'submissions': 0}
    def start(route):
        state['submissions'] += 1
        route.fulfill(json={'job': {'id': 'task123', 'status': 'queued'}})
    def status(route):
        result = {'id': 'task123', 'status': 'succeeded', 'result': job} if state['ready'] else {'id': 'task123', 'status': 'running', 'progress': {'stage':'checking', 'current':1, 'total':3}}
        route.fulfill(json={'job': result})
    page.route('**/api/article-visual/tasks/start', start)
    page.route('**/api/article-visual/tasks/task123', status)
    page.goto('http://ui.test/article-visual')
    page.locator('#av-url').fill('https://mp.weixin.qq.com/s/test')
    page.locator('#av-analyze').click()
    expect(page.locator('#av-hint')).to_contain_text('正在核对原文')
    state['ready'] = True
    page.reload()
    expect(page.locator('#av-article-title')).to_have_text('测试文章', timeout=10000)
    assert state['submissions'] == 1
    assert not observed['errors']


def test_review_unavailable_preserves_and_resumes(ui):
    page, observed = ui
    job = {'id': 'abc123', 'article': {'title': '测试文章', 'account': '', 'chars': 20},
           'plan': {'thesis': '主题', 'article_type': 'knowledge', 'alternatives': [], 'selected_angle': None},
           'slots': [{'id': 'cover', 'form': 'cover', 'headline': '封面', 'status': 'pending'}], 'images': {}}
    state = {'requests': []}
    def start(route):
        state['requests'].append(route.request.post_data_json)
        route.fulfill(json={'job': {'id': 'task2' if len(state['requests']) == 2 else 'task1', 'status': 'queued'}})
    def status(route):
        if route.request.url.endswith('task1'):
            route.fulfill(json={'job': {'id':'task1', 'status':'failed', 'resume_available':True, 'error':'复核暂不可用，积分已退回'}})
        else:
            route.fulfill(json={'job': {'id':'task2', 'status':'succeeded', 'result':job}})
    page.route('**/api/article-visual/tasks/start', start)
    page.route('**/api/article-visual/tasks/task*', status)
    page.goto('http://ui.test/article-visual')
    page.locator('#av-url').fill('https://mp.weixin.qq.com/s/test')
    page.locator('#av-analyze').click()
    expect(page.locator('#av-resume-review')).to_be_visible()
    page.reload()
    expect(page.locator('#av-resume-review')).to_be_visible()
    page.locator('#av-resume-review').click()
    expect(page.locator('#av-article-title')).to_have_text('测试文章', timeout=10000)
    assert state['requests'][1]['resume_task_id'] == 'task1'
    assert not observed['errors']


def test_sticker_guidance_preserves_link_without_starting_extraction(ui):
    page, observed = ui
    source = 'https://mp.weixin.qq.com/s/sticker-example'
    page.route('**/api/article-visual/tasks/start', lambda r: r.fulfill(json={'job':{'id':'sticker1','status':'queued'}}))
    page.route('**/api/article-visual/tasks/sticker1', lambda r: r.fulfill(json={'job':{
        'id':'sticker1','status':'failed','billing_status':'refunded','error':'这是贴图号图文，图片文字暂不能直接按文章正文拆解。可前往贴图号内容提取；本次失败积分将自动退回。'}}))
    page.goto('http://ui.test/article-visual', wait_until='networkidle')
    page.locator('#av-url').fill(source)
    page.locator('#av-analyze').click()
    button = page.locator('#av-go-sticker-extract')
    expect(button).to_be_visible()
    expect(page.locator('#av-hint')).to_contain_text('积分已退回')
    button.click()
    expect(page.locator('#sticker-extract')).to_be_visible()
    expect(page.locator('#sticker-url')).to_have_value(source)
    assert '/api/sticker-extract' not in observed['requests']
    assert not observed['errors']


def test_manual_text_submits_only_after_user_action(ui):
    page, observed = ui
    seen = []
    def start(route):
        seen.append(route.request.post_data_json)
        route.fulfill(json={'job': {'id':'manual1','status':'queued'}})
    page.route('**/api/article-visual/tasks/start', start)
    page.route('**/api/article-visual/tasks/manual1', lambda r: r.fulfill(json={'job': {'id':'manual1','status':'failed','billing_status':'refunded','error':'策划服务暂不可用'}}))
    page.goto('http://ui.test/article-visual')
    page.locator('#av-text-entry summary').click()
    text = '这是一段由用户提供并有权使用的文章正文，包含足够的文字用于测试文章拆解流程。' * 3
    page.locator('#av-source-text').fill(text)
    assert not seen
    page.locator('#av-analyze').click()
    expect(page.locator('#av-hint')).to_contain_text('积分已退回')
    assert seen[0]['source_text'] == text and seen[0]['url'] == ''
    assert not observed['errors']


def test_review_notice_is_visible_when_direction_was_not_reviewed(ui):
    page, observed = ui
    choice = {'angle_label':'方向一','angle_reason':'推荐','review_notice':'事实复核服务暂不可用，请逐条核对原文。','slots':[{'id':'cover','form':'cover','headline':'封面','source_quote':'文章中的真实依据'}]}
    job = {'id':'abc123','article':{'title':'文章','account':'','chars':50}, 'plan':{'alternatives':[choice], 'thesis':'主题','selected_angle':None},'slots':choice['slots'],'images':{}}
    page.route('**/api/article-visual/tasks/start', lambda r: r.fulfill(json={'job':{'id':'task1','status':'queued'}}))
    page.route('**/api/article-visual/tasks/task1', lambda r: r.fulfill(json={'job':{'id':'task1','status':'succeeded','result':job}}))
    page.goto('http://ui.test/article-visual')
    page.locator('#av-url').fill('https://mp.weixin.qq.com/s/example')
    page.locator('#av-analyze').click()
    expect(page.locator('.av-review-warning')).to_contain_text('复核服务暂不可用')
    expect(page.locator('#av-hint')).not_to_contain_text('已通过校验')
    assert not observed['errors']


def test_failure_with_pending_refund_does_not_claim_it_is_complete(ui):
    page, observed = ui
    page.route('**/api/article-visual/tasks/start', lambda r: r.fulfill(json={'job':{'id':'pending1','status':'queued'}}))
    page.route('**/api/article-visual/tasks/pending1', lambda r: r.fulfill(json={'job':{'id':'pending1','status':'failed','billing_status':'reserved','error':'策划服务超时；本次积分已退回'}}))
    page.goto('http://ui.test/article-visual')
    page.locator('#av-url').fill('https://mp.weixin.qq.com/s/example')
    page.locator('#av-analyze').click()
    expect(page.locator('#av-hint')).to_contain_text('退款处理中')
    expect(page.locator('#av-hint')).not_to_contain_text('积分已退回')
    assert not observed['errors']
