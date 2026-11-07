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


def test_sticker_page_failure_refunds_and_does_not_call_model(user, monkeypatch):
    monkeypatch.setattr(tasks, 'dispatch', lambda job_id: None)
    class Response:
        text = "<script>picture_page_info_list: [{cdn_url:'https://mmbiz.qpic.cn/example/0'}]</script>"
        def raise_for_status(self): pass
    monkeypatch.setattr(av.requests, 'get', lambda *a, **k: Response())
    calls = []
    monkeypatch.setattr(av, 'build_plan', lambda *a, **k: calls.append(True))
    payload = av.PlanTaskBody(url='https://mp.weixin.qq.com/s/sticker-example', idempotency_key=uuid.uuid4().hex)
    job = av.start_plan_task(payload, request(user))['job']
    assert tasks.run.run(job['id'])['status'] == 'failed'
    assert accounts.wallet_summary(user['id'])['balance'] == 2
    assert av.get_plan_task(job['id'], request(user))['job']['error'] == av.STICKER_ARTICLE_ERROR
    assert not calls


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


def test_resume_accepts_single_plan_checkpoint_at_root(monkeypatch):
    article = {'title': '标题', 'account': '账号', 'markdown': '这是一段可以用来验证的完整文章原文。'}
    candidate = {'article_type': 'story', 'angle_label': '单一方向', 'slots': [
        {'id': 'cover' if i == 0 else f'body-{i}', 'form': 'cover' if i == 0 else 'quote',
         'headline': '真实内容', 'source_quote': article['markdown']} for i in range(4)]}
    calls = []

    def model(prompt, **kwargs):
        calls.append(prompt)
        assert '独立事实核对' in prompt
        return '{"passed":true}'

    monkeypatch.setattr(av, '_text_with_deadline', model)
    monkeypatch.setattr(accounts, 'provider_settings', lambda include_secrets=True: {})
    monkeypatch.setattr(workbench, 'provider_overrides', lambda **kwargs: nullcontext())
    result = av.build_plan(article, initial_raw=json.dumps(candidate, ensure_ascii=False), first_only=True)

    assert result['available_directions'] == 1
    assert result['alternatives'][0]['angle_label'] == '单一方向'
    assert len(calls) == 1


def test_unavailable_review_delivers_warning_without_claiming_verified(user, monkeypatch, tmp_path):
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
    job = av.start_plan_task(payload, request(user))['job']
    assert tasks.run.run(job['id'])['status'] == 'succeeded'
    result = av.get_plan_task(job['id'], request(user))['job']['result']
    assert '尚未核实' in result['plan']['alternatives'][0]['review_notice']
    assert accounts.wallet_summary(user['id'])['balance'] == 0


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


def test_manual_article_checkpoint_resume_keeps_source_and_refunds(user, monkeypatch, tmp_path):
    monkeypatch.setattr(tasks, 'dispatch', lambda job_id: None)
    monkeypatch.setattr(av, 'JOBS_DIR', tmp_path)
    body = '这是一段由用户提供的文章原文，完整保留用于测试续接与文章来源。' * 3
    def fail(article, **kwargs):
        assert article['markdown'] == body and article['source_kind'] == 'user_text'
        raise ValueError('拆解模型未返回内容')
    monkeypatch.setattr(av, 'build_plan', fail)
    payload = av.PlanTaskBody(source_text=body, source_title='用户标题', idempotency_key=uuid.uuid4().hex)
    first = av.start_plan_task(payload, request(user))['job']
    assert tasks.run.run(first['id'])['status'] == 'failed'
    result = av.get_plan_task(first['id'], request(user))['job']
    assert result['resume_available'] and result['billing_status'] == 'refunded'
    assert accounts.wallet_summary(user['id'])['balance'] == 2
    assert av.recent_plan_tasks(request(user))['jobs'][0]['manual_source']
    other = av.PlanTaskBody(url='', idempotency_key=uuid.uuid4().hex, resume_task_id=first['id'])
    second = av.start_plan_task(other, request(user))['job']
    assert tasks.run.run(second['id'])['status'] == 'failed'
    assert av.get_plan_task(second['id'], request(user))['job']['resume_available']
    assert accounts.wallet_summary(user['id'])['balance'] == 2


