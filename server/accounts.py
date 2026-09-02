"""Account, points wallet, and usage ledger for the creator workbench.

The wallet is the billing source of truth.  Balances are cached for fast reads,
while every mutation is preserved in point_transactions.  AI routes reserve
points before execution and refund them automatically when a request fails.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request, Response


ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("CREATOR_ACCOUNTS_DB") or ROOT / "data" / "creator_accounts.db")
COOKIE_NAME = "creator_session"
SESSION_DAYS = 30
PBKDF2_ROUNDS = 260_000
DB_LOCK = threading.RLock()
OWNER_EMAIL = (os.getenv("CREATOR_OWNER_EMAIL") or "gelen5@163.com").strip().lower()
NEW_USER_TRIAL_POINTS = max(0, int(os.getenv("CREATOR_NEW_USER_TRIAL_POINTS", "30") or 30))

DEFAULT_PRICING = [
    ("POST", "/api/diagnose", "公众号诊断", 10, 0),
    ("POST", "/api/xiaohongshu/package", "小红书图文生成", 10, 0),
    ("POST", "/api/tie-tu/plan", "微信贴图策划", 10, 0),
    ("POST", "/api/creator-tools/image", "AI 图片生成", 30, 0),
    ("POST", "/api/hit-detector/analyze", "爆文检测", 5, 0),
    ("POST", "/api/hit-detector/rewrite", "文章改稿", 5, 0),
    ("POST", "/api/workbench/sessions", "公众号完整工作流", 30, 0),
    ("POST", "/api/workbench/chat", "公众号创作调整", 5, 0),
    ("POST", "/api/images/generations", "早安图片生成", 30, 0),
]


class ClosingConnection(sqlite3.Connection):
    """sqlite context manager that commits/rolls back and then closes."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(
        DB_PATH, timeout=20, isolation_level=None, factory=ClosingConnection
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 20000")
    return connection


