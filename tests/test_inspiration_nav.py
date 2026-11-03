import json
import subprocess
from pathlib import Path


def test_inspiration_group_is_separate_from_creation():
    routes = Path(__file__).resolve().parents[1] / 'static' / 'routes.js'
    script = ('global.window=global; require(' + json.dumps(str(routes)) + '); '
              'console.log(JSON.stringify(window.APP_NAV.notionPlan));')
    output = subprocess.run(['node', '-e', script], check=True, capture_output=True, text=True, encoding='utf-8')
    plan = dict(json.loads(output.stdout))
    assert plan['选题灵感'] == ['/hotspots', '/lowfans', '/image-board']
    assert '/wechat-plus' in plan['创作']
    assert not set(plan['选题灵感']) & set(plan['创作'])
