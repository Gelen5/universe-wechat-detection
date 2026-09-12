"""Copy the legacy SQLite dataset into an Alembic-migrated PostgreSQL database."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import MetaData, Table, create_engine, func, inspect, select
from sqlalchemy.dialects.postgresql import insert


REQUIRED_TABLES = (
    "users", "wallets", "sessions", "point_transactions", "usage_records",
    "pricing_rules", "admin_actions", "provider_settings", "workbench_sessions",
    "workbench_jobs", "jobs",
)
OPTIONAL_TABLES = ("conversation_locks",)


def counts(engine, names):
    metadata = MetaData()
    metadata.reflect(bind=engine, only=list(names))
    with engine.connect() as connection:
        return {name: connection.scalar(select(func.count()).select_from(metadata.tables[name])) for name in names}


def wallet_totals(engine):
    metadata = MetaData()
    wallets = Table("wallets", metadata, autoload_with=engine)
    with engine.connect() as connection:
        row = connection.execute(select(
            func.coalesce(func.sum(wallets.c.balance), 0),
            func.coalesce(func.sum(wallets.c.trial_balance), 0),
            func.coalesce(func.sum(wallets.c.bonus_balance), 0),
            func.coalesce(func.sum(wallets.c.paid_balance), 0),
        )).one()
    return list(row)


def migrate(source_url: str, target_url: str, dry_run: bool, batch_size: int):
    source = create_engine(source_url)
    target = create_engine(target_url, pool_pre_ping=True)
    inspector = inspect(source)
    names = REQUIRED_TABLES + tuple(name for name in OPTIONAL_TABLES if inspector.has_table(name))
    source_counts = counts(source, names)
    report = {"dry_run": dry_run, "source_counts": source_counts,
              "source_wallet_totals": wallet_totals(source)}
    if dry_run:
        return report

    source_meta, target_meta = MetaData(), MetaData()
    source_meta.reflect(bind=source, only=list(names))
    target_meta.reflect(bind=target, only=list(names))
    with source.connect() as src, target.begin() as dst:
        for name in names:
            source_table, target_table = source_meta.tables[name], target_meta.tables[name]
            offset = 0
            while True:
                rows = [dict(row._mapping) for row in src.execute(select(source_table).offset(offset).limit(batch_size))]
                if not rows:
                    break
                dst.execute(insert(target_table).values(rows).on_conflict_do_nothing())
                offset += len(rows)
    target_counts = counts(target, names)
    report.update(target_counts=target_counts, target_wallet_totals=wallet_totals(target))
    report["verified"] = source_counts == target_counts and report["source_wallet_totals"] == report["target_wallet_totals"]
    if not report["verified"]:
        raise RuntimeError("migration verification failed; source and target totals differ")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, help="SQLite file path")
    parser.add_argument("--target", required=True, help="PostgreSQL SQLAlchemy URL")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()
    source = Path(args.source).resolve()
    if not source.is_file():
        raise SystemExit(f"SQLite source not found: {source}")
    report = migrate(f"sqlite:///{source.as_posix()}", args.target, args.dry_run, max(1, args.batch_size))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
