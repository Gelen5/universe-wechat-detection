import json
import uuid
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
import tests.support  # noqa: F401
from fastapi import HTTPException
from server import accounts, article_visual as av, article_visual_tasks as tasks, workbench


@pytest.fixture
def user():
    accounts.init_db()
    user = accounts.create_user(f'plan-{uuid.uuid4().hex}@example.com', 'password12345', 'tester')
    with accounts._connect() as c:
        c.execute('UPDATE wallets SET balance=2,trial_balance=2,bonus_balance=0,paid_balance=0 WHERE user_id=?', (user['id'],))
    return user


def request(user):
    return SimpleNamespace(state=SimpleNamespace(user=user))


def test_submit_idempotent_success_and_account_isolation(user, monkeypatch):
    monkeypatch.setattr(tasks, 'dispatch', lambda job_id: None)
    payload = av.PlanTaskBody(url='https://mp.weixin.qq.com/s/example', idempotency_key=uuid.uuid4().hex)
    first = av.start_plan_task(payload, request(user))['job']
    assert accounts.wallet_summary(user['id'])['balance'] == 0
    assert av.recent_plan_tasks(request(user))['jobs'][0]['id'] == first['id']
    assert av.recent_plan_tasks(request({'id': 'different-user'}))['jobs'] == []
    assert av.start_plan_task(payload, request(user))['job']['id'] == first['id']
    monkeypatch.setattr(av, 'create_plan_for_user', lambda url, uid, progress, job_id: (progress('planning') or {'id': job_id, 'slots': []}))
    assert tasks.run.run(first['id'])['status'] == 'succeeded'
    result = av.get_plan_task(first['id'], request(user))['job']
    assert result['status'] == 'succeeded' and result['result']['id'] == first['id']
    assert accounts.wallet_summary(user['id'])['balance'] == 0
    tasks.run.run(first['id'])
    assert accounts.wallet_summary(user['id'])['balance'] == 0
    with pytest.raises(HTTPException):
        av.get_plan_task(first['id'], request({'id': 'different-user'}))


def test_failed_task_refunds(user, monkeypatch):
    monkeypatch.setattr(tasks, 'dispatch', lambda job_id: None)
    payload = av.PlanTaskBody(url='https://mp.weixin.qq.com/s/example', idempotency_key=uuid.uuid4().hex)
    job = av.start_plan_task(payload, request(user))['job']
    def fail(*args, **kwargs): raise ValueError('failure')
    monkeypatch.setattr(av, 'create_plan_for_user', fail)
    assert tasks.run.run(job['id'])['status'] == 'failed'
    assert accounts.wallet_summary(user['id'])['balance'] == 2
    assert av.get_plan_task(job['id'], request(user))['job']['status'] == 'failed'


def test_one_valid_direction_survives_bad_other_direction(monkeypatch):
    article = {'title': '标题', 'account': '账号', 'markdown': '这是一段可以用来验证的完整文章原文。'}
    valid = {'article_type': 'story', 'angle_label': '有效方向', 'slots': [
        {'id': 'cover' if i == 0 else f'body-{i}', 'form': 'cover' if i == 0 else 'quote',
         'headline': '真实内容', 'source_quote': article['markdown']} for i in range(4)]}
    raw = json.dumps({'plans': [valid, {'article_type': 'invalid', 'slots': []}]}, ensure_ascii=False)
    def model(prompt, **kwargs):
        if '修复下列单个' in prompt: raise ValueError('repair failed')
        if '独立事实核对' in prompt: return '{"passed":true}'
        return raw
    monkeypatch.setattr(av, '_text_with_deadline', model)
    monkeypatch.setattr(accounts, 'provider_settings', lambda include_secrets=True: {})
    monkeypatch.setattr(workbench, 'provider_overrides', lambda **kwargs: nullcontext())
    result = av.build_plan(article)
    assert result['available_directions'] == 1
    assert result['alternatives'][0]['angle_label'] == '有效方向'


