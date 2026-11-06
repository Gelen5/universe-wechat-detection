from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from tests import support  # noqa: F401 - isolate before importing database

from server import content_factory, database
from server.content_factory_purchase import jobs, metadata, products
from server.models import LowfansArticle, PointTransaction, Wallet


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'api.db').as_posix()}", connect_args={"check_same_thread": False})
    metadata.create_all(engine)
    for table in (LowfansArticle.__table__, Wallet.__table__, PointTransaction.__table__):
        table.create(engine)
    monkeypatch.setattr(database, "ENGINE", engine)
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
    payload = {"source_row_id": 1, "product_type": "article", "title": "原创文章", "track": "情感", "preview": "节选", "content": "只给买家看的完整文章", "price_points": 5}
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


def test_same_article_cannot_be_listed_twice(client):
    payload = {"source_row_id": 1, "product_type": "article", "title": "文章", "content": "同一 篇文章", "price_points": 5}
    admin = {'x-admin':'1'}
    first = client.post('/api/content-factory/admin/products', json=payload, headers=admin).json()['id']
    assert client.post(f'/api/content-factory/admin/products/{first}/publish', headers=admin).status_code == 200
    payload['content'] = '同一篇文章'
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
