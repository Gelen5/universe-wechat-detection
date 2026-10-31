"""Navigation must come from one list.

The sidebar was rebuilt by notion-workspace.js while shell.js and
app-navigation.js kept their own copies, so adding a module meant editing three
arrays and a missed one showed up as a missing entry. All three now read
static/routes.js; these tests lock the derived values to the ones that were
hard-coded before the refactor, so rendering cannot drift.
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / 'static'

# The exact arrays that used to live in shell.js / notion-workspace.js, updated
# whenever a module is added: the point is that all three renderers agree with
# this list, not that the list never changes.
LEGACY_SHELL_ROUTES = [
    ['/', '首页', '首页'], ['/hotspots', '热点广场'], ['/workbench', '公众号创作', '创作'],
    ['/one-click-writing', '公众号一键成文', '一键成文'],
    ['/xiaohongshu', '小红书'], ['/tie-tu', '贴图号'], ['/viral-remix', '爆款贴图复刻'],
    ['/xhs-extract', '小红书内容提取'],
    ['/morning-generator', '早安祝福'],
    ['/diagnose', '账号诊断'], ['/hit-detector', '发布前复核'],
    ['/market', 'AI 超市', '超市'], ['/bookshelf', 'AI 书架'],
    ['/pricing', '积分套餐'],
]
LEGACY_NOTION_PLAN = [
    ['内容创作', ['/hotspots', '/workbench', '/one-click-writing', '/xiaohongshu',
                  '/tie-tu', '/viral-remix', '/xhs-extract', '/morning-generator']],
    ['分析', ['/diagnose', '/hit-detector']],
    ['资源', ['/market', '/bookshelf']],
    ['账户', ['/pricing']],
]
LEGACY_VIEWS = {
    '/': 'home', '/workbench': 'workbench', '/one-click-writing': 'one-click-writing',
    '/xiaohongshu': 'xiaohongshu', '/tie-tu': 'tie-tu', '/viral-remix': 'viral-remix',
    '/xhs-extract': 'xhs-extract',
    '/diagnose': 'diagnose', '/hit-detector': 'hit-detector',
    '/morning-generator': 'morning', '/market': 'market', '/hotspots': 'hotspots',
}

NODE = shutil.which('node')


def _dump():
    script = (
        "global.window = global;"
        f"require({json.dumps(str(STATIC / 'routes.js'))});"
        "const n = window.APP_NAV;"
        "const views = {};"
        "for (const p of ['/', '/workbench', '/one-click-writing', '/xiaohongshu', '/tie-tu', '/pricing', '/bookshelf',"
        " '/viral-remix', '/xhs-extract', '/diagnose', '/hit-detector', '/morning-generator', '/market', '/hotspots'])"
        " views[p] = n.viewFor(p);"
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
        self.assertEqual(['/hotspots', '/xhs-extract', '/pricing'], self.data['extras'])

    def test_every_legacy_view_mapping_is_preserved(self):
        self.assertEqual(LEGACY_VIEWS, self.data['views'])

    def test_page_links_are_not_spa_views(self):
        # /pricing and /bookshelf are server-rendered pages; treating them as
        # views hid every panel and left a blank screen until a refresh.
        self.assertIsNone(self.data['views'].get('/pricing'))
        self.assertIsNone(self.data['views'].get('/bookshelf'))
        self.assertEqual('market', self.data['views'].get('/market'))

    def test_page_links_stay_in_the_menu(self):
        hrefs = [route[0] for route in self.data['shell']]
        self.assertIn('/pricing', hrefs)
        self.assertIn('/bookshelf', hrefs)


class IncludeTests(unittest.TestCase):
    PAGES = ['index.html', 'bookshelf.html', 'market.html', 'qihaoshou.html']

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

    def test_renderers_no_longer_hard_code_a_route_list(self):
        for name in ('shell.js', 'app-navigation.js', 'notion-workspace.js'):
            text = (STATIC / name).read_text(encoding='utf-8')
            with self.subTest(script=name):
                self.assertIn('window.APP_NAV', text)
                self.assertNotIn("'/morning-generator', '早安祝福'", text)


if __name__ == '__main__':
    unittest.main()

