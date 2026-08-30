import os
import tempfile
from pathlib import Path


TEST_DB = Path(tempfile.gettempdir()) / f"universe-workbench-tests-{os.getpid()}.db"
for suffix in ("", "-shm", "-wal"):
    path = Path(str(TEST_DB) + suffix)
    if path.exists():
        path.unlink()
os.environ["CREATOR_ACCOUNTS_DB"] = str(TEST_DB)
os.environ["CREATOR_OWNER_EMAIL"] = "admin@example.com"
os.environ["CREATOR_ADMIN_PASSWORD"] = "testing-pass-123"
os.environ["CREATOR_ADMIN_NAME"] = "测试管理员"
