"""Store whether a subscription quote includes tax.

Revision ID: 0066
Revises: 0065
"""

import sqlalchemy as sa

from alembic import op

revision = "0066"
down_revision = "0065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep NULL for existing intents: their signed checkout metadata or the
    # current plan setting is used as a compatibility fallback.
    op.add_column(
        "subscriptions",
        sa.Column("quoted_tax_inclusive", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("subscriptions", "quoted_tax_inclusive")
