from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from server.storage.local import LocalStorageProvider


class LocalStorageTests(unittest.TestCase):
    def test_upload_read_url_and_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = LocalStorageProvider(Path(directory))
            saved = storage.upload("user/conversation/file.txt", b"hello", content_type="text/plain")
            self.assertEqual(5, saved.size)
            self.assertEqual("/api/storage/user/conversation/file.txt", saved.url)
            self.assertEqual(b"hello", storage.local_path(saved.key).read_bytes())
            storage.delete(saved.key)
            with self.assertRaises(FileNotFoundError):
                storage.local_path(saved.key)

    def test_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = LocalStorageProvider(Path(directory))
            for key in ("../secret", "/absolute", "safe/../../secret"):
                with self.assertRaises(ValueError, msg=key):
                    storage.upload(key, b"no", content_type="application/octet-stream")


if __name__ == "__main__":
    unittest.main()
