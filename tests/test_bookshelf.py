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
        self.assertEqual(len(data['books']), 11)
        self.assertEqual(len({b['id'] for b in data['books']}), 11)
        for book in data['books']:
            self.assertEqual(book['readingMode'], 'official')
            self.assertEqual(urlparse(book['githubUrl']).netloc, 'github.com')
            self.assertTrue(book['githubUrl'].startswith('https://github.com/alchaincyf/'))
            self.assertEqual(urlparse(book['readUrl']).scheme, 'https')
            self.assertIs(type(book['stars']), int)
            self.assertTrue(book['starsUpdatedAt'])
            self.assertIn('花叔', book['author'])
            self.assertTrue(book['license']['url'])
            self.assertNotIn('chapters', book)
            self.assertNotIn('content', book)


if __name__ == '__main__':
    unittest.main()
