"""PostgreSQL admission, idempotency, and refund concurrency probes."""
from __future__ import annotations

import argparse, concurrent.futures, json, os, sys, time, uuid
from pathlib import Path
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def add_user(engine, uid, balance=30):
    with engine.begin() as db:
        db.execute(text("INSERT INTO users(id,email,display_name,password_hash,role,status,created_at) VALUES (:id,:email,'Probe','x','user','active','probe')"), {"id": uid, "email": f"{uid}@example.invalid"})
        db.execute(text("INSERT INTO wallets(user_id,balance,trial_balance,bonus_balance,paid_balance,updated_at) VALUES (:id,:b,:b,0,0,'probe')"), {"id": uid, "b": balance})

def cleanup(engine, prefix):
    with engine.begin() as db:
        db.execute(text("DELETE FROM users WHERE id LIKE :p"), {"p": f"{prefix}%"})

def ten_click_probe(engine):
    prefix = f"probe-click-{uuid.uuid4().hex}"
    add_user(engine, prefix, 300)
    from server.workflow_billing import create_billed_workflow
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            rows = list(pool.map(lambda _: create_billed_workflow(prefix, "same-action", "interactive", {"topic": "probe"}), range(10)))
        with engine.connect() as db:
            balance = db.execute(text("SELECT balance FROM wallets WHERE user_id=:id"), {"id": prefix}).scalar_one()
            usage = db.execute(text("SELECT COUNT(*) FROM usage_records WHERE user_id=:id"), {"id": prefix}).scalar_one()
        unique = len({row[0]["id"] for row in rows})
        return {"clicks": 10, "unique_workflows": unique, "replays": sum(int(r[1]) for r in rows), "usage_rows": int(usage), "balance": int(balance), "passed": unique == 1 and int(usage) == 1 and int(balance) == 270}
    finally:
        cleanup(engine, prefix)

def refund_probe(engine):
    prefix = f"probe-refund-{uuid.uuid4().hex}"
    add_user(engine, prefix)
    from server import accounts
    from server.workflow_billing import create_billed_workflow
    try:
        workflow, _ = create_billed_workflow(prefix, "refund-action", "interactive", {"topic": "probe"})
        usage_id = workflow["usage_id"]
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            list(pool.map(lambda _: accounts.refund_usage(usage_id, 500, 0), range(10)))
        with engine.connect() as db:
            balance = db.execute(text("SELECT balance FROM wallets WHERE user_id=:id"), {"id": prefix}).scalar_one()
            refunds = db.execute(text("SELECT COUNT(*) FROM point_transactions WHERE user_id=:id AND kind='refund'"), {"id": prefix}).scalar_one()
            status = db.execute(text("SELECT status FROM usage_records WHERE request_id=:id"), {"id": usage_id}).scalar_one()
        return {"refund_calls": 10, "refund_transactions": int(refunds), "balance": int(balance), "usage_status": status, "passed": int(refunds) == 1 and int(balance) == 30 and status == "refunded"}
    finally:
        cleanup(engine, prefix)

def load_probe(engine, registered=100, active=30):
    prefix = f"probe-load-{uuid.uuid4().hex}-"
    users = [f"{prefix}{i}" for i in range(registered)]
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=30) as pool:
            list(pool.map(lambda uid: add_user(engine, uid), users))
        from server.workflow_billing import create_billed_workflow
        started = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=active) as pool:
            rows = list(pool.map(lambda i: create_billed_workflow(users[i], f"active-{i}", "interactive", {"topic": "probe"}), range(active)))
        return {"registered": registered, "active_creators": active, "created": len(rows), "replays": sum(int(r[1]) for r in rows), "seconds": round(time.perf_counter() - started, 3), "passed": len(rows) == active}
    finally:
        cleanup(engine, prefix)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args()
    os.environ["DATABASE_URL"] = args.database_url
    engine = create_engine(args.database_url, pool_size=30, max_overflow=40, pool_pre_ping=True)
    try:
        result = {"ten_clicks": ten_click_probe(engine), "refund": refund_probe(engine), "load": load_probe(engine)}
        result["passed"] = all(v["passed"] for v in result.values())
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        engine.dispose()

if __name__ == "__main__":
    main()