def init_db() -> None:
    schema = """
    CREATE TABLE IF NOT EXISTS users (
      id TEXT PRIMARY KEY,
      email TEXT NOT NULL UNIQUE COLLATE NOCASE,
      display_name TEXT NOT NULL,
      password_hash TEXT NOT NULL,
      role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user','admin')),
      status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','disabled')),
      created_at TEXT NOT NULL,
      last_login_at TEXT
    );
    CREATE TABLE IF NOT EXISTS wallets (
      user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
      balance INTEGER NOT NULL DEFAULT 0 CHECK(balance >= 0),
      trial_balance INTEGER NOT NULL DEFAULT 0 CHECK(trial_balance >= 0),
      bonus_balance INTEGER NOT NULL DEFAULT 0 CHECK(bonus_balance >= 0),
      paid_balance INTEGER NOT NULL DEFAULT 0 CHECK(paid_balance >= 0),
      updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS sessions (
      token_hash TEXT PRIMARY KEY,
      user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      impersonator_id TEXT REFERENCES users(id),
      expires_at TEXT NOT NULL,
      created_at TEXT NOT NULL,
      last_seen_at TEXT NOT NULL,
      revoked_at TEXT
    );
    CREATE TABLE IF NOT EXISTS point_transactions (
      id TEXT PRIMARY KEY,
      user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      amount INTEGER NOT NULL,
      balance_before INTEGER NOT NULL,
      balance_after INTEGER NOT NULL,
      bucket TEXT NOT NULL,
      kind TEXT NOT NULL,
      source TEXT NOT NULL,
      feature TEXT,
      request_id TEXT,
      operator_id TEXT,
      note TEXT,
      allocation_json TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_point_transactions_user_time
      ON point_transactions(user_id, created_at DESC);
    CREATE TABLE IF NOT EXISTS usage_records (
      request_id TEXT PRIMARY KEY,
      user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      method TEXT NOT NULL,
      path TEXT NOT NULL,
      feature TEXT NOT NULL,
      points INTEGER NOT NULL,
      status TEXT NOT NULL,
      http_status INTEGER,
      duration_ms INTEGER,
      estimated_cost_micros INTEGER NOT NULL DEFAULT 0,
      allocation_json TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL,
      finished_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_usage_records_user_time
      ON usage_records(user_id, created_at DESC);
    CREATE TABLE IF NOT EXISTS pricing_rules (
      method TEXT NOT NULL,
      path TEXT NOT NULL,
      feature TEXT NOT NULL,
      points INTEGER NOT NULL CHECK(points >= 0),
      estimated_cost_micros INTEGER NOT NULL DEFAULT 0,
      active INTEGER NOT NULL DEFAULT 1,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(method, path)
    );
    CREATE TABLE IF NOT EXISTS admin_actions (
      id TEXT PRIMARY KEY,
      operator_id TEXT NOT NULL REFERENCES users(id),
      target_user_id TEXT REFERENCES users(id),
      action TEXT NOT NULL,
      detail_json TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS provider_settings (
      id INTEGER PRIMARY KEY CHECK(id = 1),
      text_api_key TEXT NOT NULL DEFAULT '', image_api_key TEXT NOT NULL DEFAULT '',
      text_base_url TEXT NOT NULL DEFAULT '', image_base_url TEXT NOT NULL DEFAULT '',
      text_model TEXT NOT NULL DEFAULT '', image_model TEXT NOT NULL DEFAULT '',
      updated_at TEXT NOT NULL, updated_by TEXT REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS workbench_sessions (
      id TEXT PRIMARY KEY,
      user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      payload_json TEXT NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_workbench_sessions_user_time
      ON workbench_sessions(user_id, updated_at DESC);
    CREATE TABLE IF NOT EXISTS workbench_jobs (
      id TEXT PRIMARY KEY,
      user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      idempotency_key TEXT NOT NULL,
      session_id TEXT NOT NULL,
      usage_id TEXT,
      status TEXT NOT NULL,
      error TEXT,
      created_at TEXT NOT NULL,
      started_at TEXT,
      finished_at TEXT,
      UNIQUE(user_id, idempotency_key)
    );
    CREATE INDEX IF NOT EXISTS idx_workbench_jobs_user_time
      ON workbench_jobs(user_id, created_at DESC);
    CREATE TABLE IF NOT EXISTS jobs (
      id TEXT PRIMARY KEY,
      user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      type TEXT NOT NULL,
      lane TEXT NOT NULL,
      idempotency_key TEXT NOT NULL,
      usage_id TEXT,
      status TEXT NOT NULL DEFAULT 'queued',
      payload_json TEXT NOT NULL,
      result_json TEXT,
      error TEXT,
      attempts INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL,
      started_at TEXT,
      finished_at TEXT,
      canceled_at TEXT,
      UNIQUE(user_id, idempotency_key)
    );
    CREATE INDEX IF NOT EXISTS idx_jobs_lane_status_time ON jobs(lane,status,created_at);
    CREATE INDEX IF NOT EXISTS idx_jobs_user_time ON jobs(user_id,created_at DESC);
    """
    with DB_LOCK, _connect() as connection:
        connection.executescript(schema)
        session_columns = {row[1] for row in connection.execute("PRAGMA table_info(sessions)")}
        if "impersonator_id" not in session_columns:
            connection.execute("ALTER TABLE sessions ADD COLUMN impersonator_id TEXT REFERENCES users(id)")
        now = utc_now()
        for method, path, feature, points, cost in DEFAULT_PRICING:
            connection.execute(
                """INSERT OR IGNORE INTO pricing_rules
                   (method,path,feature,points,estimated_cost_micros,active,updated_at)
                   VALUES (?,?,?,?,?,1,?)""",
                (method, path, feature, points, cost, now),
            )
        connection.execute("INSERT OR IGNORE INTO provider_settings(id,updated_at) VALUES (1,?)", (now,))
    _bootstrap_owner_from_env()
    _sync_owner_role()


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt_hex, expected_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds)
        )
        return hmac.compare_digest(actual, bytes.fromhex(expected_hex))
    except (ValueError, TypeError):
        return False


def _public_user(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "email": row["email"],
        "display_name": row["display_name"],
        "role": row["role"],
        "status": row["status"],
        "created_at": row["created_at"],
    }


def _validate_email(email: str) -> str:
    value = email.strip().lower()
    if len(value) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        raise HTTPException(status_code=422, detail="请输入有效邮箱")
    return value


def _validate_password(password: str) -> None:
    if len(password) < 8 or len(password) > 128:
        raise HTTPException(status_code=422, detail="密码长度需要为 8—128 位")


