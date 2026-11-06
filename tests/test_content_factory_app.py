"""Real application middleware and cookie authentication smoke test."""
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from tests import support  # noqa: F401

from server import accounts, database
from server.content_factory_purchase import metadata
from server.main import app
from server.models import LowfansArticle


def test_app_purchase_flow():
    metadata.create_all(database.ENGINE)
    with database.ENGINE.begin() as connection:
        connection.execute(LowfansArticle.__table__.insert().values(
            stat_date="2026-11-01", range_type="7d", art_id="factory-test", title="来源标题",
            art_url="https://example.com/source", captured_at=datetime.now(timezone.utc)))
        row_id = connection.execute(LowfansArticle.__table__.select().where(LowfansArticle.art_id == "factory-test")).mappings().first()['id']
    buyer = TestClient(app)
    admin = TestClient(app)
    user = buyer.post('/api/auth/register', json={'email':'factory@example.com','password':'testing-pass-123'}).json()['user']
    assert admin.post('/api/auth/login', json={'email':'admin@example.com','password':'testing-pass-123'}).status_code == 200
    assert admin.post('/api/admin/recharge', json={'user_id':user['id'],'points':10,'bucket':'trial','note':'test'}).status_code == 200
    assert buyer.get('/content-factory').status_code == 200
    response = admin.post('/api/content-factory/admin/products', json={
        'source_row_id': row_id, 'product_type':'article', 'title':'文章', 'content':'付费内容', 'price_points':5})
    assert response.status_code == 200, response.text
    ident = response.json()['id']
    assert admin.post(f'/api/content-factory/admin/products/{ident}/publish').status_code == 200
    guest = TestClient(app)
    assert guest.get('/api/content-factory/products').status_code == 200
    assert guest.post(f'/api/content-factory/products/{ident}/purchase').status_code == 401
    assert guest.get(f'/api/content-factory/products/{ident}/content').status_code == 401
    assert buyer.post(f'/api/content-factory/products/{ident}/purchase').status_code == 200
    assert buyer.post(f'/api/content-factory/products/{ident}/purchase').json()['already_owned']
    assert accounts.wallet_summary(user['id'])['balance'] == 5
    assert buyer.get('/api/content-factory/products').json()[0]['owned'] is True
    assert guest.get('/api/content-factory/products').json()[0]['status'] == 'sold'
    assert guest.get('/api/content-factory/products').json()[0]['owned'] is False
    assert buyer.get(f'/api/content-factory/products/{ident}/content').json()['content'] == '付费内容'
    assert admin.get(f'/api/content-factory/products/{ident}/content').status_code == 404