def test_invalid_manual_body_fails_before_reservation(user, monkeypatch):
    monkeypatch.setattr(tasks, 'dispatch', lambda job_id: None)
    with pytest.raises(HTTPException):
        av.start_plan_task(av.PlanTaskBody(source_text='短文', idempotency_key=uuid.uuid4().hex), request(user))
    assert accounts.wallet_summary(user['id'])['balance'] == 2


def test_semantic_rejection_stays_blocked_and_reports_reason(monkeypatch):
    article = {'title':'标题','account':'','markdown':'这是一段可以用来验证的完整文章原文。'}
    candidate = {'article_type':'story','slots':[{'id':'cover' if i == 0 else f'body-{i}', 'form':'cover' if i == 0 else 'quote', 'headline':'真实内容','source_quote':article['markdown']} for i in range(4)]}
    monkeypatch.setattr(accounts, 'provider_settings', lambda include_secrets=True: {})
    monkeypatch.setattr(workbench, 'provider_overrides', lambda **kwargs: nullcontext())
    monkeypatch.setattr(av, '_text_with_deadline', lambda *args, **kwargs: json.dumps({'plans':[candidate]}, ensure_ascii=False))
    def reject(*args): raise ValueError('图位内容未通过文章事实复核：人物身份不符')
    monkeypatch.setattr(av, 'verify_plan_semantics', reject)
    with pytest.raises(ValueError, match='人物身份不符'):
        av.build_plan(article)


def test_http_access_failure_explains_observed_status_without_claiming_cause(monkeypatch):
    import requests
    response = requests.Response(); response.status_code = 403
    error = requests.HTTPError(response=response)
    def fail(*args, **kwargs): raise error
    monkeypatch.setattr(av.requests, 'get', fail)
    with pytest.raises(ValueError, match='HTTP 403.*无法确定'):
        av.extract_article('https://mp.weixin.qq.com/s/access-test-403')


def test_free_preflight_and_reuse_snapshot_without_second_fetch(user, monkeypatch, tmp_path):
    monkeypatch.setattr(tasks, 'dispatch', lambda job_id: None)
    monkeypatch.setattr(av, 'JOBS_DIR', tmp_path)
    url = 'https://mp.weixin.qq.com/s/preflight-example'
    article = {'url':url, 'title':'标题', 'account':'', 'markdown':'这是一段可以用来验证的完整文章原文。'}
    calls = []
    monkeypatch.setattr(av, 'extract_article', lambda value: (calls.append(value) or article))
    pre = av.preflight_article(av.PlanBody(url=url), request(user))['preflight_id']
    assert accounts.wallet_summary(user['id'])['balance'] == 2
    payload = av.PlanTaskBody(url=url, preflight_id=pre, idempotency_key=uuid.uuid4().hex)
    job = av.start_plan_task(payload, request(user))['job']
    def planning(value, **kwargs):
        assert value == article
        raise ValueError('模拟策划失败')
    monkeypatch.setattr(av, 'build_plan', planning)
    assert tasks.run.run(job['id'])['status'] == 'failed'
    assert calls == [url]
    assert accounts.wallet_summary(user['id'])['balance'] == 2
    assert av.get_plan_task(job['id'], request(user))['job']['resume_available']
    with pytest.raises(HTTPException):
        av._read_preflight(pre, 'different-user', url)
    with pytest.raises(HTTPException):
        av._read_preflight(pre, user['id'], url + 'changed')


def test_preflight_sticker_detected_before_reservation(user, monkeypatch):
    def sticker(url): raise ValueError(av.STICKER_ARTICLE_ERROR)
    monkeypatch.setattr(av, 'extract_article', sticker)
    with pytest.raises(HTTPException) as exc:
        av.preflight_article(av.PlanBody(url='https://mp.weixin.qq.com/s/sticker'), request(user))
    assert '未扣积分' in exc.value.detail
    assert accounts.wallet_summary(user['id'])['balance'] == 2


