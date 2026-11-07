from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from tests import support  # noqa: F401 - isolate before importing database

from server import content_factory, database
from server.content_factory_purchase import jobs, metadata, products
from server.content_factory_v3_store import (metadata as v3_metadata, stage_candidate,
                                             budget_reservations)
from server.models import LowfansArticle, PointTransaction, Wallet


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('MAKERS_MODELS_KEY', 'test')
    class Detector:
        def raise_for_status(self): pass
        def json(self): return {'status':'success','labels_ratio':{'0':0.9}}
    monkeypatch.setattr(content_factory.requests, 'post', lambda *a, **kw: Detector())
    engine = create_engine(f"sqlite:///{(tmp_path / 'api.db').as_posix()}", connect_args={"check_same_thread": False})
    metadata.create_all(engine)
    v3_metadata.create_all(engine)
    for table in (LowfansArticle.__table__, Wallet.__table__, PointTransaction.__table__):
        table.create(engine)
    monkeypatch.setattr(database, "ENGINE", engine)
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    monkeypatch.setattr(content_factory.accounts, "require_user", lambda request: {"id": request.headers.get("x-user", "a")})
    monkeypatch.setattr(content_factory.accounts, "require_admin", lambda request: {"id": "admin"} if request.headers.get("x-admin") == "1" else (_ for _ in ()).throw(content_factory.HTTPException(403)))
    with engine.begin() as con:
        con.execute(LowfansArticle.__table__.insert().values(id=1, stat_date="2026-11-01", range_type="7d", art_id="source", title="真实来源", art_url="https://example.com/article", captured_at=datetime.now(timezone.utc)))
        con.execute(Wallet.__table__.insert(), [dict(user_id=user, balance=10, trial_balance=0, bonus_balance=0, paid_balance=10, updated_at="now") for user in ("a", "b")])
    app = FastAPI()
    app.include_router(content_factory.router)
    return TestClient(app)


def test_exclusive_sale_and_content_authorization(client):
    admin = {"x-admin": "1"}
    payload = {"source_row_id": 1, "product_type": "article", "title": "原创文章", "track": "情感", "preview": "节选", "content": "只给买家看的完整文章" * 100, "price_points": 5}
    result = client.post('/api/content-factory/admin/products', json=payload, headers=admin)
    assert result.status_code == 200
    product_id = result.json()['id']
    assert client.get('/api/content-factory/products').json() == []
    assert client.post(f'/api/content-factory/admin/products/{product_id}/publish', headers=admin).status_code == 200
    listing = client.get('/api/content-factory/products').json()
    assert '完整文章' not in str(listing)
    assert client.get(f'/api/content-factory/products/{product_id}/content').status_code == 404
    assert client.post(f'/api/content-factory/products/{product_id}/purchase').status_code == 200
    assert client.post(f'/api/content-factory/products/{product_id}/purchase').json()['already_owned']
    assert client.post(f'/api/content-factory/products/{product_id}/purchase', headers={'x-user':'b'}).status_code == 409
    assert client.get(f'/api/content-factory/products/{product_id}/content').json()['content'] == payload['content']
    assert client.get(f'/api/content-factory/products/{product_id}/content', headers={'x-user':'b'}).status_code == 404
    assert client.post(f'/api/content-factory/products/{product_id}/feedback', json={'body':'已发布'}).status_code == 200
    assert client.post(f'/api/content-factory/admin/products/{product_id}/hide', headers=admin).status_code == 409


def test_unverified_source_cannot_be_published(client):
    payload = {"source_row_id": 999, "product_type": "article", "title": "文章", "content": "正文", "price_points": 5}
    assert client.post('/api/content-factory/admin/products', json=payload, headers={'x-admin':'1'}).status_code == 400
    assert client.post('/api/content-factory/admin/products', json=payload).status_code == 403
    assert client.get('/api/content-factory/admin/opportunities').status_code == 403


