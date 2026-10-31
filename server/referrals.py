"""拉新活动：邀请码、双向奖励与防刷。

三条设计约束，改动前先读：

1. **积分账本只有一份。** 这里发的每一分都走 ``accounts.credit_bucket``，
   不自己拼 ``point_transactions``，否则退款/对账会漏掉这些行。
2. **奖励只进 bonus 桶。** 试用桶会被新用户首单判定消耗，付费桶对应真金白银；
   邀请奖励既不属于试用也不属于充值，只能是 bonus。也不发现金、不可提现。
3. **奖励不发在注册上，发在「跑完一次扣分任务」上。** 注册无邮箱验证，
   只认注册就等于按小号数发钱。激活信号复用 ``accounts.settle_usage``，
   也就是所有收费路径唯一的完成落点。
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException

from . import accounts

logger = logging.getLogger(__name__)

# 数值即活动规则，改这里就等于改活动。对外文案在 static 侧同步说明。
INVITE_SIGNUP_BONUS = 10      # 被邀请人注册即得
INVITE_ACTIVATE_INVITER = 15  # 邀请人：被邀请人跑完首个扣分任务
INVITE_ACTIVATE_INVITEE = 10  # 被邀请人：同上
INVITE_DAILY_CAP = 5          # 单个邀请人每天最多绑定几个新号
INVITE_MONTHLY_CAP = 20       # 单个邀请人每 30 天最多绑定几个新号
INVITE_IP_SAME_INVITER_CAP = 3  # 同一 IP 24 小时内最多为同一邀请人计几次

CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"  # 去掉 0/O/1/I/L 等易混字符
CODE_LENGTH = 6


def _enabled() -> bool:
    return os.getenv("INVITE_PROGRAM_ENABLED", "1") != "0"


def _normalize(code: str | None) -> str:
    return "".join(ch for ch in str(code or "").strip().upper() if ch.isalnum())[:32]


def _now() -> datetime:
    return datetime.now(timezone.utc)


# 「每天」按北京时间算：活动是国内运营的，用 UTC 零点会把每天的名额切在早上 8 点。
PRODUCT_TZ = timezone(timedelta(hours=8))


def _today_start() -> str:
    local = _now().astimezone(PRODUCT_TZ)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(timezone.utc).isoformat()


def _month_start() -> str:
    return (_now() - timedelta(days=30)).isoformat()


def ensure_code(user_id: str) -> str:
    """返回用户邀请码，没有就生成一个。写锁内「查重 + 落库」一次做完。"""
    with accounts.DB_LOCK, accounts._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT invite_code FROM users WHERE id=?", (user_id,)
        ).fetchone()
        if not row:
            connection.execute("ROLLBACK")
            raise HTTPException(status_code=404, detail="用户不存在")
        if row["invite_code"]:
            connection.execute("COMMIT")
            return row["invite_code"]
        for _ in range(8):
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
            if connection.execute(
                "SELECT 1 FROM users WHERE invite_code=? LIMIT 1", (code,)
            ).fetchone():
                continue
            connection.execute(
                "UPDATE users SET invite_code=? WHERE id=?", (code, user_id)
            )
            connection.execute("COMMIT")
            return code
        connection.execute("ROLLBACK")
    raise HTTPException(status_code=503, detail="邀请码生成失败，请重试")


def _inviter_for_code(connection, code: str):
    return connection.execute(
        "SELECT id,email,display_name,status FROM users WHERE invite_code=?", (code,)
    ).fetchone()


def bind_signup(invitee_id: str, code: str | None, ip: str | None) -> dict[str, Any]:
    """注册时绑定邀请关系。任何失败都只返回原因，绝不影响注册本身。"""
    if not _normalize(code):
        return {"status": "none"}
    try:
        return _bind_signup(invitee_id, code, ip)
    except Exception:
        logger.exception("referral.bind_failed invitee=%s", invitee_id)
        return {"status": "ignored", "reason": "internal_error"}


def _bind_signup(invitee_id: str, code: str | None, ip: str | None) -> dict[str, Any]:
    code = _normalize(code)
    if not _enabled():
        return {"status": "ignored", "reason": "program_disabled"}

    credited = False
    inviter_name = ""
    with accounts.DB_LOCK, accounts._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        inviter = _inviter_for_code(connection, code)
        if not inviter:
            connection.execute("ROLLBACK")
            return {"status": "ignored", "reason": "code_not_found"}
        inviter_name = inviter["display_name"]
        if inviter["id"] == invitee_id:
            connection.execute("ROLLBACK")
            return {"status": "ignored", "reason": "self_referral"}
        if inviter["status"] != "active":
            connection.execute("ROLLBACK")
            return {"status": "ignored", "reason": "inviter_inactive"}
        if connection.execute(
            "SELECT 1 FROM referrals WHERE invitee_id=?", (invitee_id,)
        ).fetchone():
            connection.execute("ROLLBACK")
            return {"status": "ignored", "reason": "already_referred"}
        daily = connection.execute(
            "SELECT COUNT(*) FROM referrals WHERE inviter_id=? AND created_at>=?",
            (inviter["id"], _today_start()),
        ).fetchone()[0]
        if daily >= INVITE_DAILY_CAP:
            connection.execute("ROLLBACK")
            return {"status": "ignored", "reason": "daily_cap"}
        monthly = connection.execute(
            "SELECT COUNT(*) FROM referrals WHERE inviter_id=? AND created_at>=?",
            (inviter["id"], _month_start()),
        ).fetchone()[0]
        if monthly >= INVITE_MONTHLY_CAP:
            connection.execute("ROLLBACK")
            return {"status": "ignored", "reason": "monthly_cap"}
        if ip and connection.execute(
            """SELECT COUNT(*) FROM referrals WHERE inviter_id=? AND signup_ip=?
               AND created_at>=?""",
            (inviter["id"], ip, (_now() - timedelta(days=1)).isoformat()),
        ).fetchone()[0] >= INVITE_IP_SAME_INVITER_CAP:
            connection.execute("ROLLBACK")
            return {"status": "ignored", "reason": "ip_repeated"}

        referral_id = secrets.token_hex(16)
        now = _now().isoformat()
        connection.execute(
            """INSERT INTO referrals(id,inviter_id,invitee_id,code,status,signup_ip,created_at)
               VALUES (?,?,?,?,'pending',?,?)""",
            (referral_id, inviter["id"], invitee_id, code, ip, now),
        )
        # 注册奖励就在这个事务里发，所以「绑上了但没给分」不会作为中间态存在。
        credited = accounts.credit_bucket(
            connection, invitee_id, INVITE_SIGNUP_BONUS, "bonus",
            request_id=f"referral:signup:{referral_id}",
            source="referral", feature="邀请注册奖励",
            note=f"接受 {inviter['display_name']} 的邀请",
        )
        connection.execute("COMMIT")

    return {
        "status": "bound",
        "bonus": INVITE_SIGNUP_BONUS if credited else 0,
        "inviter": inviter_name,
    }


def on_usage_completed(request_id: str) -> None:
    """被邀请人跑完首个扣分任务 → 发双向激活奖励。"""
    if not _enabled():
        return
    with accounts.DB_LOCK, accounts._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        usage = connection.execute(
            "SELECT user_id,points FROM usage_records WHERE request_id=?", (request_id,)
        ).fetchone()
        if not usage or int(usage["points"] or 0) < 1:
            # 0 分步骤（如 /api/workbench/steps）跑通说明不了任何事，不算激活。
            connection.execute("ROLLBACK")
            return
        referral = connection.execute(
            """SELECT * FROM referrals WHERE invitee_id=? AND status IN ('pending','activated')""",
            (usage["user_id"],),
        ).fetchone()
        if not referral:
            connection.execute("ROLLBACK")
            return

        referral_id = referral["id"]
        now = _now().isoformat()
        claimed = connection.execute(
            """UPDATE referrals SET status='activated',activated_at=?
               WHERE id=? AND status IN ('pending','activated')""",
            (now, referral_id),
        ).rowcount
        if not claimed:
            connection.execute("ROLLBACK")
            return
        inviter_paid = accounts.credit_bucket(
            connection, referral["inviter_id"], INVITE_ACTIVATE_INVITER, "bonus",
            request_id=f"referral:inviter:{referral_id}",
            source="referral", feature="邀请激活奖励",
            note="邀请的好友完成了第一个任务",
        )
        invitee_paid = accounts.credit_bucket(
            connection, referral["invitee_id"], INVITE_ACTIVATE_INVITEE, "bonus",
            request_id=f"referral:invitee:{referral_id}",
            source="referral", feature="受邀激活奖励",
            note="完成第一个任务，邀请奖励已到账",
        )
        if inviter_paid or invitee_paid:
            connection.execute(
                "UPDATE referrals SET status='rewarded',rewarded_at=? WHERE id=?",
                (now, referral_id),
            )
        connection.execute("COMMIT")
    logger.info("referral.activated id=%s request=%s", referral_id, request_id)


def _masked(email: str) -> str:
    name, _, domain = str(email or "").partition("@")
    if not name:
        return ""
    keep = name[:2] if len(name) > 2 else name[:1]
    return f"{keep}****@{domain}"


def summary(user_id: str) -> dict[str, Any]:
    code = ensure_code(user_id)
    with accounts.DB_LOCK, accounts._connect() as connection:
        counts = {
            row["status"]: row["n"]
            for row in connection.execute(
                "SELECT status,COUNT(*) n FROM referrals WHERE inviter_id=? GROUP BY status",
                (user_id,),
            ).fetchall()
        }
        rows = connection.execute(
            """SELECT r.status,r.created_at,r.activated_at,u.display_name,u.email
               FROM referrals r JOIN users u ON u.id=r.invitee_id
               WHERE r.inviter_id=? ORDER BY r.created_at DESC LIMIT 50""",
            (user_id,),
        ).fetchall()
        earned = connection.execute(
            """SELECT COALESCE(SUM(amount),0) FROM point_transactions
               WHERE user_id=? AND source='referral'""",
            (user_id,),
        ).fetchone()[0]
        used_today = connection.execute(
            "SELECT COUNT(*) FROM referrals WHERE inviter_id=? AND created_at>=?",
            (user_id, _today_start()),
        ).fetchone()[0]
        used_month = connection.execute(
            "SELECT COUNT(*) FROM referrals WHERE inviter_id=? AND created_at>=?",
            (user_id, _month_start()),
        ).fetchone()[0]

    return {
        "code": code,
        "path": f"/?ref={code}",
        "enabled": _enabled(),
        "rewards": {
            "signup": INVITE_SIGNUP_BONUS,
            "activate_inviter": INVITE_ACTIVATE_INVITER,
            "activate_invitee": INVITE_ACTIVATE_INVITEE,
        },
        "caps": {
            "daily": INVITE_DAILY_CAP,
            "monthly": INVITE_MONTHLY_CAP,
            "remaining_today": max(0, INVITE_DAILY_CAP - used_today),
            "remaining_month": max(0, INVITE_MONTHLY_CAP - used_month),
        },
        "counts": {
            "pending": counts.get("pending", 0),
            "activated": counts.get("activated", 0),
            "rewarded": counts.get("rewarded", 0),
            "total": sum(counts.values()),
        },
        "earned_points": int(earned or 0),
        "invitees": [
            {
                "display_name": row["display_name"],
                "email": _masked(row["email"]),
                "status": row["status"],
                "created_at": row["created_at"],
                "activated_at": row["activated_at"],
            }
            for row in rows
        ],
    }


def admin_summary() -> dict[str, Any]:
    with accounts.DB_LOCK, accounts._connect() as connection:
        counts = {
            row["status"]: row["n"]
            for row in connection.execute(
                "SELECT status,COUNT(*) n FROM referrals GROUP BY status"
            ).fetchall()
        }
        inviters = connection.execute(
            "SELECT COUNT(DISTINCT inviter_id) FROM referrals"
        ).fetchone()[0]
        granted = connection.execute(
            "SELECT COALESCE(SUM(amount),0) FROM point_transactions WHERE source='referral'"
        ).fetchone()[0]
        top = connection.execute(
            """SELECT u.display_name,u.email,COUNT(*) invited,
                      SUM(CASE WHEN r.status='rewarded' THEN 1 ELSE 0 END) rewarded
               FROM referrals r JOIN users u ON u.id=r.inviter_id
               GROUP BY r.inviter_id,u.display_name,u.email
               ORDER BY invited DESC LIMIT 10"""
        ).fetchall()
    total = sum(counts.values())
    rewarded = counts.get("rewarded", 0)
    return {
        "enabled": _enabled(),
        "referrals": total,
        "pending": counts.get("pending", 0),
        "activated": counts.get("activated", 0),
        "rewarded": rewarded,
        "inviters": inviters,
        "points_granted": int(granted or 0),
        "activation_rate": round(rewarded / total, 3) if total else 0.0,
        "top_inviters": [
            {"display_name": r["display_name"], "email": _masked(r["email"]),
             "invited": r["invited"], "rewarded": r["rewarded"] or 0}
            for r in top
        ],
    }