def test_preflight_rejects_expired_snapshot_before_reservation(user, monkeypatch, tmp_path):
    import os, time
    monkeypatch.setattr(tasks, 'dispatch', lambda job_id: None)
    monkeypatch.setattr(av, 'JOBS_DIR', tmp_path)
    url = 'https://mp.weixin.qq.com/s/expired'
    monkeypatch.setattr(av, 'extract_article', lambda value: {'url':url, 'title':'标题', 'markdown':'文章正文内容'})
    ident = av.preflight_article(av.PlanBody(url=url), request(user))['preflight_id']
    path = tmp_path / '_preflight' / (ident + '.json')
    os.utime(path, (time.time() - 601, time.time() - 601))
    with pytest.raises(HTTPException) as exc:
        av.start_plan_task(av.PlanTaskBody(url=url, preflight_id=ident, idempotency_key=uuid.uuid4().hex), request(user))
    assert exc.value.status_code == 409 and '未扣积分' in exc.value.detail
    assert accounts.wallet_summary(user['id'])['balance'] == 2


def test_wechat_extraction_rejects_offsite_redirect(monkeypatch):
    class Response:
        status_code = 302
        headers = {'Location':'http://127.0.0.1/private'}
    calls = []
    def fetch(url, **kwargs):
        calls.append(url)
        assert kwargs['allow_redirects'] is False
        return Response()
    monkeypatch.setattr(av.requests, 'get', fetch)
    with pytest.raises(ValueError, match='跳转到了不支持的地址'):
        av.extract_article('https://mp.weixin.qq.com/s/redirect-test')
    assert all(url.startswith('https://mp.weixin.qq.com/') for url in calls)


def test_first_direction_returns_without_waiting_for_other_reviews(monkeypatch):
    article = {'title':'标题','account':'','markdown':'这是一段可以用来验证的完整文章原文。'}
    candidates = [{'article_type':'story','angle_label':f'方向{i}','slots':[{'id':'cover' if j==0 else f'body-{j}', 'form':'cover' if j==0 else 'quote', 'headline':'真实内容','source_quote':article['markdown']} for j in range(4)]} for i in range(3)]
    monkeypatch.setattr(accounts, 'provider_settings', lambda include_secrets=True: {})
    monkeypatch.setattr(workbench, 'provider_overrides', lambda **kwargs: nullcontext())
    monkeypatch.setattr(av, '_text_with_deadline', lambda *args, **kwargs: json.dumps({'plans':candidates},ensure_ascii=False))
    checked = []
    monkeypatch.setattr(av, 'verify_plan_semantics', lambda raw, article: checked.append(raw))
    result = av.build_plan(article, first_only=True)
    assert len(checked) == 1 and len(result['alternatives']) == 1
    assert result['background_status'] == 'pending' and result['first_candidate_index'] == 0


def test_background_direction_merge_never_overwrites_user_choice(user, monkeypatch, tmp_path):
    monkeypatch.setattr(av, 'JOBS_DIR', tmp_path)
    ident = uuid.uuid4().hex
    first = {'angle_label':'第一版','slots':[]}
    job = {'id':ident, 'user_id':user['id'], 'plan':{'alternatives':[first], 'background_status':'pending', 'selected_angle':None}, 'images':{}}
    av._write_job(job)
    stale = av._read_job(ident)
    assert tasks._merge_more_directions(ident, [{'angle_label':'第二版','slots':[]}], 'complete')
    assert len(av._read_job(ident)['plan']['alternatives']) == 2
    stale['plan']['selected_angle'] = 0
    stale['images'] = {'cover':{'file':'cover.png'}}; av._write_job(stale)
    saved = av._read_job(ident)
    assert saved['plan']['selected_angle'] == 0 and saved['images']['cover']['file'] == 'cover.png'
    assert len(saved['plan']['alternatives']) == 2 and saved['plan']['background_status'] == 'complete'