def test_unavailable_review_can_resume_without_generating_again(user, monkeypatch, tmp_path):
    monkeypatch.setattr(tasks, 'dispatch', lambda job_id: None)
    monkeypatch.setattr(av, 'JOBS_DIR', tmp_path)
    monkeypatch.setattr(accounts, 'provider_settings', lambda include_secrets=True: {})
    monkeypatch.setattr(workbench, 'provider_overrides', lambda **kwargs: nullcontext())
    article = {'url':'https://mp.weixin.qq.com/s/example', 'title':'标题', 'account':'账号', 'markdown':'这是一段可以用来验证的完整文章原文。'}
    monkeypatch.setattr(av, 'extract_article', lambda url: article)
    candidate = {'article_type': 'story', 'slots': [
        {'id': 'cover' if i == 0 else f'body-{i}', 'form': 'cover' if i == 0 else 'quote',
         'headline': '真实内容', 'source_quote': article['markdown']} for i in range(4)]}
    monkeypatch.setattr(av, '_text_with_deadline', lambda *a, **k: json.dumps({'plans': [candidate]}, ensure_ascii=False))
    def unavailable(*args): raise ValueError('文章内容复核暂不可用，请稍后重新拆解')
    monkeypatch.setattr(av, 'verify_plan_semantics', unavailable)
    payload = av.PlanTaskBody(url=article['url'], idempotency_key=uuid.uuid4().hex)
    first = av.start_plan_task(payload, request(user))['job']
    assert tasks.run.run(first['id'])['status'] == 'failed'
    assert av.get_plan_task(first['id'], request(user))['job']['resume_available']
    assert accounts.wallet_summary(user['id'])['balance'] == 2
    monkeypatch.setattr(av, 'verify_plan_semantics', lambda *args: None)
    def no_regeneration(*args, **kwargs): raise AssertionError('unexpected generation')
    monkeypatch.setattr(av, '_text_with_deadline', no_regeneration)
    resumed = av.PlanTaskBody(url=article['url'], idempotency_key=uuid.uuid4().hex, resume_task_id=first['id'])
    second = av.start_plan_task(resumed, request(user))['job']
    assert tasks.run.run(second['id'])['status'] == 'succeeded'
    assert accounts.wallet_summary(user['id'])['balance'] == 0
    result = av.get_plan_task(second['id'], request(user))['job']['result']
    assert len(result['plan']['alternatives']) == 1


def test_invalid_evidence_is_repaired_and_verified(monkeypatch):
    article = {'title': '标题', 'account': '账号', 'markdown': '这是一段可以用来验证的完整文章原文。'}
    candidate = {'article_type': 'story', 'slots': [
        {'id': 'cover' if i == 0 else f'body-{i}', 'form': 'cover' if i == 0 else 'quote',
         'headline': '真实内容', 'source_quote': article['markdown']} for i in range(4)]}
    broken = json.loads(json.dumps(candidate, ensure_ascii=False))
    broken['slots'][1]['source_quote'] = '这段错误引用不是文章中的原句'
    calls = []
    def model(prompt, **kwargs):
        calls.append(prompt)
        if '修复下列单个' in prompt:
            repaired = json.loads(json.dumps(candidate, ensure_ascii=False))
            repaired['slots'][2]['headline'] = '不应覆盖的修改'
            return json.dumps(repaired, ensure_ascii=False)
        if '独立事实核对' in prompt: return '{"passed":true}'
        return json.dumps({'plans':[broken]}, ensure_ascii=False)
    monkeypatch.setattr(av, '_text_with_deadline', model)
    monkeypatch.setattr(accounts, 'provider_settings', lambda include_secrets=True: {})
    monkeypatch.setattr(workbench, 'provider_overrides', lambda **kwargs: nullcontext())
    result = av.build_plan(article)
    assert result['alternatives'][0]['slots'][1]['source_quote'] == article['markdown']
    assert result['alternatives'][0]['slots'][2]['headline'] == '真实内容'
    assert any('独立事实核对' in prompt for prompt in calls)


