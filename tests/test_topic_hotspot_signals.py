import json
from unittest.mock import patch

from server import topic_hotspot_signals as signals
from server import workbench
from server.celery_app import celery_app


class FakeCache:
    def __init__(self, entries):
        self.entries = entries
    def get(self, key):
        return self.entries.get(key)
    def ttl(self, key):
        return 600 if key in self.entries else -2


def test_hotspot_sync_is_loaded_by_worker():
    assert 'server.hotspots' in celery_app.conf.include
    celery_app.loader.import_default_modules()
    assert 'hotspot.sync' in celery_app.tasks


def test_cached_domestic_sources_filter_unrelated_and_preserve_provenance():
    key = signals.hotspots.KEY_ITEMS.format(platform='douyin')
    entries = [{'platform': 'douyin', 'title': 'AI工具如何使用', 'url': 'https://example.com/a', 'rank': 3},
               {'platform': 'douyin', 'title': '足球比赛结果', 'url': 'https://example.com/b', 'rank': 1}]
    with patch.object(signals.hotspots, '_redis', return_value=FakeCache({key: json.dumps(entries)})):
        result = signals.cached_topic_signals('AI工具')
    assert result['status'] == 'matched'
    assert len(result['items']) == 1
    assert result['items'][0]['platform'] == 'douyin'
    assert result['items'][0]['observed_at'] and result['items'][0]['rank'] == 3


def test_cache_no_match_and_unavailable_do_not_invent_hotspots():
    key = signals.hotspots.KEY_ITEMS.format(platform='weibo')
    with patch.object(signals.hotspots, '_redis', return_value=FakeCache({key: json.dumps([
        {'platform': 'weibo', 'title': '足球比赛', 'url': 'https://example.com/a'}])})):
        result = signals.cached_topic_signals('婚姻沟通')
    assert result['status'] == 'no_match' and result['items'] == []
    with patch.object(signals.hotspots, '_redis', return_value=None):
        assert signals.cached_topic_signals('婚姻沟通')['status'] == 'unavailable'


def test_topic_prompt_and_session_carry_square_evidence():
    square = {'status': 'matched', 'items': [{'title': 'AI工具', 'platform': 'douyin',
              'url': 'https://example.com/a', 'observed_at': '2026-10-28T00:00:00+08:00'}]}
    captured, session = [], {}
    topics = [{'title': '方向%d' % i} for i in range(6)]
    with patch.object(workbench, '_require_skill'), \
         patch.object(workbench.skill_runtime, 'context', return_value=('规则', [])), \
         patch.object(workbench.skill_runtime, 'script', return_value=[]), \
         patch.object(signals, 'cached_topic_signals', return_value=square), \
         patch.object(workbench.workbench_research, 'search', return_value={'status': 'unavailable', 'sources': []}), \
         patch.object(workbench.workbench_research, 'history', return_value={'titles': []}), \
         patch.object(workbench, '_json_text', side_effect=lambda **kw: captured.append(kw['prompt']) or {'topics': topics}):
        result = workbench._suggestions('AI工具', '作者', session)
    assert len(result) == 6 and session['square_hotspots'] == square
    assert 'https://example.com/a' in captured[0] and '热点只是线索' in captured[0]
