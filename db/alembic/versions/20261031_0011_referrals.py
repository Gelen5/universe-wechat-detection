"""Invite codes and the two-sided referral ledger.

The invite code on ``users`` is the only way to resolve an inviter, so it gets a
unique index. ``referrals`` keeps one row per invited account (``invitee_id`` is
unique), which is what makes "reward once per person" enforceable in SQL rather
than in application logic.

Every step is guarded: production never runs this migration (``deploy.sh``
starts the stack with ``--no-deps``, so the compose ``migrate`` service is
skipped and ``referrals.init_schema()`` creates the same shape at import time).
A later ``alembic upgrade head`` against such a database must not collide.
"""
from alembic import op
import sqlalchemy as sa


revision = "20261031_0011"
down_revision = "20261031_0010"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade():
    if "invite_code" not in _columns("users"):
        op.add_column("users", sa.Column("invite_code", sa.String(16), nullable=True))
    if "uq_users_invite_code" not in _indexes("users"):
        op.create_index("uq_users_invite_code", "users", ["invite_code"], unique=True)

    if "referrals" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "referrals",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("inviter_id", sa.String(64), nullable=False),
            sa.Column("invitee_id", sa.String(64), nullable=False, unique=True),
            sa.Column("code", sa.String(16), nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
            sa.Column("signup_ip", sa.String(64)),
            sa.Column("reject_reason", sa.String(64)),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.Column("activated_at", sa.Text()),
            sa.Column("rewarded_at", sa.Text()),
            # 约束名要和 referrals.init_schema 用 ALTER 补出来的一致，
            # 否则两条建表路径产出的不是同一张表。
            sa.ForeignKeyConstraint(["inviter_id"], ["users.id"],
                                    name="fk_referrals_inviter", ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["invitee_id"], ["users.id"],
                                    name="fk_referrals_invitee", ondelete="CASCADE"),
            sa.CheckConstraint("status IN ('pending','activated','rewarded')",
                               name="ck_referrals_status"),
        )

    existing = _indexes("referrals")
    if "idx_referrals_inviter_time" not in existing:
        op.create_index("idx_referrals_inviter_time", "referrals",
                        ["inviter_id", "created_at"])
    if "idx_referrals_signup_ip" not in existing:
        op.create_index("idx_referrals_signup_ip", "referrals",
                        ["signup_ip", "inviter_id", "created_at"])


def downgrade():
    if "referrals" in sa.inspect(op.get_bind()).get_table_names():
        for name in ("idx_referrals_signup_ip", "idx_referrals_inviter_time"):
            if name in _indexes("referrals"):
                op.drop_index(name, table_name="referrals")
        op.drop_table("referrals")
    if "uq_users_invite_code" in _indexes("users"):
        op.drop_index("uq_users_invite_code", table_name="users")
    if "invite_code" in _columns("users"):
        op.drop_column("users", "invite_code")