def test_first_direction_delivers_then_background_adds_without_new_charge(user, monkeypatch, tmp_path):
    monkeypatch.setattr(tasks, 'dispatch', lambda job_id: None)
    sent = []
    monkeypatch.setattr(tasks, 'dispatch_more_directions', lambda job_id: sent.append(job_id))
    monkeypatch.setattr(av, 'JOBS_DIR', tmp_path)
    monkeypatch.setattr(accounts, 'provider_settings', lambda include_secrets=True: {})
    monkeypatch.setattr(workbench, 'provider_overrides', lambda **kwargs: nullcontext())
    url = 'https://mp.weixin.qq.com/s/three-directions'
    article = {'url':url,'title':'标题','account':'','markdown':'这是一段可以用来验证的完整文章原文。','chars':20,'images':[]}
    monkeypatch.setattr(av, 'extract_article', lambda value: article)
    candidates = [{'article_type':'story','angle_label':f'方向{i}','slots':[{'id':'cover' if j==0 else f'body-{j}', 'form':'cover' if j==0 else 'quote','headline':'真实内容','source_quote':article['markdown']} for j in range(4)]} for i in range(3)]
    monkeypatch.setattr(av, '_text_with_deadline', lambda *args, **kwargs: json.dumps({'plans':candidates},ensure_ascii=False))
    reviews = []
    monkeypatch.setattr(av, 'verify_plan_semantics', lambda raw, article: reviews.append(raw))
    task = av.start_plan_task(av.PlanTaskBody(url=url,idempotency_key=uuid.uuid4().hex),request(user))['job']
    assert tasks.run.run(task['id'])['status'] == 'succeeded'
    result = av.get_plan_task(task['id'], request(user))['job']['result']
    assert len(result['plan']['alternatives']) == 1 and len(reviews) == 1
    assert result['plan']['background_status'] == 'pending' and sent == [task['id']]
    assert accounts.wallet_summary(user['id'])['balance'] == 0
    saved = av._read_job(task['id']); saved['plan']['selected_angle'] = 0
    saved['images'] = {'cover':{'file':'cover.png'}}; av._write_job(saved)
    assert tasks.more_directions.run(task['id'])['status'] == 'completed'
    saved = av._read_job(task['id'])
    assert len(saved['plan']['alternatives']) == 3
    assert saved['plan']['selected_angle'] == 0 and saved['images']['cover']['file'] == 'cover.png'
    assert accounts.wallet_summary(user['id'])['balance'] == 0


def test_background_failure_keeps_first_direction_and_does_not_change_wallet(user, monkeypatch, tmp_path):
    monkeypatch.setattr(av, 'JOBS_DIR', tmp_path)
    ident = uuid.uuid4().hex
    article = {'url':'https://mp.weixin.qq.com/s/test','title':'标题','markdown':'这里是一段可核对的原文。'}
    first = {'angle_label':'第一版','slots':[]}
    job = {'id':ident,'user_id':user['id'],'article_digest':av.article_digest(article),'plan':{'alternatives':[first], 'background_status':'pending', 'first_candidate_index':0, 'selected_angle':None},'images':{}}
    av._write_job(job)
    (tmp_path / ident / 'plan-checkpoint.json').write_text(json.dumps({'user_id':user['id'],'article':article,'raw':'{}'},ensure_ascii=False),encoding='utf-8')
    def fail(*args, **kwargs): raise ValueError('辅助方向复核未通过')
    monkeypatch.setattr(av, 'build_plan', fail)
    before = accounts.wallet_summary(user['id'])['balance']
    assert tasks.more_directions.run(ident)['status'] == 'unavailable'
    saved = av._read_job(ident)
    assert saved['plan']['alternatives'] == [first] and saved['plan']['background_status'] == 'unavailable'
    assert accounts.wallet_summary(user['id'])['balance'] == before
