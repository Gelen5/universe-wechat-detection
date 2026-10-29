"""One-time registration codes, stored briefly in Redis and delivered by SMTP."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import smtplib
import ssl
from email.message import EmailMessage

from fastapi import HTTPException
from redis import Redis


def required() -> bool:
    return os.getenv("EMAIL_VERIFICATION_REQUIRED", "0") == "1"


def _redis() -> Redis:
    try:
        client = Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"),
                                socket_connect_timeout=2, socket_timeout=2)
        client.ping()
        return client
    except Exception as exc:
        raise HTTPException(503, "验证码服务暂不可用") from exc


def _key(email: str) -> str:
    return "registration-code:" + hashlib.sha256(email.strip().lower().encode()).hexdigest()


def send_code(email: str) -> None:
    host = os.getenv("SMTP_HOST", "")
    sender = os.getenv("SMTP_FROM", "")
    username = os.getenv("SMTP_USERNAME", "")
    password = os.getenv("SMTP_PASSWORD", "")
    if not all((host, sender, username, password)):
        raise HTTPException(503, "邮件服务尚未配置")
    client = _redis()
    key = _key(email)
    if client.ttl(key + ":cooldown") > 0:
        raise HTTPException(429, "请稍后再获取验证码")
    code = f"{secrets.randbelow(1_000_000):06d}"
    salt = secrets.token_hex(16)
    digest = hashlib.sha256((salt + code).encode()).hexdigest()
    message = EmailMessage()
    message["Subject"] = "宇宙第一工作台注册验证码"
    message["From"] = sender
    message["To"] = email
    message.set_content(f"你的注册验证码是 {code}，10 分钟内有效。如果不是你本人操作，请忽略这封邮件。")
    try:
        port = int(os.getenv("SMTP_PORT", "465"))
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=10, context=ssl.create_default_context()) as smtp:
                smtp.login(username, password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=10) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                smtp.login(username, password)
                smtp.send_message(message)
    except Exception as exc:
        raise HTTPException(503, "验证码邮件发送失败，请稍后重试") from exc
    pipe = client.pipeline()
    pipe.setex(key, 600, salt + ":" + digest)
    pipe.setex(key + ":cooldown", 60, "1")
    pipe.delete(key + ":attempts")
    pipe.execute()


def verify_code(email: str, code: str) -> None:
    client = _redis()
    key = _key(email)
    attempts = client.incr(key + ":attempts")
    client.expire(key + ":attempts", 600, nx=True)
    if attempts > 5:
        client.delete(key)
        raise HTTPException(429, "验证码尝试次数过多，请重新获取")
    stored = client.get(key)
    if not stored:
        raise HTTPException(403, "验证码已失效，请重新获取")
    salt, digest = stored.decode().split(":", 1)
    candidate = hashlib.sha256((salt + code.strip()).encode()).hexdigest()
    if not hmac.compare_digest(candidate, digest):
        raise HTTPException(403, "验证码错误")
    client.delete(key, key + ":attempts")
