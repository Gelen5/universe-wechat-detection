"""Private Better Auth RPC bridge. No provider secrets or identity tokens reach JS."""
from __future__ import annotations

import os
import secrets
from typing import Any

import requests
from fastapi import HTTPException, Request, Response


def enabled() -> bool:
    return os.getenv('AUTH_ENGINE', 'legacy') == 'better-auth'


def call(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    secret = os.getenv('AUTH_BRIDGE_SECRET', '')
    if len(secret) < 32:
        raise HTTPException(503, '认证服务尚未配置')
    try:
        with requests.Session() as session:
            session.trust_env = False  # Internal credentials must not traverse a proxy.
            response = session.post(os.getenv('BETTER_AUTH_INTERNAL_URL', 'http://auth:3001').rstrip('/') + '/' + action,
                                    headers={'X-Auth-Bridge-Secret': secret}, json=payload, timeout=(3, 25))
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise HTTPException(503, '认证服务暂不可用，请稍后重试') from exc
    if not response.ok:
        raise HTTPException(response.status_code if 400 <= response.status_code < 500 else 503,
                            data.get('detail') or '认证未完成，请重试')
    return data


def copy_cookies(response: Response, result: dict[str, Any]) -> None:
    for cookie in result.get('cookies', []):
        if '\r' in cookie or '\n' in cookie:
            raise HTTPException(503, '认证服务响应异常')
        response.headers.append('set-cookie', cookie)


def validate_origin(request: Request) -> None:
    from urllib.parse import urlsplit
    origin = request.headers.get('origin')
    expected = os.getenv('BETTER_AUTH_URL', '').rstrip('/')
    if origin and (urlsplit(origin).scheme, urlsplit(origin).netloc) != (urlsplit(expected).scheme, urlsplit(expected).netloc):
        raise HTTPException(403, '请求来源不受信任')


def business_user(identity: dict[str, Any], *, rollback_password: str | None = None) -> dict[str, Any]:
    from . import accounts
    user_id, email = identity.get('id'), str(identity.get('email') or '').lower()
    if not isinstance(user_id, str) or len(user_id) > 64 or not user_id or not email:
        raise HTTPException(503, '认证身份不完整')
    with accounts.DB_LOCK, accounts._connect() as connection:
        row = connection.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
    if row:
        if row['email'].lower() != email:
            raise HTTPException(403, '账号身份不匹配')
        if row['status'] != 'active':
            raise HTTPException(403, '账号已被停用')
        return accounts._public_user(row)
    if identity.get('emailVerified') is not True:
        raise HTTPException(403, '请先验证邮箱')
    try:
        # Keep a PBKDF2 rollback credential while Better Auth owns live sign-in.
        # This does not create or accept a legacy session on the new login path.
        return accounts.create_user(email, rollback_password or secrets.token_urlsafe(48), str(identity.get('name') or ''), user_id=user_id)
    except HTTPException as exc:
        if exc.status_code != 409:
            raise
        # Concurrent requests may provision the same confirmed identity once.
        with accounts.DB_LOCK, accounts._connect() as connection:
            row = connection.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
        if row and row['email'].lower() == email and row['status'] == 'active':
            return accounts._public_user(row)
        raise HTTPException(409, '该邮箱已有账号，需要人工核对身份迁移') from exc


def from_request(request: Request) -> dict[str, Any] | None:
    if not any('better-auth' in name for name in request.cookies):
        return None
    identity = call('session', {'cookie': request.headers.get('cookie', '')}).get('user')
    return business_user(identity) if identity else None
