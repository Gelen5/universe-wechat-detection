from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from server.storage.local import LocalStorageProvider
from server.storage.s3 import S3StorageProvider


class FakeS3Client:
    def __init__(self):
        self.uploads = []
        self.deletes = []

    def put_object(self, **kwargs):
        self.uploads.append(kwargs)

    def delete_object(self, **kwargs):
        self.deletes.append(kwargs)

    def generate_presigned_url(self, operation, *, Params, ExpiresIn):
        return f"https://signed.example/{Params['Key']}?expires={ExpiresIn}"


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


class S3StorageTests(unittest.TestCase):
    def test_private_upload_url_and_delete(self):
        client = FakeS3Client()
        storage = S3StorageProvider(bucket="assets", client=client, prefix="prod")
        saved = storage.upload("user one/article.html", b"hello", content_type="text/html")
        self.assertEqual("user one/article.html", saved.key)
        self.assertEqual("/api/storage/user%20one/article.html", saved.url)
        self.assertEqual("prod/user one/article.html", client.uploads[0]["Key"])
        self.assertEqual("https://signed.example/prod/user one/article.html?expires=900",
                         storage.get_url(saved.key))
        self.assertIsNone(storage.local_path(saved.key))
        storage.delete(saved.key)
        self.assertEqual("prod/user one/article.html", client.deletes[0]["Key"])

    def test_public_url_is_encoded_and_traversal_rejected(self):
        storage = S3StorageProvider(
            bucket="assets", client=FakeS3Client(), prefix="prod", public_url="https://cdn.example",
        )
        self.assertEqual("https://cdn.example/prod/user%20one/a.png", storage.get_url("user one/a.png"))
        with self.assertRaises(ValueError):
            storage.get_url("../secret")


if __name__ == "__main__":
    unittest.main()
