"""Public library routing, curated provenance and the existing auth boundary."""
import json
import unittest
from pathlib import Path
from urllib.parse import urlparse

from tests import support  # isolate all application storage from real accounts
from fastapi.testclient import TestClient
from server.main import app

ROOT = Path(__file__).resolve().parents[1]


class BookshelfTests(unittest.TestCase):
    def test_public_routes_and_existing_private_apis(self):
        with TestClient(app) as client:
            self.assertEqual(client.get('/bookshelf').status_code, 200)
            detail = client.get('/bookshelf/codex')
            self.assertEqual(detail.status_code, 200)
            self.assertIn('OpenAI Codex 橙皮书 · AI 书架', detail.text)
            self.assertEqual(client.get('/bookshelf/missing').status_code, 404)
            self.assertEqual(client.get('/api/wallet').status_code, 401)
            for route in ('/', '/workbench', '/morning-generator', '/qihaoshou'):
                response = client.get(route)
                self.assertEqual(response.status_code, 200)
            self.assertIn('href="/bookshelf"', client.get('/workbench').text)

    def test_catalog_is_complete_sourced_and_does_not_mirror_restricted_text(self):
        data = json.loads((ROOT / 'static/bookshelf-data.json').read_text(encoding='utf-8'))
        self.assertEqual(len(data['books']), 21)
        self.assertEqual(len({b['id'] for b in data['books']}), 21)
        for book in data['books']:
            self.assertEqual(book['readingMode'], 'official')
            self.assertEqual(urlparse(book['githubUrl']).netloc, 'github.com')
            self.assertEqual(urlparse(book['readUrl']).scheme, 'https')
            self.assertIs(type(book['stars']), int)
            self.assertTrue(book['starsUpdatedAt'])
            self.assertTrue(book['author'])
            self.assertTrue(book['license']['url'])
            self.assertNotIn('chapters', book)
            self.assertNotIn('content', book)

    def test_life_guides_have_sources_authors_and_risk_notes(self):
        data = json.loads((ROOT / 'static/bookshelf-data.json').read_text(encoding='utf-8'))
        books = {book['id']: book for book in data['books']}
        additions = {'cook', 'life-level-up', 'live-better', 'everyone-english',
                     'smart-questions', 'live-longer', 'human-system', 'side-income',
                     'selfteaching', 'regular-investing'}
        audit = json.loads((ROOT / 'docs/bookshelf-source-audit.json').read_text(encoding='utf-8'))
        audited = {record['id'] for record in audit['records']}
        for ident in additions:
            with self.subTest(ident=ident):
                self.assertIn(ident, audited)
                self.assertNotIn('utm_source', books[ident]['githubUrl'])
                self.assertNotIn('花叔', books[ident]['author'])
                self.assertEqual('生活与成长指南', books[ident]['series'])
        for ident in ('live-better', 'live-longer', 'human-system', 'regular-investing'):
            self.assertTrue(books[ident]['riskNote'])
        with TestClient(app) as client:
            for ident in additions:
                response = client.get('/bookshelf/' + ident)
                self.assertEqual(response.status_code, 200)
                self.assertIn(books[ident]['title'], response.text)


if __name__ == '__main__':
    unittest.main()
