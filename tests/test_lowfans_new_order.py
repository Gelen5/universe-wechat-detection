import os
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from server import database, lowfans, lowfans_sync
from server.models import LowfansArticle


def test_new_entries_precede_old_across_pagination_and_export():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    with patch.object(database, 'ENGINE', engine), patch.object(database, 'SessionLocal',
            sessionmaker(bind=engine, expire_on_commit=False)), patch.dict(os.environ, {'VIRAL_INSIGHTS_PAYWALL_ENABLED': '0'}):
        lowfans_sync.init_schema()
        with database.session_scope() as session:
            session.add_all([
                LowfansArticle(stat_date='2026-11-01', range_type=lowfans.DEFAULT_RANGE, art_id='old', rank_no=1),
                LowfansArticle(stat_date='2026-11-02', range_type=lowfans.DEFAULT_RANGE, art_id='old', rank_no=1, title='old', read_num=999999),
                LowfansArticle(stat_date='2026-11-02', range_type=lowfans.DEFAULT_RANGE, art_id='new', rank_no=99, title='new', read_num=1),
            ])
        app = FastAPI()
        app.include_router(lowfans.router)
        with TestClient(app) as client:
            for sort in ('burst', 'read', 'boost', 'time'):
                first = client.get(f'/api/lowfans?sort={sort}&page_size=1').json()
                second = client.get(f'/api/lowfans?sort={sort}&page_size=1&page=2').json()
                assert first['items'][0]['art_id'] == 'new' and first['items'][0]['is_new']
                assert second['items'][0]['art_id'] == 'old' and not second['items'][0]['is_new']
            csv = client.post('/api/lowfans/export', json={'sort': 'read'}).text
            assert csv.index('new') < csv.index('old')
    engine.dispose()
