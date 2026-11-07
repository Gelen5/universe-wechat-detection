"""Navigation must come from one list.

The sidebar was rebuilt by notion-workspace.js while shell.js and
app-navigation.js kept their own copies, so adding a module meant editing three
arrays and a missed one showed up as a missing entry. All three now read
static/routes.js; these tests lock the derived values to the ones that were
hard-coded before the refactor, so rendering cannot drift.
"""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / 'static'

# The exact arrays that used to live in shell.js / notion-workspace.js, updated
# whenever a module is added: the point is that all three renderers agree with
# this list, not that the list never changes.
LEGACY_SHELL_ROUTES = [
    ['/', '首页', '首页'], ['/content-factory', '爆款成品库'],
    ['/hotspots', '热点广场', '热点'],
    ['/topic-library', '选题灵感库'], ['/lowfans', '低粉爆文'],
    ['/image-board', '低粉爆图'],
    ['/viral-article', '爆文复刻'],
    ['/xiaohongshu', '小红书'], ['/tie-tu', '贴图号'], ['/viral-remix', '爆款贴图复刻', '爆图复刻'],
    ['/article-visual', '爆文转贴图'],
    ['/remove-ai-flavor', '去 AI 味'],
    ['/sticker-extract', '贴图号内容提取'],
    ['/xhs-extract', '小红书内容提取'],
    ['/douyin-extract', '抖音内容提取'],
    ['/morning-generator', '早安祝福'],
    ['/market', 'AI 超市', '超市'], ['/skills', '技能库'], ['/bookshelf', 'AI 书架'],
    ['/pricing', '积分套餐'],
    ['/invite', '邀请好友'],
]
LEGACY_NOTION_PLAN = [
    ['选题灵感', ['/hotspots', '/topic-library', '/lowfans', '/image-board']],
    ['创作', ['/viral-article', '/xiaohongshu', '/tie-tu',
              '/viral-remix', '/article-visual']],
    ['工具', ['/remove-ai-flavor', '/sticker-extract', '/xhs-extract', '/douyin-extract']],
    ['资源', ['/content-factory', '/market', '/skills', '/bookshelf']],
    ['账户', ['/pricing', '/invite']],
]
LEGACY_VIEWS = {
    '/': 'home', '/workbench': None, '/one-click-writing': None,
    '/content-factory': 'content-factory',
    '/skills': 'skills',
    '/remove-ai-flavor': 'remove-ai-flavor',
    '/wechat-plus': 'wechat-plus',
    '/viral-article': 'viral-article',
    '/xiaohongshu': 'xiaohongshu', '/tie-tu': 'tie-tu', '/viral-remix': 'viral-remix',
    '/lowfans': 'lowfans', '/article-visual': 'article-visual',
    '/topic-library': 'topic-library', '/image-board': 'image-board',
    '/sticker-extract': 'sticker-extract',
    '/xhs-extract': 'xhs-extract',
    '/douyin-extract': 'douyin-extract',
    '/diagnose': 'diagnose', '/hit-detector': 'hit-detector',
    # 隐藏只影响入口，视图映射必须保留，直链和已存的会话才能照常打开。
    '/wechat-plus': 'wechat-plus',
    '/morning-generator': 'morning', '/market': 'market', '/hotspots': 'hotspots',
    # 书架现在内嵌在常驻外壳里（section + iframe），所以是应用内视图。
    '/bookshelf': 'bookshelf',
    # 邀请好友和积分套餐都是服务端渲染的独立页，不能被当成应用内视图。
    '/pricing': None,
    '/invite': None,
}

NODE = shutil.which('node')


def _dump():
    script = (
        "global.window = global;"
        f"require({json.dumps(str(STATIC / 'routes.js'))});"
        "const n = window.APP_NAV;"
        "const views = {};"
        "for (const p of ['/', '/workbench', '/one-click-writing', '/wechat-plus', '/viral-article', '/content-factory', '/skills', '/remove-ai-flavor', '/xiaohongshu', '/tie-tu', '/pricing', '/bookshelf',"
        " '/viral-remix', '/article-visual', '/sticker-extract', '/xhs-extract', '/douyin-extract', '/lowfans', '/topic-library', '/image-board', '/diagnose', '/hit-detector', '/morning-generator', '/market', '/hotspots', '/invite'])"
        " views[p] = n.viewFor(p) ?? null;"
        "process.stdout.write(JSON.stringify({shell: n.shellRoutes, plan: n.notionPlan,"
        " extras: n.extras.map(e => e.href), views}));"
    )
    # Node writes UTF-8; without an explicit encoding, Windows decodes stdout as
    # GBK and every assertion here dies on a UnicodeDecodeError instead of
    # checking anything.
    out = subprocess.run([NODE, '-e', script], capture_output=True, text=True,
                         encoding='utf-8', timeout=60)
    if out.returncode != 0:
        raise AssertionError(out.stderr[-400:])
    return json.loads(out.stdout)


