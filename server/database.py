"""Shared SQLAlchemy engine and transaction helpers.

SQLite remains available for local tests and migration dry-runs. Production
must set DATABASE_URL to PostgreSQL; Redis is never a persistence fallback.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
import re
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker


ROOT = Path(__file__).resolve().parent.parent


def database_url() -> str:
    configured = os.getenv("DATABASE_URL", "").strip()
    if configured:
        if configured.startswith("postgres://"):
            return "postgresql+psycopg://" + configured[len("postgres://"):]
        if configured.startswith("postgresql://"):
            return "postgresql+psycopg://" + configured[len("postgresql://"):]
        return configured
    path = Path(os.getenv("CREATOR_ACCOUNTS_DB") or ROOT / "data" / "creator_accounts.db")
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path.as_posix()}"


def build_engine(url: str | None = None) -> Engine:
    value = url or database_url()
    options: dict = {"pool_pre_ping": True}
    if value.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False, "timeout": 20}
    else:
        options.update(
            pool_size=max(2, int(os.getenv("DB_POOL_SIZE", "10"))),
            max_overflow=max(0, int(os.getenv("DB_MAX_OVERFLOW", "20"))),
            pool_recycle=max(60, int(os.getenv("DB_POOL_RECYCLE_SECONDS", "1800"))),
        )
    return create_engine(value, **options)


ENGINE = build_engine()
SessionLocal = sessionmaker(bind=ENGINE, class_=Session, expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def database_ready() -> bool:
    try:
        with ENGINE.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def require_postgres_in_production() -> None:
    environment = os.getenv("APP_ENV", "development").lower()
    if environment in {"production", "prod"} and ENGINE.dialect.name != "postgresql":
        raise RuntimeError("Production requires DATABASE_URL pointing to PostgreSQL")


def ensure_local_workflow_schema() -> None:
    """Add only new workflow tables to a legacy local SQLite database."""
    if ENGINE.dialect.name == "sqlite":
        from .models import Base
        Base.metadata.create_all(ENGINE, checkfirst=True)


class CompatRow(Mapping[str, Any]):
    """Expose SQLAlchemy rows with the sqlite3.Row interface used by legacy services."""

    def __init__(self, row: Any):
        self._values = tuple(row)
        self._mapping = dict(row._mapping)

    def __getitem__(self, key: str | int) -> Any:
        return self._values[key] if isinstance(key, int) else self._mapping[key]

    def __iter__(self):
        return iter(self._mapping)

    def __len__(self) -> int:
        return len(self._mapping)


class CompatResult:
    def __init__(self, result: Any):
        self._result = result
        self.rowcount = result.rowcount

    def fetchone(self) -> CompatRow | None:
        row = self._result.fetchone()
        return CompatRow(row) if row is not None else None

    def fetchall(self) -> list[CompatRow]:
        return [CompatRow(row) for row in self._result.fetchall()]

    def __iter__(self):
        for row in self._result:
            yield CompatRow(row)


def _bind_qmarks(statement: str, params: Sequence[Any]) -> tuple[str, dict[str, Any]]:
    values = list(params)
    index = 0

    def replace(_match):
        nonlocal index
        if index >= len(values):
            raise ValueError("SQL parameter count does not match placeholders")
        name = f"p{index}"
        index += 1
        return f":{name}"

    bound = re.sub(r"\?", replace, statement)
    if index != len(values):
        raise ValueError("SQL parameter count does not match placeholders")
    return bound, {f"p{i}": value for i, value in enumerate(values)}


class CompatConnection:
    """Small DB-API compatibility adapter used during the incremental cutover."""

    def __init__(self):
        self._connection = ENGINE.connect()
        self._closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
        finally:
            self.close()
        return False

    def execute(self, statement: str, params: Sequence[Any] = ()) -> CompatResult:
        command = statement.strip().upper()
        if command == "BEGIN IMMEDIATE":
            if not self._connection.in_transaction():
                self._connection.begin()
            return CompatResult(self._connection.execute(text("SELECT 1 WHERE false")))
        if command == "COMMIT":
            self.commit()
            return CompatResult(self._connection.execute(text("SELECT 1 WHERE false")))
        if command == "ROLLBACK":
            self.rollback()
            return CompatResult(self._connection.execute(text("SELECT 1 WHERE false")))
        sql = re.sub(r"^\s*INSERT\s+OR\s+IGNORE\s+INTO", "INSERT INTO", statement, flags=re.I)
        if re.match(r"^\s*INSERT\s+OR\s+IGNORE", statement, flags=re.I):
            sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
        sql, bindings = _bind_qmarks(sql, params)
        return CompatResult(self._connection.execute(text(sql), bindings))

    def commit(self) -> None:
        if self._connection.in_transaction():
            self._connection.commit()

    def rollback(self) -> None:
        if self._connection.in_transaction():
            self._connection.rollback()

    def close(self) -> None:
        if not self._closed:
            self._connection.close()
            self._closed = True


def compat_connect() -> CompatConnection:
    return CompatConnection()
