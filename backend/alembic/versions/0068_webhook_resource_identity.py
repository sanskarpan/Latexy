"""Bind webhook retries to an immutable provider resource identity.

Revision ID: 0068
Revises: 0067
"""

import sqlalchemy as sa

from alembic import op

revision = "0068"
down_revision = "0067"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Historical inbox rows have no recoverable payload, so leave their
    # identity unknown. Their changed-body retry policy must remain closed.
    op.add_column(
        "billing_webhook_events",
        sa.Column("event_resource_id", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    has_identity_evidence = op.get_bind().execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM billing_webhook_events WHERE event_resource_id IS NOT NULL)"
    )).scalar_one()
    if has_identity_evidence:
        raise RuntimeError(
            "cannot downgrade billing revision 0068: immutable webhook resource identity evidence exists"
        )
    op.drop_column("billing_webhook_events", "event_resource_id")
