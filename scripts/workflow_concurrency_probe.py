"""Run 10/30/50-user PostgreSQL workflow admission probes without provider calls."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import uuid

from sqlalchemy import create_engine, text


def probe(database_url: str, concurrency: int) -> dict:
    engine = create_engine(database_url, pool_size=min(concurrency, 20), max_overflow=concurrency)

    def create(index: int):
        user_id = f"probe-{uuid.uuid4().hex}"
        with engine.begin() as db:
            db.execute(text("INSERT INTO users(id,email,display_name,password_hash,role,status,created_at) VALUES (:id,:email,'Probe','x','user','active','probe')"),
                       {"id": user_id, "email": f"{user_id}@example.invalid"})
            db.execute(text("INSERT INTO wallets(user_id,balance,trial_balance,bonus_balance,paid_balance,updated_at) VALUES (:id,30,30,0,0,'probe')"), {"id": user_id})
        from server.workflow_billing import create_billed_workflow
        workflow, replay = create_billed_workflow(user_id, f"probe-{index}", "interactive", {"topic": "probe"})
        return workflow["id"], replay

    started = __import__("time").perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = list(pool.map(create, range(concurrency)))
    elapsed = __import__("time").perf_counter() - started
    return {"concurrency": concurrency, "created": len(results), "replays": sum(int(item[1]) for item in results), "seconds": round(elapsed, 3)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args()
    print(json.dumps([probe(args.database_url, size) for size in (10, 30, 50)], indent=2))


if __name__ == "__main__":
    main()