def test_title_plan_is_validated_and_stored_by_admin(client):
    source = {'track': '情感', 'source': {'id': 'one', 'title': '来源标题',
              'url': 'https://example.com/a', 'observed_at': '2026-11-07'}}
    with database.ENGINE.begin() as connection:
        run = stage_candidate(connection, day='2026-11-07', product_type='article', candidate=source, angle='沟通')
    plan = {'main_title': '家庭沟通从听懂开始', 'alternative_titles': ['说清需求才容易商量',
            '给亲密关系留一些空间', '吵架之后如何继续对话'], 'strategy': '问题解决', 'reason': '围绕沟通'}
    path = f"/api/content-factory/admin/automation/runs/{run['id']}/titles"
    assert client.put(path, json=plan).status_code == 403
    assert client.put(path, json=plan, headers={'x-admin':'1'}).status_code == 200
    assert client.get('/api/content-factory/admin/automation/runs', headers={'x-admin':'1'}).json()[0]['status'] == 'title_ready'


def test_automation_limits_cannot_enable_work_and_require_admin(client):
    limits = {'daily_budget_micros': 1000000, 'article_limit': 2, 'image_limit': 2,
              'image_people_mode': 'required', 'tracks': ['情感', '情感']}
    path = '/api/content-factory/admin/automation/limits'
    assert client.put(path, json=limits).status_code == 403
    response = client.put(path, json=limits, headers={'x-admin':'1'})
    assert response.status_code == 200
    assert response.json()['tracks'] == ['情感']
    assert response.json()['image_people_mode'] == 'required'
    assert response.json()['emergency_stop'] is True and response.json()['automatic_selection'] is False
    assert client.put(path, json={**limits, 'image_people_mode': 'invalid'},
                      headers={'x-admin':'1'}).status_code == 422
    assert client.post('/api/content-factory/admin/automation/emergency-stop', headers={'x-admin':'1'}).json()['stopped']


def test_publishing_requires_healthy_lanes_and_emergency_stop_clears_it(client):
    admin = {'x-admin':'1'}
    publishing = '/api/content-factory/admin/automation/enable-publishing'
    assert client.post(publishing, json={'articles': True}, headers=admin).status_code == 409
    limits = {
        'daily_budget_micros': 1000, 'title_call_bound_micros': 100,
        'article_call_bound_micros': 300, 'detector_call_bound_micros': 50,
        'cost_bound_verified': True, 'article_limit': 1, 'image_limit': 0,
        'tracks': ['情感'],
    }
    assert client.put('/api/content-factory/admin/automation/limits',
                      json=limits, headers=admin).status_code == 200
    assert client.post(publishing, json={'articles': True}, headers=admin).status_code == 409
    assert client.post('/api/content-factory/admin/automation/enable-title-planning',
                       headers=admin).status_code == 200
    assert client.post(publishing, json={'articles': True}, headers=admin).status_code == 409
    assert client.post('/api/content-factory/admin/automation/enable-production',
                       json={'articles': True}, headers=admin).status_code == 200
    assert client.post(publishing, json={'articles': True}, headers=admin).json() == {
        'automatic_article_publish': True, 'automatic_image_publish': False}

    assert client.post('/api/content-factory/admin/automation/emergency-stop',
                       headers=admin).status_code == 200
    state = client.get('/api/content-factory/admin/automation', headers=admin).json()
    for name in ('emergency_stop',):
        assert state[name] is True
    for name in ('automatic_selection', 'scheduled_selection', 'automatic_articles',
                 'automatic_images', 'automatic_article_publish', 'automatic_image_publish'):
        assert state[name] is False