@unittest.skipIf(NODE is None, 'node is not installed')
class SingleSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = _dump()

    def test_shell_routes_match_the_old_array_exactly(self):
        self.assertEqual(LEGACY_SHELL_ROUTES, self.data['shell'])

    def test_sidebar_plan_matches_the_old_grouping_exactly(self):
        self.assertEqual(LEGACY_NOTION_PLAN, self.data['plan'])

    def test_only_the_fallback_entries_are_created(self):
        # Entries absent from the server-rendered HTML declare fallback: true so
        # every renderer can build them instead of silently dropping them.
        self.assertEqual(
            ['/content-factory', '/hotspots', '/topic-library', '/lowfans', '/image-board',
             '/viral-article', '/article-visual', '/remove-ai-flavor', '/sticker-extract',
             '/xhs-extract', '/douyin-extract', '/skills', '/bookshelf', '/pricing', '/invite'],
            self.data['extras'],
        )

    def test_every_legacy_view_mapping_is_preserved(self):
        self.assertEqual(LEGACY_VIEWS, self.data['views'])

    def test_page_links_are_not_spa_views(self):
        # /pricing is still a server-rendered page: treating it as a view hid
        # every panel and left a blank screen until a refresh. /bookshelf is
        # now embedded via its own <section id="bookshelf"> + iframe, so it is
        # a legitimate view; the invariant that matters is that any entry
        # claiming a view has a matching section in index.html.
        self.assertIsNone(self.data['views'].get('/pricing'))
        self.assertIsNone(self.data['views'].get('/invite'))
        self.assertEqual('bookshelf', self.data['views'].get('/bookshelf'))
        self.assertEqual('market', self.data['views'].get('/market'))

    def test_new_views_are_registered_in_app_view_map(self):
        app = (STATIC / 'app.js').read_text(encoding='utf-8')
        self.assertIn("'remove-ai-flavor': document.querySelector('#remove-ai-flavor')", app)
        self.assertIn("skills: document.querySelector('#skills')", app)
        self.assertIn("'remove-ai-flavor': '去 AI 味'", app)
        self.assertIn("skills: '技能库'", app)

    def test_page_links_stay_in_the_menu(self):
        hrefs = [route[0] for route in self.data['shell']]
        self.assertIn('/pricing', hrefs)
        self.assertIn('/bookshelf', hrefs)

    def test_hidden_modules_leave_every_menu_but_keep_their_route(self):
        """A module can be switched off without deleting it.

        /diagnose is hidden because its upstream data source is out of quota, so
        it must drop out of all three renderers while `viewFor` keeps resolving
        the route. Restoring it is one flag flip plus the page anchors that were
        commented out next to it.
        """
        self.assertNotIn('/diagnose', [route[0] for route in self.data['shell']])
        self.assertNotIn('/diagnose', [h for _, hrefs in self.data['plan'] for h in hrefs])
        self.assertNotIn('/diagnose', self.data['extras'])
        self.assertEqual('diagnose', self.data['views'].get('/diagnose'))

    def test_workbench_entry_is_hidden_and_redirects_at_server(self):
        """旧公众号创作入口已迁到 Plus，SPA 不再把它当应用内视图。"""
        self.assertNotIn('/workbench', [route[0] for route in self.data['shell']])
        self.assertNotIn('/workbench', [h for _, hrefs in self.data['plan'] for h in hrefs])
        self.assertNotIn('/workbench', self.data['extras'])
        self.assertIsNone(self.data['views'].get('/workbench'))

    def test_hit_detector_entry_is_hidden_but_the_route_still_opens(self):
        """发布前复核按用户要求从侧栏收起，但 /hit-detector 直链仍可用。"""
        self.assertNotIn('/hit-detector', [route[0] for route in self.data['shell']])
        self.assertNotIn('/hit-detector', [h for _, hrefs in self.data['plan'] for h in hrefs])
        self.assertNotIn('/hit-detector', self.data['extras'])
        self.assertEqual('hit-detector', self.data['views'].get('/hit-detector'))

    def test_hidden_modules_have_no_live_anchor_in_any_page(self):
        """The page shells still ship server-rendered anchors.

        shell.js renders whatever anchors the HTML already contains, so a hidden
        module's anchor has to be commented out there as well, otherwise the
        entry reappears on every standalone page.
        """
        for page in ('index.html', 'bookshelf.html', 'market.html'):
            text = (STATIC / page).read_text(encoding='utf-8')
            live = re.sub(r'<!--.*?-->', '', text, flags=re.S)
            with self.subTest(page=page):
                self.assertNotIn('/diagnose', live,
                                 f'{page} still renders a live /diagnose link')

    def test_wechat_plus_entry_is_hidden_but_the_route_still_opens(self):
        """公众号创作 Plus 有 bug，先收起入口；路由与视图映射必须留着。

        侧栏锚点是服务端渲染的，shell.js 只复用已有节点，所以只改 routes.js
        不够 —— index.html 那段 <a data-view="wechat-plus"> 也必须注释掉，
        否则每个独立页面都会把入口又摆回来。
        """
        self.assertNotIn('/wechat-plus', [route[0] for route in self.data['shell']])
        self.assertNotIn('/wechat-plus', [h for _, hrefs in self.data['plan'] for h in hrefs])
        self.assertNotIn('/wechat-plus', self.data['extras'])
        self.assertEqual('wechat-plus', self.data['views'].get('/wechat-plus'))

        text = (STATIC / 'index.html').read_text(encoding='utf-8')
        live = re.sub(r'<!--.*?-->', '', text, flags=re.S)
        self.assertNotIn('data-view="wechat-plus"', live)
        # 首页那两张卡片和 hero CTA 也是入口，同样不能出现在正文里。
        self.assertNotIn('href="/wechat-plus"', live)
        self.assertIn('id="wechat-plus"', live, '章节本身要留着，直链还得能打开')

    def test_wechat_plus_has_no_live_entry_on_other_pages(self):
        """选题灵感库是独立页面，自带一套侧栏，得单独挡。"""
        text = (STATIC / 'topic-library.html').read_text(encoding='utf-8')
        live = re.sub(r'<!--.*?-->', '', text, flags=re.S)
        self.assertNotIn('href="/wechat-plus"', live)

    def test_lowfans_and_hotspots_no_longer_hand_off_to_the_creator(self):
        """两个列表页原本各有一个「去创作」按钮，会把内容塞进创作台。"""
        for name in ('lowfans.js', 'hotspots.js'):
            js = (STATIC / name).read_text(encoding='utf-8')
            # 注释里保留着还原说明，只检查真正会渲染出来的标记。
            code = re.sub(r'//[^\n]*', '', js)
            with self.subTest(script=name):
                self.assertNotIn('data-write=', code)
                self.assertNotIn('data-create=', code)


