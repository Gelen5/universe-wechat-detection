import hashlib
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
                default = client.get('/api/image-board').json()
                self.assertEqual((200, 40, True, 40, 0),
                                 (default['total'], len(default['items']),
                                  default['has_more'], default['limit'], default['offset']))
                data = client.get('/api/image-board?limit=200').json()
                self.assertEqual(200, data['total'])
                self.assertEqual(200, len(data['items']))
                self.assertFalse(data['has_more'])
                self.assertEqual(100, data['counts']['image'])
                images = client.get('/api/image-board?scope=image&limit=200').json()
                self.assertEqual((100, 100), (images['total'], len(images['items'])))
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
                data = client.get('/api/image-board?limit=200').json()
                self.assertEqual((200, 132, 68), (data['total'], data['primary_count'], data['fallback_count']))
                self.assertEqual(sorted((item['read_num'] for item in data['items']), reverse=True),
                                 [item['read_num'] for item in data['items']])
                self.assertTrue(data['items'][0]['is_fallback'])
                for sort in ('share', 'time'):
                    ordered = client.get(f'/api/image-board?sort={sort}&limit=200').json()['items']
                    self.assertTrue(all(not item['is_fallback'] for item in ordered[:132]))
                self.assertEqual(200, len({item['sn'] for item in data['items']}))
                self.assertEqual(68, sum(item['is_fallback'] for item in data['items']))
                self.assertEqual('new 1', next(item['title'] for item in data['items'] if item['sn'] == '1'))
                self.assertEqual(68, client.get('/api/image-board?wx_type=历史&limit=200').json()['total'])
                self.assertEqual(200, client.get('/api/image-board?date=2026-11-01&limit=200').json()['total'])
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
                    data = client.get(f'/api/image-board?sort={sort}&limit=200').json()
                    self.assertEqual(290, data['total'])
                    self.assertTrue(data['has_more'])
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

    def test_pagination_contract_metadata_invariance_and_rank(self):
        engine = create_engine('sqlite://', connect_args={'check_same_thread': False},
                               poolclass=StaticPool)
        with patch.object(database, 'ENGINE', engine), patch.object(
                database, 'SessionLocal', sessionmaker(bind=engine, expire_on_commit=False)), \
                patch.dict(os.environ, {'VIRAL_INSIGHTS_PAYWALL_ENABLED': '0'}):
            image_board.init_schema()
            image_board.store('2026-11-02', [
                {'sn': f's{i:03d}', 'content_type': 'book', 'title': f'item {i}',
                 'read_num': 1000 + i, 'word_num': 10, 'image_num': 1,
                 'pic_url': f'https://mmbiz.qpic.cn/{i}.jpg', 'content': 'x' * 1126}
                for i in range(200)], source='test')
            app = FastAPI()
            app.include_router(image_board.router)
            with TestClient(app) as client:
                first = client.get('/api/image-board?limit=40&offset=0').json()
                second = client.get('/api/image-board?limit=40&offset=40').json()
                last = client.get('/api/image-board?limit=40&offset=160').json()
                self.assertEqual(list(range(1, 41)), [x['rank_no'] for x in first['items']])
                self.assertEqual(list(range(41, 81)), [x['rank_no'] for x in second['items']])
                self.assertEqual(list(range(161, 201)), [x['rank_no'] for x in last['items']])
                self.assertFalse({x['sn'] for x in first['items']} &
                                 {x['sn'] for x in second['items']})
                self.assertTrue(first['has_more'] and second['has_more'])
                self.assertFalse(last['has_more'])
                small = client.get('/api/image-board?limit=40').json()
                large = client.get('/api/image-board?limit=200').json()
                for key in ('total', 'counts', 'categories', 'primary_count', 'fallback_count'):
                    self.assertEqual(small[key], large[key], key)
                self.assertEqual((200, 40, 0), (small['total'], small['limit'], small['offset']))
                self.assertEqual(200, len(large['items']))
        engine.dispose()

    def test_cover_cache_headers_and_versioned_url(self):
        engine = create_engine('sqlite://', connect_args={'check_same_thread': False},
                               poolclass=StaticPool)
        picture = 'https://mmbiz.qpic.cn/cover.jpg'
        with patch.object(database, 'ENGINE', engine), patch.object(
                database, 'SessionLocal', sessionmaker(bind=engine, expire_on_commit=False)):
            image_board.init_schema()
            image_board.store('2026-11-02', [
                {'sn': 'cover-sn', 'content_type': 'book', 'title': 'cover',
                 'read_num': 12000, 'image_num': 1, 'pic_url': picture}], source='test')
            app = FastAPI()
            app.include_router(image_board.router)
            with patch.dict(os.environ, {'VIRAL_INSIGHTS_PAYWALL_ENABLED': '0'}), \
                    TestClient(app) as client:
                data = client.get('/api/image-board?limit=200').json()
                cover_url = data['items'][0]['cover_url']
                version = hashlib.sha1(picture.encode('utf-8')).hexdigest()[:8]
                self.assertIn(f'&v={version}', cover_url)
                image_board.COVER_CACHE.clear()
                with patch.object(image_board, '_cover_fetch',
                                  return_value=(b'img', 'image/png')):
                    response = client.get(cover_url)
                self.assertEqual(200, response.status_code)
                self.assertEqual('public, max-age=86400',
                                 response.headers['cache-control'])
                self.assertNotIn('pragma', response.headers)
            image_board.COVER_CACHE.clear()
            with patch.dict(os.environ, {'VIRAL_INSIGHTS_PAYWALL_ENABLED': '1'}), \
                    patch.object(image_board.membership, 'require_access',
                                 lambda request: None), TestClient(app) as client:
                with patch.object(image_board, '_cover_fetch',
                                  return_value=(b'img', 'image/png')):
                    response = client.get(cover_url)
                self.assertEqual('private, max-age=86400',
                                 response.headers['cache-control'])
                self.assertNotIn('pragma', response.headers)
        engine.dispose()

    def test_board_pool_selects_columns_and_content_excerpt(self):
        engine = create_engine('sqlite://', connect_args={'check_same_thread': False},
                               poolclass=StaticPool)
        with patch.object(database, 'ENGINE', engine), patch.object(
                database, 'SessionLocal', sessionmaker(bind=engine, expire_on_commit=False)):
            image_board.init_schema()
            image_board.store('2026-11-02', [
                {'sn': 'pruned', 'content_type': 'book', 'title': 'pruned',
                 'content': 'x' * 1126, 'pic_url': 'https://mmbiz.qpic.cn/p.jpg',
                 'read_num': 12000, 'image_num': 1}], source='test')
            with database.session_scope() as session:
                rows = image_board._board_pool(session, '2026-11-02')
            row = rows[0]
            self.assertFalse(isinstance(row, image_board.ImageBoardItem))
            self.assertTrue(hasattr(row, 'content_excerpt'))
            self.assertFalse(hasattr(row, 'content'))
            self.assertEqual(200, len(row.content_excerpt))
            self.assertEqual('pruned', row.sn)
        engine.dispose()

    def test_cover_middleware_keeps_handler_cache_for_success_only(self):
        import asyncio
        from types import SimpleNamespace
        from starlette.responses import Response
        from server import main

        async def cover_next(request):
            return Response(b'img', media_type='image/jpeg',
                            headers={'Cache-Control': 'private, max-age=86400'})

        cover_request = SimpleNamespace(
            url=SimpleNamespace(path='/api/image-board/cover'), query_params={})
        response = asyncio.run(main.disable_frontend_cache(cover_request, cover_next))
        self.assertEqual('private, max-age=86400', response.headers['cache-control'])
        self.assertNotIn('pragma', response.headers)

        async def other_next(request):
            return Response('{}', media_type='application/json',
                            headers={'Cache-Control': 'public, max-age=86400'})

        other_request = SimpleNamespace(
            url=SimpleNamespace(path='/api/lowfans'), query_params={})
        response = asyncio.run(main.disable_frontend_cache(other_request, other_next))
        self.assertEqual('private, no-store, max-age=0', response.headers['cache-control'])
        self.assertEqual('no-cache', response.headers['pragma'])

        async def error_next(request):
            return Response('{}', status_code=403, media_type='application/json')

        response = asyncio.run(main.disable_frontend_cache(cover_request, error_next))
        self.assertEqual('private, no-store, max-age=0', response.headers['cache-control'])


if __name__ == '__main__':
    unittest.main()