def test_manual_retry_is_bounded_and_does_not_consume_a_second_daily_slot(client, monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from server import content_factory_v3_tasks
    from server.content_factory_v3_store import ensure_settings, runs, settings
    day = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    admin = {'x-admin':'1'}
    candidate = {
        'track': '情感',
        'source': {'id': 'retry-source', 'title': '来源标题',
                   'url': 'https://example.com/retry', 'observed_at': day},
    }
    with database.ENGINE.begin() as connection:
        ensure_settings(connection)
        run = stage_candidate(connection, day=day, product_type='article',
                              candidate=candidate, angle='沟通')
        connection.execute(runs.update().where(runs.c.id == run['id']).values(
            status='held', error='production_failed', production_day=day,
            titles_json='{"main_title":"家庭沟通从听懂开始"}'))
        connection.execute(settings.update().where(settings.c.id == 1).values(
            emergency_stop=False, automatic_selection=True, automatic_articles=True,
            cost_bound_verified=True, daily_budget_micros=1000,
            title_call_bound_micros=100, article_call_bound_micros=300,
            detector_call_bound_micros=50, article_limit=1, image_limit=0,
            tracks_json='["情感"]'))
    dispatched = []
    monkeypatch.setattr(content_factory_v3_tasks.produce_draft, 'apply_async',
                        lambda **kwargs: dispatched.append(kwargs))
    path = f"/api/content-factory/admin/automation/runs/{run['id']}/retry"
    assert client.post(path, headers=admin).json()['attempt'] == 1
    with database.ENGINE.begin() as connection:
        connection.execute(runs.update().where(runs.c.id == run['id']).values(
            status='held', error='production_failed'))
    assert client.post(path, headers=admin).json()['attempt'] == 2
    with database.ENGINE.begin() as connection:
        connection.execute(runs.update().where(runs.c.id == run['id']).values(
            status='held', error='production_failed'))
    assert client.post(path, headers=admin).status_code == 409
    assert len(dispatched) == 2


def test_overdue_running_task_requires_admin_manual_marking(client):
    from datetime import timedelta
    from server.content_factory_v3_store import runs
    day = datetime.now(timezone.utc).date().isoformat()
    candidate = {
        'track': '情感',
        'source': {'id': 'stale-source', 'title': '来源标题',
                   'url': 'https://example.com/stale', 'observed_at': day},
    }
    with database.ENGINE.begin() as connection:
        run = stage_candidate(connection, day=day, product_type='article',
                              candidate=candidate, angle='沟通')
        connection.execute(runs.update().where(runs.c.id == run['id']).values(
            status='production_running',
            updated_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()))
    path = f"/api/content-factory/admin/automation/runs/{run['id']}/mark-stale"
    assert client.post(path).status_code == 403
    response = client.post(path, headers={'x-admin': '1'})
    assert response.status_code == 200
    assert response.json()['status'] == 'held'
    assert response.json()['previous_status'] == 'production_running'
    with database.ENGINE.connect() as connection:
        row = connection.execute(runs.select().where(runs.c.id == run['id'])).mappings().one()
    assert row['error'] == 'execution_state_unknown' and row['attempt'] == 0
    assert client.post(path, headers={'x-admin': '1'}).status_code == 409


def test_metrics_and_exception_pool_require_admin_and_report_auditable_counts(client):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from server.content_factory_v3_store import (detections, quality_reports, runs,
                                                  stage_candidate)
    day = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    held_candidate = {
        'track': '情感',
        'source': {'id': 'metrics-held', 'title': '来源一',
                   'url': 'https://example.com/one', 'observed_at': day},
    }
    published_candidate = {
        'track': '成长',
        'source': {'id': 'metrics-published', 'title': '来源二',
                   'url': 'https://example.com/two', 'observed_at': day},
    }
    with database.ENGINE.begin() as connection:
        held = stage_candidate(connection, day=day, product_type='article',
                               candidate=held_candidate, angle='角度一')
        published = stage_candidate(connection, day=day, product_type='article',
                                    candidate=published_candidate, angle='角度二')
        connection.execute(runs.update().where(runs.c.id == held['id']).values(
            status='held', error='production_failed', production_day=day,
            product_id='product-held'))
        connection.execute(runs.update().where(runs.c.id == published['id']).values(
            status='published', product_id='product-published', production_day=day))
        connection.execute(quality_reports.insert().values(
            id='quality-one', run_id=published['id'], product_id='product-published',
            attempt=0, status='eligible', report_json='{}', created_at=day))
        connection.execute(detections.insert().values(
            id='detector-one', run_id=published['id'], content_hash='a' * 64,
            provider='@makers/zhuque-text', status='success', human_ratio='0.9',
            created_at=day))
        connection.execute(budget_reservations.insert().values(
            idempotency_key='metrics-budget', day=day, bound_micros=125,
            amount_micros=125, status='reserved', created_at=day))

    assert client.get('/api/content-factory/admin/automation/metrics').status_code == 403
    assert client.get('/api/content-factory/admin/automation/exceptions').status_code == 403
    metrics = client.get('/api/content-factory/admin/automation/metrics',
                         headers={'x-admin':'1'}).json()
    assert metrics['candidates'] == 2
    assert metrics['articles_generated'] == 2
    assert metrics['quality_passed'] == 1
    assert metrics['detector_passed'] == 1
    assert metrics['auto_published'] == 1
    assert metrics['held'] == 1 and metrics['failed'] == 1
    assert metrics['cost_micros'] == 125
    exceptions = client.get('/api/content-factory/admin/automation/exceptions',
                            headers={'x-admin':'1'}).json()
    assert [row['id'] for row in exceptions] == [held['id']]


def test_automation_endpoint_returns_503_when_a_known_column_is_missing(client):
    with database.ENGINE.begin() as connection:
        connection.exec_driver_sql(
            'ALTER TABLE content_factory_v3_runs DROP COLUMN attempt')
    response = client.get('/api/content-factory/admin/automation',
                          headers={'x-admin':'1'})
    assert response.status_code == 503
    assert '结构不完整' in response.json()['detail']


def test_title_task_reserves_budget_once_and_stores_result(client, monkeypatch):
    from server import content_factory_v3_tasks
    source = {'track': '情感', 'topic': '家庭沟通', 'source': {'id': 'one', 'title': '来源标题',
              'url': 'https://example.com/a', 'observed_at': '2026-11-07'}}
    with database.ENGINE.begin() as connection:
        run = stage_candidate(connection, day='2026-11-07', product_type='article', candidate=source, angle='沟通')
    admin = {'x-admin':'1'}
    path = f"/api/content-factory/admin/automation/runs/{run['id']}/generate-titles"
    assert client.post(path, headers=admin).status_code == 409
    limits = {'daily_budget_micros': 1000, 'title_call_bound_micros': 100,
              'cost_bound_verified': True, 'article_limit': 1, 'image_limit': 0, 'tracks':['情感']}
    assert client.put('/api/content-factory/admin/automation/limits', json=limits, headers=admin).status_code == 200
    assert client.post('/api/content-factory/admin/automation/enable-title-planning', headers=admin).status_code == 200
    dispatched = []
    monkeypatch.setattr(content_factory_v3_tasks.generate_titles, 'apply_async', lambda **kw: dispatched.append(kw))
    assert client.post(path, headers=admin).json()['existing'] is False
    assert client.post(path, headers=admin).json()['existing'] is True
    redispatch = client.post(
        f"/api/content-factory/admin/automation/runs/{run['id']}/dispatch",
        headers=admin)
    assert redispatch.status_code == 200 and redispatch.json()['dispatched'] is True
    assert len(dispatched) == 2
    plan = {'main_title': '家庭沟通从听懂开始', 'alternative_titles': ['说清需求才容易商量',
            '给亲密关系留一些空间', '吵架之后如何继续对话'], 'strategy': '问题解决', 'reason': '围绕沟通'}
    monkeypatch.setattr(content_factory_v3_tasks, '_single_json_call', lambda prompt, **kwargs: plan)
    assert content_factory_v3_tasks.generate_titles.run(run['id'])['status'] == 'title_ready'
    assert content_factory_v3_tasks.generate_titles.run(run['id'])['status'] == 'ignored'
    with database.ENGINE.connect() as connection:
        assert len(connection.execute(budget_reservations.select()).all()) == 1


def test_article_production_is_bounded_and_never_auto_publishes_unknown_quality(client, monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from server import content_factory_v3_tasks
    from server.content_factory_v3_store import runs, product_details
    day = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    candidate = {'track': '情感', 'topic': '家庭沟通', 'source': {'id':'one', 'title':'来源标题',
                 'url':'https://example.com/a', 'observed_at':day}}
    with database.ENGINE.begin() as connection:
        run = stage_candidate(connection, day=day, product_type='article', candidate=candidate, angle='沟通')
    admin = {'x-admin':'1'}
    limits = {'daily_budget_micros': 1000, 'title_call_bound_micros': 100, 'article_call_bound_micros': 300, 'detector_call_bound_micros': 50,
              'vision_call_bound_micros': 50,
              'cost_bound_verified': True, 'article_limit': 1, 'image_limit': 0, 'tracks':['情感']}
    assert client.put('/api/content-factory/admin/automation/limits', json=limits, headers=admin).status_code == 200
    assert client.post('/api/content-factory/admin/automation/enable-title-planning', headers=admin).status_code == 200
    assert client.post('/api/content-factory/admin/automation/enable-production', json={'articles':True}, headers=admin).status_code == 200
    plan = {'main_title':'家庭沟通从听懂开始', 'alternative_titles':['说清需求才容易商量','给亲密关系留一些空间','吵架之后如何继续对话'],
            'strategy':'问题解决', 'reason':'围绕沟通'}
    assert client.put(f"/api/content-factory/admin/automation/runs/{run['id']}/titles", json=plan, headers=admin).status_code == 200
    queued = []
    monkeypatch.setattr(content_factory_v3_tasks.produce_draft, 'apply_async', lambda **kw: queued.append(kw))
    path = f"/api/content-factory/admin/automation/runs/{run['id']}/produce"
    assert client.post(path, headers=admin).json()['existing'] is False
    assert client.post(path, headers=admin).json()['existing'] is True and len(queued) == 1
    monkeypatch.setattr(content_factory_v3_tasks, '_single_json_call', lambda prompt, **kwargs: {'content':'文'*1000,'summary':'摘要'})
    monkeypatch.setattr(content_factory_v3_tasks.creator_tools, 'detect_article', lambda *args, **kwargs: {
        'scores': {'total': 75}, 'source_ledger': [],
        'editorial_gate': {'status': 'human_review', 'blockers': [], 'revisions': [], 'confirmations': []},
        'compliance': [], 'content_risk': {'substantive': [], 'confirm': [], 'machine': []},
        'evidence': [{'type': 'alignment', 'severity': 'review'}]})
    from server import content_factory_detector
    monkeypatch.setattr(content_factory_detector, 'detect', lambda text: {'status':'success','human_ratio':0.9,'makers_tokens':10})
    result = content_factory_v3_tasks.produce_draft.run(run['id'])
    assert result['status'] == 'held'
    with database.ENGINE.connect() as connection:
        product = connection.execute(products.select().where(products.c.id == result['product_id'])).mappings().one()
        state = connection.execute(runs.select().where(runs.c.id == run['id'])).mappings().one()
        detail = connection.execute(product_details.select()).mappings().one()
    assert product['status'] == 'draft' and product['price_points'] == 10
    assert state['status'] == 'held' and 'check_not_passed:title_consistency' in state['quality_json']
    assert 'alternative_titles' in detail['details_json']


def test_image_production_creates_private_held_image(client, monkeypatch):
    import base64
    import io
    from datetime import datetime
    from pathlib import Path
    from zoneinfo import ZoneInfo
    from PIL import Image
    from server import content_factory_v3_tasks
    from server.content_factory_v3_store import runs
    font = next((p for p in (Path('C:/Windows/Fonts/msyh.ttc'), Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')) if p.is_file()), None)
    if not font:
        pytest.skip('Chinese font unavailable')
    monkeypatch.setenv('CONTENT_FACTORY_FONT_PATH', str(font))
    day = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    candidate = {'track':'情感', 'topic':'家庭沟通', 'source': {'id':'image-one', 'title':'来源标题',
                 'url':'https://example.com/a', 'observed_at':day}}
    with database.ENGINE.begin() as connection:
        run = stage_candidate(connection, day=day, product_type='image', candidate=candidate, angle='沟通')
    admin={'x-admin':'1'}
    limits={'daily_budget_micros':1000,'title_call_bound_micros':100,'image_call_bound_micros':300,
            'vision_call_bound_micros':50,
            'cost_bound_verified':True,'article_limit':0,'image_limit':1,'tracks':['情感']}
    assert client.put('/api/content-factory/admin/automation/limits',json=limits,headers=admin).status_code==200
    assert client.post('/api/content-factory/admin/automation/enable-title-planning',headers=admin).status_code==200
    assert client.post('/api/content-factory/admin/automation/enable-production',json={'images':True},headers=admin).status_code==200
    plan={'main_title':'好好说话让关系更近','alternative_titles':['认真听完对方的话','争执之后如何和好'],
          'image_text':'慢一点说','caption':'留出说话的空间','tags':['家庭','沟通','生活'],
          'strategy':'家庭情感','reason':'围绕对话'}
    assert client.put(f"/api/content-factory/admin/automation/runs/{run['id']}/titles",json=plan,headers=admin).status_code==200
    monkeypatch.setattr(content_factory_v3_tasks.produce_draft,'apply_async',lambda **kw:None)
    assert client.post(f"/api/content-factory/admin/automation/runs/{run['id']}/produce",headers=admin).status_code==200
    stream=io.BytesIO(); Image.new('RGB',(300,400),'navy').save(stream,format='PNG')
    monkeypatch.setattr(content_factory_v3_tasks.image_provider,'generate',lambda payload:{'data':[{'b64_json':base64.b64encode(stream.getvalue()).decode()}]})
    monkeypatch.setattr(content_factory_v3_tasks, 'review_image', lambda *args, **kwargs: {
        'status':'failed', 'error':'visual_review_failed'})
    monkeypatch.setattr(content_factory_v3_tasks.creator_tools, 'detect_article', lambda *args, **kwargs: {
        'scores': {'total': 75},
        'editorial_gate': {'status': 'human_review', 'blockers': [], 'revisions': [], 'confirmations': []},
        'compliance': [], 'content_risk': {'substantive': [], 'confirm': [], 'machine': []},
        'evidence': []})
    result=content_factory_v3_tasks.produce_draft.run(run['id'])
    assert result['status']=='held'
    with database.ENGINE.connect() as connection:
        product=connection.execute(products.select().where(products.c.id==result['product_id'])).mappings().one()
        state=connection.execute(runs.select().where(runs.c.id==run['id'])).mappings().one()
    assert product['status']=='draft' and product['price_points']==5 and product['image_data']
    assert 'check_not_passed:visual_quality' in state['quality_json']
    assert client.get(f"/api/content-factory/products/{product['id']}/image").status_code==404


def test_scheduled_selection_is_disabled_by_default_and_deduplicates(client, monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from server import content_factory_opportunities, content_factory_v3_tasks
    assert content_factory_v3_tasks.schedule_candidates.run()['status'] == 'disabled'
    day = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    with database.ENGINE.begin() as connection:
        connection.execute(LowfansArticle.__table__.update().values(
            stat_date=day, wx_type='情感', title='家庭关系如何沟通', account_read_base=100,
            boost_ratio=100, read_num=100001))
    admin={'x-admin':'1'}
    limits={'daily_budget_micros':1000,'title_call_bound_micros':100,'article_call_bound_micros':300,
            'detector_call_bound_micros':50,'cost_bound_verified':True,'article_limit':1,'image_limit':0,
            'minimum_score':70,'tracks':['情感']}
    assert client.put('/api/content-factory/admin/automation/limits',json=limits,headers=admin).status_code == 200
    assert client.post('/api/content-factory/admin/automation/enable-title-planning',headers=admin).status_code == 200
    assert client.post('/api/content-factory/admin/automation/enable-production',json={'articles':True},headers=admin).status_code == 200
    assert client.put('/api/content-factory/admin/automation/schedule',json={'enabled':True},headers=admin).status_code == 200
    monkeypatch.setattr(content_factory_opportunities,'match_topics',lambda *args:[])
    calls=[]
    monkeypatch.setattr(content_factory_v3_tasks.generate_titles,'apply_async',lambda **kw:calls.append(kw))
    assert content_factory_v3_tasks.schedule_candidates.run()['queued'] == 1
    assert content_factory_v3_tasks.schedule_candidates.run()['queued'] == 0
    assert len(calls) == 1


def test_article_gate_rejects_short_and_low_human_ratio(client, monkeypatch):
    admin = {'x-admin': '1'}
    payload = {'source_row_id': 1, 'product_type': 'article', 'title': '文章', 'content': '短文', 'price_points': 10}
    ident = client.post('/api/content-factory/admin/products', json=payload, headers=admin).json()['id']
    assert client.post(f'/api/content-factory/admin/products/{ident}/publish', headers=admin).status_code == 400
    payload['content'] = '文' * 1000
    assert client.put(f'/api/content-factory/admin/products/{ident}', json=payload, headers=admin).status_code == 200
    class Low:
        def raise_for_status(self): pass
        def json(self): return {'status': 'success', 'labels_ratio': {'0': 0.79}}
    monkeypatch.setattr(content_factory.requests, 'post', lambda *a, **kw: Low())
    assert client.post(f'/api/content-factory/admin/products/{ident}/publish', headers=admin).status_code == 400


def test_same_article_cannot_be_listed_twice(client):
    payload = {"source_row_id": 1, "product_type": "article", "title": "文章", "content": "同一 篇文章" * 200, "price_points": 5}
    admin = {'x-admin':'1'}
    first = client.post('/api/content-factory/admin/products', json=payload, headers=admin).json()['id']
    assert client.post(f'/api/content-factory/admin/products/{first}/publish', headers=admin).status_code == 200
    payload['content'] = '同一篇文章' * 200
    second = client.post('/api/content-factory/admin/products', json=payload, headers=admin).json()['id']
    assert client.post(f'/api/content-factory/admin/products/{second}/publish', headers=admin).status_code == 409


def test_generation_uses_platform_provider_and_saves_draft(client, monkeypatch):
    from server import content_factory_tasks
    payload = {"source_row_id": 1, "product_type": "article", "title": "文章", "price_points": 5}
    ident = client.post('/api/content-factory/admin/products', json=payload, headers={'x-admin':'1'}).json()['id']
    with database.ENGINE.begin() as con:
        con.execute(jobs.insert().values(id='job', product_id=ident, angle='原创角度', status='queued', created_at='now'))
    monkeypatch.setattr(content_factory_tasks.wechat_plus_service, 'generate_json', lambda prompt: {'content':'生成后的原创草稿'})
    content_factory_tasks.generate_article.run('job')
    with database.ENGINE.connect() as con:
        assert con.execute(products.select().where(products.c.id == ident)).mappings().first()['content'] == '生成后的原创草稿'
        assert con.execute(jobs.select().where(jobs.c.id == 'job')).mappings().first()['status'] == 'completed'


def test_image_is_only_available_to_buyer(client):
    import io
    from PIL import Image
    data = io.BytesIO()
    Image.new('RGB', (12, 16), 'red').save(data, format='PNG')
    payload = {"source_row_id": 1, "product_type": "image", "title": "图片", "content": "配文", "price_points": 5}
    admin = {'x-admin':'1'}
    ident = client.post('/api/content-factory/admin/products', json=payload, headers=admin).json()['id']
    assert client.post(f'/api/content-factory/admin/products/{ident}/publish', headers=admin).status_code == 400
    assert client.put(f'/api/content-factory/admin/products/{ident}/image', content=data.getvalue(), headers=admin).status_code == 200
    assert client.post(f'/api/content-factory/admin/products/{ident}/publish', headers=admin).status_code == 200
    preview = client.get(f'/api/content-factory/products/{ident}/preview-image')
    assert preview.status_code == 200 and preview.content != data.getvalue()
    assert client.get(f'/api/content-factory/products/{ident}/image').status_code == 404
    assert client.post(f'/api/content-factory/products/{ident}/purchase').status_code == 200
    result = client.get(f'/api/content-factory/products/{ident}/image')
    assert result.content == data.getvalue()
    assert result.headers['cache-control'] == 'private, no-store'
    assert client.get(f'/api/content-factory/products/{ident}/image', headers={'x-user':'b'}).status_code == 404
    assert client.put(f'/api/content-factory/admin/products/{ident}', json=payload, headers=admin).status_code == 409


def test_expired_worker_cannot_overwrite_recovered_job(client, monkeypatch):
    from server import content_factory_tasks
    payload = {"source_row_id": 1, "product_type": "article", "title": "文章", "price_points": 5}
    ident = client.post('/api/content-factory/admin/products', json=payload, headers={'x-admin':'1'}).json()['id']
    with database.ENGINE.begin() as con:
        con.execute(jobs.insert().values(id='recovered', product_id=ident, angle='角度', status='queued', created_at='now'))
    def delayed_result(_prompt):
        with database.ENGINE.begin() as con:
            con.execute(jobs.update().where(jobs.c.id == 'recovered').values(lease_token='new-worker'))
        return {'content': '过期任务不能覆盖的新内容'}
    monkeypatch.setattr(content_factory_tasks.wechat_plus_service, 'generate_json', delayed_result)
    content_factory_tasks.generate_article.run('recovered')
    with database.ENGINE.connect() as con:
        assert con.execute(products.select().where(products.c.id == ident)).mappings().first()['content'] == ''
        assert con.execute(jobs.select().where(jobs.c.id == 'recovered')).mappings().first()['lease_token'] == 'new-worker'