class SidebarCollapseTests(unittest.TestCase):
    """侧栏不再折叠：工具 / 资源 / 账户 直接展开。

    曾经把三个分组默认收起、在上面挂一个「更多功能」开关。用户要求取消折叠，
    所以渲染器不该再生成那个按钮，样式里也不该再有默认 display:none。
    """

    def test_renderer_does_not_build_the_more_toggle(self):
        js = (STATIC / 'notion-workspace.js').read_text(encoding='utf-8')
        self.assertNotIn('nav-more-toggle', js)
        self.assertNotIn('nav-expanded', js)

    def test_stylesheet_does_not_hide_any_group_by_default(self):
        css = (STATIC / 'ui-system.css').read_text(encoding='utf-8')
        self.assertNotIn('nav-more-toggle', css)
        self.assertNotIn('nav-expanded', css)
        for group in ('工具', '资源', '账户'):
            with self.subTest(group=group):
                self.assertNotIn(f'.nav-group[data-group="{group}"]', css,
                                 f'{group} 分组又被默认隐藏了')


class IncludeTests(unittest.TestCase):
    PAGES = ['index.html', 'bookshelf.html', 'market.html']

    def test_every_page_loads_routes_before_the_nav_scripts(self):
        for page in self.PAGES:
            text = (STATIC / page).read_text(encoding='utf-8')
            with self.subTest(page=page):
                routes_at = text.find('/static/routes.js')
                self.assertGreaterEqual(routes_at, 0, f'{page} does not load routes.js')
                for script in ('/static/shell.js', '/static/app-navigation.js'):
                    at = text.find(script)
                    if at >= 0:
                        self.assertLess(routes_at, at,
                                        f'{page} loads {script} before routes.js')

    def test_every_view_resolves_to_a_real_element(self):
        """A routed view whose element is missing hides every panel.

        The selector is read from app.js (the view map), not assumed from the
        view name: `morning` maps to #morning-generator, `home` to #home.
        """
        index = (STATIC / 'index.html').read_text(encoding='utf-8')
        bundle = (STATIC / 'app.js').read_text(encoding='utf-8')
        # Lines look like:   xiaohongshu: xiaohongshuPage,   'tie-tu': tieTuPage,
        pattern = re.compile(r"^\s*'?([\w-]+)'?:\s*([A-Za-z_$][\w$]*),\s*$", re.M)
        declarations = dict(re.findall(
            r"^const\s+([A-Za-z_$][\w$]*)\s*=\s*document\.querySelector\('([^']+)'\);\s*$",
            bundle, re.M))
        checked = 0
        for view, variable in pattern.findall(bundle):
            selector = declarations.get(variable)
            if not selector or not selector.startswith('#'):
                continue
            checked += 1
            with self.subTest(view=view, selector=selector):
                self.assertIn(f'id="{selector[1:]}"', index,
                              f'{view} -> {selector} has no section in index.html')
        self.assertGreaterEqual(checked, 8, f'view map parse looks wrong ({checked})')

    def test_renderers_no_longer_hard_code_a_route_list(self):
        for name in ('shell.js', 'app-navigation.js', 'notion-workspace.js'):
            text = (STATIC / name).read_text(encoding='utf-8')
            with self.subTest(script=name):
                self.assertIn('window.APP_NAV', text)
                self.assertNotIn("'/morning-generator', '早安祝福'", text)


if __name__ == '__main__':
    unittest.main()

