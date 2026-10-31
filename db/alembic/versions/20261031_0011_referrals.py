"""Invite codes and the two-sided referral ledger.

The invite code on ``users`` is the only way to resolve an inviter, so it gets a
unique index. ``referrals`` keeps one row per invited account (``invitee_id`` is
unique), which is what makes "reward once per person" enforceable in SQL rather
than in application logic.
"""
from alembic import op
import sqlalchemy as sa


revision = "20261031_0011"
down_revision = "20261031_0010"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("invite_code", sa.String(16), nullable=True))
    op.create_index("uq_users_invite_code", "users", ["invite_code"], unique=True)
    op.create_table(
        "referrals",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("inviter_id", sa.String(64),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("invitee_id", sa.String(64),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("signup_ip", sa.String(64)),
        sa.Column("reject_reason", sa.String(64)),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("activated_at", sa.Text()),
        sa.Column("rewarded_at", sa.Text()),
        sa.CheckConstraint("status IN ('pending','activated','rewarded')",
                           name="ck_referrals_status"),
    )
    op.create_index("idx_referrals_inviter_time", "referrals", ["inviter_id", "created_at"])
    op.create_index("idx_referrals_signup_ip", "referrals",
                    ["signup_ip", "inviter_id", "created_at"])


def downgrade():
    op.drop_index("idx_referrals_signup_ip", table_name="referrals")
    op.drop_index("idx_referrals_inviter_time", table_name="referrals")
    op.drop_table("referrals")
    op.drop_index("uq_users_invite_code", table_name="users")
    op.drop_column("users", "invite_code")
