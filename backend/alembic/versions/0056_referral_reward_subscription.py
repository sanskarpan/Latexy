"""Link referral rewards to the exact referrer subscription term.

Revision ID: 0056
Revises: 0055
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "referral_rewards",
        sa.Column(
            "subscription_id",
            postgresql.UUID(as_uuid=False),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_referral_rewards_subscription_id",
        "referral_rewards",
        "subscriptions",
        ["subscription_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_referral_rewards_subscription_id",
        "referral_rewards",
        ["subscription_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_referral_rewards_subscription_id", table_name="referral_rewards")
    op.drop_constraint(
        "fk_referral_rewards_subscription_id",
        "referral_rewards",
        type_="foreignkey",
    )
    op.drop_column("referral_rewards", "subscription_id")