def test_transient_generation_error_retries_in_same_plan(monkeypatch):
    article = {'title': '标题', 'account': '账号', 'markdown': '这是一段可以用来验证的完整文章原文。'}
    candidate = {'article_type': 'story', 'slots': [
        {'id': 'cover' if i == 0 else f'body-{i}', 'form': 'cover' if i == 0 else 'quote',
         'headline': '真实内容', 'source_quote': article['markdown']} for i in range(4)]}
    calls = []
    def model(prompt, **kwargs):
        calls.append(prompt)
        if len(calls) == 1: raise TimeoutError('temporary')
        if '独立事实核对' in prompt: return '{"passed":true}'
        return json.dumps({'plans':[candidate]}, ensure_ascii=False)
    monkeypatch.setattr(av, '_text_with_deadline', model)
    monkeypatch.setattr(accounts, 'provider_settings', lambda include_secrets=True: {})
    monkeypatch.setattr(workbench, 'provider_overrides', lambda **kwargs: nullcontext())
    stages = []
    result = av.build_plan(article, progress=lambda stage, *args: stages.append(stage))
    assert 'retrying' in stages and result['available_directions'] == 1
    assert len(calls) == 3


def test_recovery_reconciles_settled_and_failed_jobs(user, monkeypatch):
    monkeypatch.setattr(tasks, 'dispatch', lambda job_id: None)
    payload = av.PlanTaskBody(url='https://mp.weixin.qq.com/s/example', idempotency_key=uuid.uuid4().hex)
    job = av.start_plan_task(payload, request(user))['job']
    accounts.claim_job(['text'], job['id'])
    accounts.fail_job(job['id'], 'interrupted')
    assert accounts.wallet_summary(user['id'])['balance'] == 0
    tasks.recover.run()
    assert accounts.wallet_summary(user['id'])['balance'] == 2


def test_interrupted_task_requeues_once_then_refunds(user, monkeypatch):
    sent = []
    monkeypatch.setattr(tasks, 'dispatch', lambda job_id: sent.append(job_id))
    payload = av.PlanTaskBody(url='https://mp.weixin.qq.com/s/example', idempotency_key=uuid.uuid4().hex)
    job = av.start_plan_task(payload, request(user))['job']
    accounts.claim_job(['text'], job['id'])
    accounts.recover_interrupted_jobs()
    assert accounts.job(job['id'], user['id'])['status'] == 'running'
    with accounts._connect() as c:
        c.execute("UPDATE jobs SET started_at='2000-01-01T00:00:00+00:00' WHERE id=?", (job['id'],))
    tasks.recover.run()
    assert accounts.job(job['id'], user['id'])['status'] == 'queued'
    assert job['id'] in sent
    accounts.claim_job(['text'], job['id'])
    with accounts._connect() as c:
        c.execute("UPDATE jobs SET started_at='2000-01-01T00:00:00+00:00' WHERE id=?", (job['id'],))
    tasks.recover.run()
    assert accounts.job(job['id'], user['id'])['status'] == 'failed'
    assert accounts.wallet_summary(user['id'])['balance'] == 2
    tasks.recover.run()
    assert accounts.wallet_summary(user['id'])['balance'] == 2


def test_orphan_reservation_is_refunded_after_crash(user, monkeypatch):
    monkeypatch.setattr(tasks, 'dispatch', lambda job_id: None)
    usage_id = accounts.reserve_points(user['id'], {'points': 2, 'feature': '文章配图策划'}, 'POST', '/api/article-visual/tasks/start')
    with accounts._connect() as c:
        c.execute("UPDATE usage_records SET created_at='2000-01-01T00:00:00+00:00' WHERE request_id=?", (usage_id,))
    tasks.recover.run()
    tasks.recover.run()
    assert accounts.wallet_summary(user['id'])['balance'] == 2
