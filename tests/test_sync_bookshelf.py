"""Refresh all curated owners atomically without contacting GitHub in tests."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import sync_bookshelf

ROOT = Path(__file__).resolve().parents[1]


class SyncBookshelfTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'books.json'
        self.catalog = json.loads((ROOT / 'static/bookshelf-data.json').read_text(encoding='utf-8'))
        self.path.write_text(json.dumps(self.catalog, ensure_ascii=False), encoding='utf-8')

    def run_sync(self, fetch):
        with patch.object(sync_bookshelf, 'CATALOG', self.path), \
                patch.object(sync_bookshelf, 'urlopen', side_effect=fetch), \
                patch('sys.argv', ['sync_bookshelf', '--force']), patch('sys.stdout', new_callable=io.StringIO):
            sync_bookshelf.main()

    def test_all_curated_owners_refresh(self):
        urls = []
        def fetch(request, timeout):
            urls.append(request.full_url)
            return io.BytesIO(b'{"stargazers_count":123}')
        self.run_sync(fetch)
        self.assertEqual(len(self.catalog['books']), len(urls))
        self.assertIn('https://api.github.com/repos/Anduin2017/HowToCook', urls)
        self.assertTrue(all(book['stars'] == 123 for book in json.loads(self.path.read_text(encoding='utf-8'))['books']))

    def test_partial_failure_preserves_entire_original_snapshot(self):
        original = self.path.read_bytes()
        calls = 0
        def fetch(request, timeout):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise TimeoutError('simulated timeout')
            return io.BytesIO(b'{"stargazers_count":123}')
        with self.assertRaises(SystemExit):
            self.run_sync(fetch)
        self.assertEqual(original, self.path.read_bytes())

    def test_non_github_url_is_rejected_before_network(self):
        self.catalog['books'][0]['githubUrl'] = 'https://github.com.evil.test/owner/repo'
        self.path.write_text(json.dumps(self.catalog), encoding='utf-8')
        with self.assertRaises(SystemExit):
            self.run_sync(lambda *args, **kwargs: self.fail('must not fetch invalid host'))
