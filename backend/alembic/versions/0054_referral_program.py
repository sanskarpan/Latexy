"""Add server-authoritative user referral attribution and reward ledger (B59).

Revision ID: 0054
Revises: 0053
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "referral_identities",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("code_digest", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", name="uq_referral_identities_user"),
        sa.UniqueConstraint("code", name="uq_referral_identities_code"),
        sa.UniqueConstraint("code_digest", name="uq_referral_identities_digest"),
    )
    op.create_index("ix_referral_identities_user_id", "referral_identities", ["user_id"])
    op.create_index("ix_referral_identities_code_digest", "referral_identities", ["code_digest"])

    op.create_table(
        "referral_attributions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("referral_identity_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("referrer_user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("referred_user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="captured", nullable=False),
        sa.Column("rejection_reason", sa.String(length=64), nullable=True),
        sa.Column("qualifying_payment_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("qualified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["referral_identity_id"], ["referral_identities.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["referrer_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["referred_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["qualifying_payment_id"], ["payments.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("referred_user_id", name="uq_referral_attributions_referred_user"),
        sa.UniqueConstraint("qualifying_payment_id", name="uq_referral_attributions_payment"),
    )
    op.create_index("ix_referral_attributions_referrer_user_id", "referral_attributions", ["referrer_user_id"])
    op.create_index("ix_referral_attributions_referred_user_id", "referral_attributions", ["referred_user_id"])
    op.create_index(
        "ix_referral_attributions_referrer_status",
        "referral_attributions",
        ["referrer_user_id", "status"],
    )

    op.create_table(
        "referral_rewards",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("attribution_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("referrer_user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("qualifying_payment_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("reward_type", sa.String(length=32), nullable=False),
        sa.Column("reward_value", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("period_end_before", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["attribution_id"], ["referral_attributions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["referrer_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["qualifying_payment_id"], ["payments.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("attribution_id", name="uq_referral_rewards_attribution"),
        sa.UniqueConstraint("qualifying_payment_id", name="uq_referral_rewards_payment"),
    )
    op.create_index("ix_referral_rewards_referrer_user_id", "referral_rewards", ["referrer_user_id"])


def downgrade() -> None:
    op.drop_index("ix_referral_rewards_referrer_user_id", table_name="referral_rewards")
    op.drop_table("referral_rewards")
    op.drop_index("ix_referral_attributions_referrer_status", table_name="referral_attributions")
    op.drop_index("ix_referral_attributions_referred_user_id", table_name="referral_attributions")
    op.drop_index("ix_referral_attributions_referrer_user_id", table_name="referral_attributions")
    op.drop_table("referral_attributions")
    op.drop_index("ix_referral_identities_code_digest", table_name="referral_identities")
    op.drop_index("ix_referral_identities_user_id", table_name="referral_identities")
    op.drop_table("referral_identities")
