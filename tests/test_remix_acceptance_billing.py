import json
from contextlib import nullcontext
import pytest
import tests.support
from server import viral_remix_tasks as tasks, remix_quality


@pytest.mark.parametrize('review', ['passed', 'issues', 'unavailable'])
def test_review_never_blocks_delivery_or_retries(monkeypatch, tmp_path, review):
    idea = {'content_ledger': {'version': 2}, 'id': 'A'}
    job = {'id': 'qa-job', 'payload_json': json.dumps({'idea': idea, 'session_id': 'qa', 'count': 1})}
    monkeypatch.setattr(tasks.accounts, 'claim_job', lambda *args: job)
    monkeypatch.setattr(tasks.workbench, 'provider_overrides', lambda: nullcontext())
    monkeypatch.setattr(tasks.creator_tools, 'prepare_remix_cards', lambda *args: ([{}], idea, tmp_path / 'draft'))
    calls, settlements, finished = [], [], []
    def generate(*args):
        calls.append(args)
        return {'url': '/qa.jpg', 'index': 1}
    monkeypatch.setattr(tasks.creator_tools, 'generate_remix_card', generate)
    def inspect(*args):
        if review == 'unavailable':
            raise RuntimeError('review unavailable')
        return {'passed': review == 'passed', 'issues': ['年龄可能不一致'] if review == 'issues' else [], 'repair': ''}
    monkeypatch.setattr(remix_quality, 'inspect_image', inspect)
    monkeypatch.setattr(tasks.accounts, 'progress_job', lambda *args, **kwargs: None)
    monkeypatch.setattr(tasks.accounts, 'finish_job', lambda job_id, result: finished.append(result))
    monkeypatch.setattr(tasks.accounts, 'fail_job', lambda *args: pytest.fail('image should be delivered'))
    monkeypatch.setattr(tasks.jobs, 'settle', lambda job, images, elapsed: settlements.append(images))
    result = tasks.run.run('qa-job')
    assert result['status'] == 'succeeded'
    assert len(calls) == 1
    assert len(settlements) == 1 and len(settlements[0]) == 1
    image = finished[0]['images'][0]
    if review == 'issues':
        assert '年龄可能不一致' in image['review_notice']
    elif review == 'unavailable':
        assert '自动检查暂不可用' in image['review_notice']
    else:
        assert image['check_passed'] is True
