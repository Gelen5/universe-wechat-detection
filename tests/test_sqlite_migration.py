import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import migrate_sqlite_to_postgres as migration


class SQLiteMigrationTests(unittest.TestCase):
    def test_migration_uses_disposable_copy_of_legacy_database(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, "creator_accounts.db")
            source.write_bytes(b"legacy-data")
            copied_path = None

            def fake_migrate(source_url, target_url, dry_run, batch_size):
                nonlocal copied_path
                copied_path = Path(source_url.removeprefix("sqlite:///"))
                self.assertNotEqual(copied_path, source)
                self.assertEqual(copied_path.read_bytes(), b"legacy-data")
                self.assertEqual(target_url, "postgresql://target")
                self.assertTrue(dry_run)
                self.assertEqual(batch_size, 25)
                return {"verified": True}

            with patch.object(migration, "migrate", side_effect=fake_migrate):
                report = migration.migrate_file(source, "postgresql://target", True, 25)

            self.assertEqual(report, {"verified": True})
            self.assertIsNotNone(copied_path)
            self.assertFalse(copied_path.exists())


if __name__ == "__main__":
    unittest.main()
