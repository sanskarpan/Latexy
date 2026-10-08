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
    has_saved_quotes = op.get_bind().execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM subscriptions WHERE quoted_tax_inclusive IS NOT NULL)"
    )).scalar_one()
    if has_saved_quotes:
        raise RuntimeError(
            "cannot downgrade billing revision 0066: immutable subscription tax-quote evidence exists"
        )
    op.drop_column("subscriptions", "quoted_tax_inclusive")