def create_user(email: str, password: str, display_name: str, *, role: str = "user") -> dict[str, Any]:
    email = _validate_email(email)
    _validate_password(password)
    role = "admin" if email == OWNER_EMAIL else "user"
    display_name = display_name.strip()[:40] or email.split("@", 1)[0]
    user_id = uuid.uuid4().hex
    now = utc_now()
    try:
        with DB_LOCK, _connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT INTO users(id,email,display_name,password_hash,role,status,created_at)
                   VALUES (?,?,?,?,?,'active',?)""",
                (user_id, email, display_name, _hash_password(password), role, now),
            )
            connection.execute(
                "INSERT INTO wallets(user_id,balance,trial_balance,bonus_balance,paid_balance,updated_at) VALUES (?,?,?,?,?,?)",
                (user_id, NEW_USER_TRIAL_POINTS, NEW_USER_TRIAL_POINTS, 0, 0, now),
            )
            if NEW_USER_TRIAL_POINTS:
                connection.execute(
                    """INSERT INTO point_transactions
                       (id,user_id,amount,balance_before,balance_after,bucket,kind,source,feature,note,created_at)
                       VALUES (?,?,?,?,?,'trial','recharge','system','新用户试用','注册赠送试用积分',?)""",
                    (uuid.uuid4().hex, user_id, NEW_USER_TRIAL_POINTS, 0, NEW_USER_TRIAL_POINTS, now),
                )
            connection.execute("COMMIT")
            row = connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="该邮箱已经注册") from exc
    return _public_user(row)


def _bootstrap_owner_from_env() -> None:
    email = OWNER_EMAIL
    password = os.getenv("CREATOR_ADMIN_PASSWORD", "")
    if not password:
        return
    with DB_LOCK, _connect() as connection:
        if connection.execute("SELECT 1 FROM users WHERE email=? LIMIT 1", (email,)).fetchone():
            return
    create_user(email, password, os.getenv("CREATOR_ADMIN_NAME", "管理员"), role="admin")


def _sync_owner_role() -> None:
    """Make the configured owner email the only possible administrator."""
    with DB_LOCK, _connect() as connection:
        connection.execute(
            "UPDATE users SET role=CASE WHEN lower(email)=? THEN 'admin' ELSE 'user' END",
            (OWNER_EMAIL,),
        )


def register(email: str, password: str, display_name: str) -> dict[str, Any]:
    return create_user(email, password, display_name)


def authenticate(email: str, password: str) -> dict[str, Any]:
    email = _validate_email(email)
    with DB_LOCK, _connect() as connection:
        row = connection.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if not row or not _verify_password(password, row["password_hash"]):
            raise HTTPException(status_code=401, detail="邮箱或密码错误")
        if row["status"] != "active":
            raise HTTPException(status_code=403, detail="账号已被停用")
        connection.execute("UPDATE users SET last_login_at=? WHERE id=?", (utc_now(), row["id"]))
        return _public_user(row)


def create_session(user_id: str, response: Response, *, impersonator_id: str | None = None) -> None:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now_dt = datetime.now(timezone.utc)
    expires = now_dt + timedelta(days=SESSION_DAYS)
    with DB_LOCK, _connect() as connection:
        connection.execute(
            "INSERT INTO sessions(token_hash,user_id,impersonator_id,expires_at,created_at,last_seen_at) VALUES (?,?,?,?,?,?)",
            (token_hash, user_id, impersonator_id, expires.isoformat(), now_dt.isoformat(), now_dt.isoformat()),
        )
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_DAYS * 86400,
        httponly=True,
        secure=os.getenv("CREATOR_COOKIE_SECURE") == "1",
        samesite="lax",
        path="/",
    )


def revoke_session(request: Request, response: Response) -> None:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with DB_LOCK, _connect() as connection:
            connection.execute("UPDATE sessions SET revoked_at=? WHERE token_hash=?", (utc_now(), token_hash))
    response.delete_cookie(COOKIE_NAME, path="/")


def user_from_request(request: Request) -> dict[str, Any] | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = utc_now()
    with DB_LOCK, _connect() as connection:
        row = connection.execute(
            """SELECT u.*,s.impersonator_id FROM sessions s JOIN users u ON u.id=s.user_id
               WHERE s.token_hash=? AND s.revoked_at IS NULL AND s.expires_at>? AND u.status='active'""",
            (token_hash, now),
        ).fetchone()
        if not row:
            return None
        connection.execute("UPDATE sessions SET last_seen_at=? WHERE token_hash=?", (now, token_hash))
        user = _public_user(row)
        if row["impersonator_id"]:
            actor = connection.execute("SELECT * FROM users WHERE id=?", (row["impersonator_id"],)).fetchone()
            if actor:
                user["impersonation"] = {"active": True, "actor": _public_user(actor)}
        return user


def require_user(request: Request) -> dict[str, Any]:
    user = getattr(request.state, "user", None) or user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    return user


def require_admin(request: Request) -> dict[str, Any]:
    user = require_user(request)
    if user["role"] != "admin" or user["email"].lower() != OWNER_EMAIL:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def provider_settings(*, include_secrets: bool = False) -> dict[str, Any]:
    with DB_LOCK, _connect() as connection:
        row = connection.execute("SELECT * FROM provider_settings WHERE id=1").fetchone()
    data = dict(row) if row else {}
    result = {
        "text_base_url": data.get("text_base_url", ""), "image_base_url": data.get("image_base_url", ""),
        "text_model": data.get("text_model", ""), "image_model": data.get("image_model", ""),
        "text_configured": bool(data.get("text_api_key") or os.getenv("WECHAT_TEXT_API_KEY")),
        "image_configured": bool(data.get("image_api_key") or os.getenv("WECHAT_IMAGE_API_KEY")),
        "updated_at": data.get("updated_at"),
    }
    if include_secrets:
        result.update(text_api_key=data.get("text_api_key", ""), image_api_key=data.get("image_api_key", ""))
    return result


def update_provider_settings(operator_id: str, values: dict[str, Any]) -> dict[str, Any]:
    current = provider_settings(include_secrets=True)
    updated = {field: str(values.get(field, "")).strip() for field in
               ("text_base_url", "image_base_url", "text_model", "image_model")}
    for key in ("text_api_key", "image_api_key"):
        updated[key] = str(values.get(key, "")).strip() or current.get(key, "")
    now = utc_now()
    with DB_LOCK, _connect() as connection:
        connection.execute(
            """UPDATE provider_settings SET text_api_key=?,image_api_key=?,text_base_url=?,image_base_url=?,
               text_model=?,image_model=?,updated_at=?,updated_by=? WHERE id=1""",
            (updated["text_api_key"], updated["image_api_key"], updated["text_base_url"],
             updated["image_base_url"], updated["text_model"], updated["image_model"], now, operator_id),
        )
        connection.execute(
            "INSERT INTO admin_actions(id,operator_id,action,detail_json,created_at) VALUES (?,?,?,?,?)",
            (uuid.uuid4().hex, operator_id, "update_provider_settings",
             json.dumps({"text_key_updated": bool(values.get("text_api_key")), "image_key_updated": bool(values.get("image_api_key"))}), now),
        )
    return provider_settings()


def wallet_summary(user_id: str) -> dict[str, Any]:
    with DB_LOCK, _connect() as connection:
        row = connection.execute("SELECT * FROM wallets WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="积分钱包不存在")
        return {
            "balance": row["balance"],
            "trial": row["trial_balance"],
            "bonus": row["bonus_balance"],
            "paid": row["paid_balance"],
            "updated_at": row["updated_at"],
        }


def list_transactions(user_id: str, limit: int = 50) -> list[dict[str, Any]]:
    with DB_LOCK, _connect() as connection:
        rows = connection.execute(
            """SELECT id,amount,balance_before,balance_after,bucket,kind,source,feature,note,created_at
               FROM point_transactions WHERE user_id=? ORDER BY created_at DESC LIMIT ?""",
            (user_id, max(1, min(limit, 200))),
        ).fetchall()
        return [dict(row) for row in rows]


def pricing_rule(method: str, path: str) -> dict[str, Any] | None:
    with DB_LOCK, _connect() as connection:
        row = connection.execute(
            "SELECT * FROM pricing_rules WHERE method=? AND path=? AND active=1",
            (method.upper(), path),
        ).fetchone()
        return dict(row) if row else None


def list_pricing() -> list[dict[str, Any]]:
    with DB_LOCK, _connect() as connection:
        return [dict(row) for row in connection.execute(
            "SELECT method,path,feature,points,active,updated_at FROM pricing_rules ORDER BY points,feature"
        ).fetchall()]


def reserve_points(user_id: str, rule: dict[str, Any], method: str, path: str) -> str:
    points = int(rule["points"])
    request_id = uuid.uuid4().hex
    now = utc_now()
    with DB_LOCK, _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        wallet = connection.execute("SELECT * FROM wallets WHERE user_id=?", (user_id,)).fetchone()
        if not wallet or wallet["balance"] < points:
            connection.execute("ROLLBACK")
            balance = wallet["balance"] if wallet else 0
            raise HTTPException(status_code=402, detail=f"积分不足：需要 {points} 积分，当前剩余 {balance} 积分")
        remaining = points
        allocation: dict[str, int] = {}
        updated = {
            "trial": wallet["trial_balance"],
            "bonus": wallet["bonus_balance"],
            "paid": wallet["paid_balance"],
        }
        for bucket in ("trial", "bonus", "paid"):
            used = min(updated[bucket], remaining)
            if used:
                updated[bucket] -= used
                allocation[bucket] = used
                remaining -= used
            if remaining == 0:
                break
        before = wallet["balance"]
        after = before - points
        connection.execute(
            """UPDATE wallets SET balance=?,trial_balance=?,bonus_balance=?,paid_balance=?,updated_at=?
               WHERE user_id=?""",
            (after, updated["trial"], updated["bonus"], updated["paid"], now, user_id),
        )
        allocation_json = json.dumps(allocation, ensure_ascii=False)
        connection.execute(
            """INSERT INTO point_transactions
               (id,user_id,amount,balance_before,balance_after,bucket,kind,source,feature,request_id,note,allocation_json,created_at)
               VALUES (?,?,?,?,?,'mixed','consume','usage',?,?,?, ?,?)""",
            (uuid.uuid4().hex, user_id, -points, before, after, rule["feature"], request_id,
             f"预扣 {rule['feature']}", allocation_json, now),
        )
        connection.execute(
            """INSERT INTO usage_records
               (request_id,user_id,method,path,feature,points,status,estimated_cost_micros,allocation_json,created_at)
               VALUES (?,?,?,?,?,?,'reserved',?,?,?)""",
            (request_id, user_id, method, path, rule["feature"], points,
             int(rule.get("estimated_cost_micros") or 0), allocation_json, now),
        )
        connection.execute("COMMIT")
    return request_id


def save_workbench_session(user_id: str, session: dict[str, Any]) -> None:
    now = utc_now()
    payload = json.dumps(session, ensure_ascii=False)
    with DB_LOCK, _connect() as connection:
        connection.execute(
            """INSERT INTO workbench_sessions(id,user_id,payload_json,created_at,updated_at)
               VALUES (?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET payload_json=excluded.payload_json,updated_at=excluded.updated_at
               WHERE workbench_sessions.user_id=excluded.user_id""",
            (session["id"], user_id, payload, session.get("created_at") or now, now),
        )


def load_workbench_session(session_id: str, user_id: str) -> dict[str, Any] | None:
    with DB_LOCK, _connect() as connection:
        row = connection.execute(
            "SELECT payload_json FROM workbench_sessions WHERE id=? AND user_id=?",
            (session_id, user_id),
        ).fetchone()
    return json.loads(row["payload_json"]) if row else None


def create_workbench_job(user_id: str, idempotency_key: str, session_id: str, usage_id: str) -> dict[str, Any]:
    now = utc_now()
    job_id = uuid.uuid4().hex
    with DB_LOCK, _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT * FROM workbench_jobs WHERE user_id=? AND idempotency_key=?",
            (user_id, idempotency_key),
        ).fetchone()
        if existing:
            connection.execute("COMMIT")
            return dict(existing)
        connection.execute(
            """INSERT INTO workbench_jobs
               (id,user_id,idempotency_key,session_id,usage_id,status,created_at)
               VALUES (?,?,?,?,?,'queued',?)""",
            (job_id, user_id, idempotency_key, session_id, usage_id, now),
        )
        connection.execute("COMMIT")
    return workbench_job(job_id, user_id) or {}


def workbench_job(job_id: str, user_id: str) -> dict[str, Any] | None:
    with DB_LOCK, _connect() as connection:
        row = connection.execute(
            "SELECT * FROM workbench_jobs WHERE id=? AND user_id=?", (job_id, user_id)
        ).fetchone()
    return dict(row) if row else None


def workbench_job_by_key(user_id: str, idempotency_key: str) -> dict[str, Any] | None:
    with DB_LOCK, _connect() as connection:
        row = connection.execute(
            "SELECT * FROM workbench_jobs WHERE user_id=? AND idempotency_key=?",
            (user_id, idempotency_key),
        ).fetchone()
    return dict(row) if row else None


def update_workbench_job(job_id: str, status: str, error: str | None = None) -> None:
    now = utc_now()
    started_at = now if status == "running" else None
    finished_at = now if status in {"completed", "failed"} else None
    with DB_LOCK, _connect() as connection:
        connection.execute(
            """UPDATE workbench_jobs SET status=?,error=?,
               started_at=COALESCE(started_at,?),finished_at=COALESCE(?,finished_at)
               WHERE id=?""",
            (status, error, started_at, finished_at, job_id),
        )


def recover_interrupted_workbench_jobs() -> int:
    with DB_LOCK, _connect() as connection:
        rows = connection.execute(
            "SELECT id,usage_id FROM workbench_jobs WHERE status IN ('queued','running')"
        ).fetchall()
    for row in rows:
        if row["usage_id"]:
            refund_usage(row["usage_id"], 503, 0)
        update_workbench_job(row["id"], "failed", "服务重启，任务已中止，积分已自动退还")
    return len(rows)


def create_job(user_id: str, task_type: str, lane: str, idempotency_key: str, usage_id: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    with DB_LOCK, _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute("SELECT * FROM jobs WHERE user_id=? AND idempotency_key=?", (user_id, idempotency_key)).fetchone()
        if existing:
            connection.execute("COMMIT")
            return dict(existing)
        job_id = uuid.uuid4().hex
        connection.execute(
            """INSERT INTO jobs(id,user_id,type,lane,idempotency_key,usage_id,status,payload_json,created_at)
               VALUES (?,?,?,?,?,?, 'queued', ?,?)""",
            (job_id, user_id, task_type, lane, idempotency_key, usage_id, json.dumps(payload, ensure_ascii=False), now),
        )
        connection.execute("COMMIT")
    return job(job_id, user_id) or {}


def job(job_id: str, user_id: str | None = None) -> dict[str, Any] | None:
    with DB_LOCK, _connect() as connection:
        query, params = ("SELECT * FROM jobs WHERE id=?", (job_id,)) if user_id is None else ("SELECT * FROM jobs WHERE id=? AND user_id=?", (job_id, user_id))
        row = connection.execute(query, params).fetchone()
    return dict(row) if row else None


def claim_job(lanes: list[str]) -> dict[str, Any] | None:
    if not lanes:
        return None
    marks = ",".join("?" for _ in lanes)
    with DB_LOCK, _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(f"SELECT * FROM jobs WHERE status='queued' AND lane IN ({marks}) ORDER BY created_at LIMIT 1", lanes).fetchone()
        if not row:
            connection.execute("COMMIT")
            return None
        now = utc_now()
        updated = connection.execute("UPDATE jobs SET status='running',started_at=?,attempts=attempts+1 WHERE id=? AND status='queued'", (now, row["id"])).rowcount
        connection.execute("COMMIT")
    return job(row["id"]) if updated else None


def finish_job(job_id: str, result: dict[str, Any]) -> None:
    with DB_LOCK, _connect() as connection:
        connection.execute("UPDATE jobs SET status='succeeded',result_json=?,finished_at=? WHERE id=? AND status='running'", (json.dumps(result, ensure_ascii=False), utc_now(), job_id))


def fail_job(job_id: str, error: str) -> None:
    with DB_LOCK, _connect() as connection:
        connection.execute("UPDATE jobs SET status='failed',error=?,finished_at=? WHERE id=? AND status IN ('queued','running')", (error[-1000:], utc_now(), job_id))


def cancel_job(job_id: str, user_id: str) -> dict[str, Any] | None:
    with DB_LOCK, _connect() as connection:
        connection.execute("UPDATE jobs SET status='canceled',canceled_at=?,finished_at=? WHERE id=? AND user_id=? AND status='queued'", (utc_now(), utc_now(), job_id, user_id))
    return job(job_id, user_id)


def list_jobs(limit: int = 100, user_id: str | None = None) -> list[dict[str, Any]]:
    with DB_LOCK, _connect() as connection:
        if user_id:
            rows = connection.execute("SELECT * FROM jobs WHERE user_id=? ORDER BY created_at DESC LIMIT ?", (user_id, max(1, min(limit, 200)))).fetchall()
        else:
            rows = connection.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 200)),)).fetchall()
    return [dict(row) for row in rows]


def active_job_count(user_id: str) -> int:
    with DB_LOCK, _connect() as connection:
        return int(connection.execute("SELECT COUNT(*) FROM jobs WHERE user_id=? AND status IN ('queued','running')", (user_id,)).fetchone()[0])


def recover_interrupted_jobs() -> int:
    """Refund only jobs that were actually running when the worker stopped.

    Queued jobs remain durable and will be picked up after the worker restarts.
    """
    with DB_LOCK, _connect() as connection:
        rows = connection.execute("SELECT id,usage_id FROM jobs WHERE status='running'").fetchall()
    for row in rows:
        if row["usage_id"]:
            refund_usage(row["usage_id"], 503, 0)
        fail_job(row["id"], "Worker 重启，任务已中止，积分已自动退还")
    return len(rows)


def settle_usage(request_id: str, http_status: int, duration_ms: int) -> None:
    with DB_LOCK, _connect() as connection:
        connection.execute(
            """UPDATE usage_records SET status='completed',http_status=?,duration_ms=?,finished_at=?
               WHERE request_id=? AND status='reserved'""",
            (http_status, duration_ms, utc_now(), request_id),
        )


def refund_usage(request_id: str, http_status: int, duration_ms: int) -> None:
    now = utc_now()
    with DB_LOCK, _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        usage = connection.execute(
            "SELECT * FROM usage_records WHERE request_id=? AND status='reserved'", (request_id,)
        ).fetchone()
        if not usage:
            connection.execute("ROLLBACK")
            return
        allocation = json.loads(usage["allocation_json"] or "{}")
        wallet = connection.execute("SELECT * FROM wallets WHERE user_id=?", (usage["user_id"],)).fetchone()
        before = wallet["balance"]
        points = int(usage["points"])
        after = before + points
        connection.execute(
            """UPDATE wallets SET balance=?,trial_balance=?,bonus_balance=?,paid_balance=?,updated_at=?
               WHERE user_id=?""",
            (after, wallet["trial_balance"] + int(allocation.get("trial", 0)),
             wallet["bonus_balance"] + int(allocation.get("bonus", 0)),
             wallet["paid_balance"] + int(allocation.get("paid", 0)), now, usage["user_id"]),
        )
        connection.execute(
            """INSERT INTO point_transactions
               (id,user_id,amount,balance_before,balance_after,bucket,kind,source,feature,request_id,note,allocation_json,created_at)
               VALUES (?,?,?,?,?,'mixed','refund','usage',?,?,?, ?,?)""",
            (uuid.uuid4().hex, usage["user_id"], points, before, after, usage["feature"], request_id,
             "请求失败，积分自动退还", usage["allocation_json"], now),
        )
        connection.execute(
            """UPDATE usage_records SET status='refunded',http_status=?,duration_ms=?,finished_at=?
               WHERE request_id=?""",
            (http_status, duration_ms, now, request_id),
        )
        connection.execute("COMMIT")


def recharge(operator_id: str, user_id: str, points: int, bucket: str, note: str) -> dict[str, Any]:
    if points <= 0 or points > 1_000_000:
        raise HTTPException(status_code=422, detail="单次充值积分需要在 1—1,000,000 之间")
    if bucket not in {"trial", "bonus", "paid"}:
        raise HTTPException(status_code=422, detail="积分类型无效")
    note = note.strip()
    if not note:
        raise HTTPException(status_code=422, detail="充值备注不能为空")
    now = utc_now()
    with DB_LOCK, _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        wallet = connection.execute("SELECT * FROM wallets WHERE user_id=?", (user_id,)).fetchone()
        if not wallet:
            connection.execute("ROLLBACK")
            raise HTTPException(status_code=404, detail="用户不存在")
        before = wallet["balance"]
        after = before + points
        column = f"{bucket}_balance"
        connection.execute(
            f"UPDATE wallets SET balance=?,{column}={column}+?,updated_at=? WHERE user_id=?",
            (after, points, now, user_id),
        )
        connection.execute(
            """INSERT INTO point_transactions
               (id,user_id,amount,balance_before,balance_after,bucket,kind,source,operator_id,note,allocation_json,created_at)
               VALUES (?,?,?,?,?,?,'recharge','admin',?,?,?,?)""",
            (uuid.uuid4().hex, user_id, points, before, after, bucket, operator_id, note,
             json.dumps({bucket: points}), now),
        )
        connection.execute(
            "INSERT INTO admin_actions(id,operator_id,target_user_id,action,detail_json,created_at) VALUES (?,?,?,?,?,?)",
            (uuid.uuid4().hex, operator_id, user_id, "recharge",
             json.dumps({"points": points, "bucket": bucket, "note": note}, ensure_ascii=False), now),
        )
        connection.execute("COMMIT")
    return wallet_summary(user_id)


def list_users(query: str = "", limit: int = 50) -> list[dict[str, Any]]:
    pattern = f"%{query.strip()}%"
    with DB_LOCK, _connect() as connection:
        rows = connection.execute(
            """SELECT u.id,u.email,u.display_name,u.role,u.status,u.created_at,u.last_login_at,w.balance,
                      w.trial_balance,w.bonus_balance,w.paid_balance,
                      (SELECT COUNT(*) FROM usage_records r WHERE r.user_id=u.id AND r.status='completed') completed_tasks
               FROM users u JOIN wallets w ON w.user_id=u.id
               WHERE u.email LIKE ? OR u.display_name LIKE ?
               ORDER BY u.created_at DESC LIMIT ?""",
            (pattern, pattern, max(1, min(limit, 200))),
        ).fetchall()
        return [dict(row) for row in rows]


def admin_overview() -> dict[str, Any]:
    with DB_LOCK, _connect() as connection:
        users = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        today = connection.execute("SELECT COUNT(*) FROM users WHERE julianday(created_at) >= julianday('now','start of day')").fetchone()[0]
        seven_days = connection.execute("SELECT COUNT(*) FROM users WHERE julianday(created_at) >= julianday('now','-7 days')").fetchone()[0]
        thirty_days = connection.execute("SELECT COUNT(*) FROM users WHERE julianday(created_at) >= julianday('now','-30 days')").fetchone()[0]
        active_30d = connection.execute("SELECT COUNT(*) FROM users WHERE julianday(last_login_at) >= julianday('now','-30 days')").fetchone()[0]
        total_balance = connection.execute("SELECT COALESCE(SUM(balance),0) FROM wallets").fetchone()[0]
        paid_points = connection.execute(
            "SELECT COALESCE(SUM(amount),0) FROM point_transactions WHERE kind='recharge' AND bucket='paid'"
        ).fetchone()[0]
        consumed = -connection.execute(
            "SELECT COALESCE(SUM(amount),0) FROM point_transactions WHERE kind='consume'"
        ).fetchone()[0]
        completed = connection.execute(
            "SELECT COUNT(*) FROM usage_records WHERE status='completed'"
        ).fetchone()[0]
        return {"users": users, "registered_today": today, "registered_7d": seven_days,
                "registered_30d": thirty_days, "active_30d": active_30d, "total_balance": total_balance,
                "paid_points_recharged": paid_points, "points_consumed": consumed, "completed_tasks": completed}


def admin_user_detail(user_id: str) -> dict[str, Any]:
    with DB_LOCK, _connect() as connection:
        user = connection.execute(
            """SELECT u.id,u.email,u.display_name,u.role,u.status,u.created_at,u.last_login_at,
                      w.balance,w.trial_balance,w.bonus_balance,w.paid_balance
               FROM users u JOIN wallets w ON w.user_id=u.id WHERE u.id=?""", (user_id,)
        ).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        usage = connection.execute(
            """SELECT COUNT(*) total,COALESCE(SUM(points),0) points,
                      COALESCE(SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END),0) completed
               FROM usage_records WHERE user_id=?""", (user_id,)
        ).fetchone()
        transactions = connection.execute(
            """SELECT amount,bucket,kind,feature,note,created_at FROM point_transactions
               WHERE user_id=? ORDER BY created_at DESC LIMIT 20""", (user_id,)
        ).fetchall()
        result = dict(user)
        result["usage"] = dict(usage)
        result["transactions"] = [dict(row) for row in transactions]
        return result


def start_impersonation(operator: dict[str, Any], target_user_id: str, request: Request, response: Response) -> dict[str, Any]:
    with DB_LOCK, _connect() as connection:
        target = connection.execute("SELECT * FROM users WHERE id=? AND status='active'", (target_user_id,)).fetchone()
        if not target:
            raise HTTPException(status_code=404, detail="用户不存在或已停用")
        if target["id"] == operator["id"] or target["role"] == "admin":
            raise HTTPException(status_code=422, detail="不能切换到管理员账号")
        connection.execute(
            "INSERT INTO admin_actions(id,operator_id,target_user_id,action,detail_json,created_at) VALUES (?,?,?,?,?,?)",
            (uuid.uuid4().hex, operator["id"], target_user_id, "start_impersonation", "{}", utc_now()),
        )
    revoke_session(request, response)
    create_session(target_user_id, response, impersonator_id=operator["id"])
    user = _public_user(target)
    user["impersonation"] = {"active": True, "actor": operator}
    return user


def stop_impersonation(request: Request, response: Response) -> dict[str, Any]:
    user = require_user(request)
    info = user.get("impersonation")
    if not info:
        raise HTTPException(status_code=409, detail="当前不在用户视角")
    actor = info["actor"]
    revoke_session(request, response)
    create_session(actor["id"], response)
    with DB_LOCK, _connect() as connection:
        connection.execute(
            "INSERT INTO admin_actions(id,operator_id,target_user_id,action,detail_json,created_at) VALUES (?,?,?,?,?,?)",
            (uuid.uuid4().hex, actor["id"], user["id"], "stop_impersonation", "{}", utc_now()),
        )
    return actor
