"""Run 10/30/50-user PostgreSQL workflow admission probes without provider calls."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import sys
import uuid
from pathlib import Path

from sqlalchemy import create_engine, text


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def probe(database_url: str, concurrency: int) -> dict:
    engine = create_engine(database_url, pool_size=min(concurrency, 20), max_overflow=concurrency)
    batch_id = uuid.uuid4().hex
    user_ids = [f"probe-{batch_id}-{index}" for index in range(concurrency)]

    def create(index: int):
        user_id = user_ids[index]
        with engine.begin() as db:
            db.execute(text("INSERT INTO users(id,email,display_name,password_hash,role,status,created_at) VALUES (:id,:email,'Probe','x','user','active','probe')"),
                       {"id": user_id, "email": f"{user_id}@example.invalid"})
            db.execute(text("INSERT INTO wallets(user_id,balance,trial_balance,bonus_balance,paid_balance,updated_at) VALUES (:id,30,30,0,0,'probe')"), {"id": user_id})
        from server.workflow_billing import create_billed_workflow
        workflow, replay = create_billed_workflow(user_id, f"probe-{index}", "interactive", {"topic": "probe"})
        return workflow["id"], replay

    started = __import__("time").perf_counter()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
            results = list(pool.map(create, range(concurrency)))
        elapsed = __import__("time").perf_counter() - started
        result = {
            "concurrency": concurrency,
            "created": len(results),
            "replays": sum(int(item[1]) for item in results),
            "seconds": round(elapsed, 3),
        }
    finally:
        with engine.begin() as db:
            db.execute(text("DELETE FROM users WHERE id LIKE :prefix"), {"prefix": f"probe-{batch_id}-%"})

    with engine.connect() as db:
        remaining = db.execute(
            text("SELECT COUNT(*) FROM users WHERE id LIKE :prefix"),
            {"prefix": f"probe-{batch_id}-%"},
        ).scalar_one()
    result["remaining_probe_users"] = int(remaining)
    engine.dispose()
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args()
    os.environ["DATABASE_URL"] = args.database_url
    print(json.dumps([probe(args.database_url, size) for size in (10, 30, 50)], indent=2))


if __name__ == "__main__":
    main()
