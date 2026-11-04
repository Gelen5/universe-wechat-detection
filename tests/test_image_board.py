import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from server import image_board
from server import database


class ImageBoardTests(unittest.TestCase):
    def test_row_preserves_book_fields_and_limits_content(self):
        row = image_board._row('2026-11-02', {
            'sn': 'abc', 'wx_type': '生活', 'content_type': 'book',
            'content': 'x' * 5000, 'word_num': 28, 'image_num': 1,
            'video_num': 0, 'read_num': 100001,
        })
        self.assertEqual('abc', row['sn'])
        self.assertEqual('book', row['content_type'])
        self.assertEqual(4000, len(row['content']))
        self.assertEqual(28, row['word_num'])

    def test_image_first_rule_excludes_video_and_long_text(self):
        class Item:
            word_num = 80
            video_num = 0
            image_num = 1
        self.assertTrue(image_board.is_image_first(Item()))
        Item.video_num = 1
        self.assertFalse(image_board.is_image_first(Item()))
        Item.video_num = 0
        Item.word_num = 101
        self.assertFalse(image_board.is_image_first(Item()))

    @patch.dict(os.environ, {'WXRANK_API_KEY': ''}, clear=False)
    def test_sync_does_not_call_upstream_without_key(self):
        result = image_board.sync('2026-11-02', pages=10)
        self.assertEqual('unconfigured', result['status'])

    def test_default_api_returns_all_200_items(self):
        engine = create_engine('sqlite://', connect_args={'check_same_thread': False},
                               poolclass=StaticPool)
        session_local = sessionmaker(bind=engine, expire_on_commit=False)
        with patch.object(database, 'ENGINE', engine), patch.object(database, 'SessionLocal', session_local):
            image_board.init_schema()
            image_board.store('2026-11-02', [
                {'sn': str(i), 'content_type': 'book', 'title': f'item {i}',
                 'word_num': 200 if i % 2 else 10, 'image_num': 1, 'read_num': i}
                for i in range(200)
            ], source='test')
            image_board.store('2026-11-02', [
                {'sn': 'partial', 'content_type': 'book', 'title': 'partial'}
            ], source='test', error='page 2 failed')
            app = FastAPI()
            app.include_router(image_board.router)
            with TestClient(app) as client:
                data = client.get('/api/image-board').json()
                self.assertEqual(200, data['total'])
                self.assertEqual(200, len(data['items']))
                self.assertEqual(100, data['counts']['image'])
                self.assertEqual(100, client.get('/api/image-board?scope=image').json()['total'])
                self.assertTrue(data['freshness']['stale'])
        engine.dispose()

    def test_fill_from_earlier_snapshots_deduplicates_and_filters_pool(self):
        engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        with patch.object(database, 'ENGINE', engine), patch.object(database, 'SessionLocal',
                sessionmaker(bind=engine, expire_on_commit=False)):
            image_board.init_schema()
            image_board.store('2026-11-01', [
                {'sn': str(i), 'content_type': 'book', 'title': f'old {i}', 'wx_type': '历史', 'read_num': i,
                 'pic_url': f'https://mmbiz.qpic.cn/old-{i}'}
                for i in range(200)], source='test')
            image_board.store('2026-11-02', [
                {'sn': str(i), 'content_type': 'book', 'title': f'new {i}', 'wx_type': '当日', 'read_num': i,
                 'pic_url': f'https://mmbiz.qpic.cn/new-{i}'}
                for i in range(132)], source='test')
            app = FastAPI()
            app.include_router(image_board.router)
            with patch.dict(os.environ, {'VIRAL_INSIGHTS_PAYWALL_ENABLED': '0'}), TestClient(app) as client:
                data = client.get('/api/image-board').json()
                self.assertEqual((200, 132, 68), (data['total'], data['primary_count'], data['fallback_count']))
                self.assertEqual(sorted((item['read_num'] for item in data['items']), reverse=True),
                                 [item['read_num'] for item in data['items']])
                self.assertTrue(data['items'][0]['is_fallback'])
                for sort in ('share', 'time'):
                    ordered = client.get(f'/api/image-board?sort={sort}').json()['items']
                    self.assertTrue(all(not item['is_fallback'] for item in ordered[:132]))
                self.assertEqual(200, len({item['sn'] for item in data['items']}))
                self.assertEqual(68, sum(item['is_fallback'] for item in data['items']))
                self.assertEqual('new 1', next(item['title'] for item in data['items'] if item['sn'] == '1'))
                self.assertEqual(68, client.get('/api/image-board?wx_type=历史').json()['total'])
                self.assertEqual(200, client.get('/api/image-board?date=2026-11-01').json()['total'])
            with patch.dict(os.environ, {'VIRAL_INSIGHTS_PAYWALL_ENABLED': '1'}), TestClient(app) as client:
                image_board.COVER_CACHE.clear()
                preview = client.get('/api/image-board').json()['items']
                self.assertEqual('old 199', preview[0]['title_preview'])
                with patch.object(image_board, '_cover_fetch', return_value=(b'img', 'image/png')) as fetch:
                    self.assertEqual(200, client.get(preview[0]['cover_url']).status_code)
                    self.assertTrue(fetch.call_args.args[0].endswith('old-199'))
                image_board.COVER_CACHE.clear()
        engine.dispose()

    def test_full_pool_puts_all_10k_items_before_lower_read_items(self):
        engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        with patch.object(database, 'ENGINE', engine), patch.object(database, 'SessionLocal',
                sessionmaker(bind=engine, expire_on_commit=False)), patch.dict(os.environ, {'VIRAL_INSIGHTS_PAYWALL_ENABLED': '0'}):
            image_board.init_schema()
            image_board.store('2026-11-01', [
                {'sn': f'high-{i}', 'content_type': 'book', 'read_num': 10000+i, 'title': f'high {i}'}
                for i in range(140)], source='test')
            image_board.store('2026-11-02', [
                {'sn': f'low-{i}', 'content_type': 'book', 'read_num': 9999, 'title': f'low {i}'}
                for i in range(150)], source='test')
            app = FastAPI()
            app.include_router(image_board.router)
            with TestClient(app) as client:
                for sort in ('read', 'share', 'time'):
                    data = client.get(f'/api/image-board?sort={sort}').json()
                    self.assertEqual(290, data['total'])
                    self.assertTrue(all(x['read_num'] >= 10000 for x in data['items'][:140]))
                    self.assertTrue(all(x['read_num'] < 10000 for x in data['items'][140:]))
        engine.dispose()

    @patch.dict(os.environ, {'WXRANK_API_KEY': 'test'}, clear=False)
    def test_sync_expands_only_when_more_qualifying_results_are_possible(self):
        class Response:
            def __init__(self, batch, cursor): self.batch, self.cursor = batch, cursor
            def raise_for_status(self): pass
            def json(self): return {'code': 0, 'data': {'list': self.batch, 'cursor': self.cursor}}
        pages = [[{'sn': f'id-{i}', 'read_num': 12000} for i in range(90)] for _ in range(10)]
        pages.append([{'sn': f'new-{i}', 'read_num': 11000} for i in range(10)])
        pages.append([{'sn': 'extra', 'read_num': 11000}])
        responses = [Response(batch, f'cursor-{i}') for i, batch in enumerate(pages)]
        with patch.object(image_board.requests, 'post', side_effect=responses) as post, \
             patch.object(image_board.time, 'sleep'), \
             patch.object(image_board, 'store', return_value={'inserted': 100, 'retained': 0}):
            image_board.sync('2026-11-03', pages=10, extended_pages=30)
        self.assertEqual(11, post.call_count)
        self.assertEqual('20261103', post.call_args_list[0].kwargs['json']['date'])
        self.assertEqual('read_num', post.call_args_list[0].kwargs['json']['sort'])
        self.assertEqual({'key': 'test', 'cursor': 'cursor-0'}, post.call_args_list[1].kwargs['json'])

    @patch.dict(os.environ, {'WXRANK_API_KEY': 'test'}, clear=False)
    def test_sync_stops_when_descending_results_drop_below_threshold(self):
        class Response:
            def raise_for_status(self): pass
            def json(self):
                return {'code': 0, 'data': {'list': [{'sn': 'same', 'read_num': 9999}], 'cursor': 'next'}}
        with patch.object(image_board.requests, 'post', return_value=Response()) as post, \
             patch.object(image_board.time, 'sleep'), \
             patch.object(image_board, 'store', return_value={'inserted': 1, 'retained': 0}):
            image_board.sync('2026-11-03', pages=10, extended_pages=30)
        self.assertEqual(10, post.call_count)


if __name__ == '__main__':
    unittest.main()
