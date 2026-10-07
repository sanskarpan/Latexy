"""Track reserved coupons against checkout intents.

Revision ID: 0061
Revises: 0060
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0061"
down_revision = "0060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "coupon_redemptions",
        sa.Column("subscription_id", postgresql.UUID(as_uuid=False), nullable=True),
    )
    op.create_foreign_key(
        "fk_coupon_redemptions_subscription_id_subscriptions",
        "coupon_redemptions",
        "subscriptions",
        ["subscription_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_coupon_redemptions_subscription_id",
        "coupon_redemptions",
        ["subscription_id"],
    )
    # Existing rows represent previously counted coupon redemptions.
    op.add_column(
        "coupon_redemptions",
        sa.Column("status", sa.String(length=20), nullable=False, server_default="redeemed"),
    )
    op.alter_column("coupon_redemptions", "redeemed_at", nullable=True)


def downgrade() -> None:
    op.execute("UPDATE coupon_redemptions SET redeemed_at = NOW() WHERE redeemed_at IS NULL")
    op.alter_column("coupon_redemptions", "redeemed_at", nullable=False)
    op.drop_column("coupon_redemptions", "status")
    op.drop_index("ix_coupon_redemptions_subscription_id", table_name="coupon_redemptions")
    op.drop_constraint(
        "fk_coupon_redemptions_subscription_id_subscriptions",
        "coupon_redemptions",
        type_="foreignkey",
    )
    op.drop_column("coupon_redemptions", "subscription_id")
