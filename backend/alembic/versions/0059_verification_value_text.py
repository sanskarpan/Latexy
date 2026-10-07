"""Allow Better Auth OAuth state payloads longer than 255 characters.

Revision ID: 0059
Revises: 0058
"""

import sqlalchemy as sa

from alembic import op

revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Better Auth stores the serialized OAuth state (code verifier, callback
    # URLs, expiry, and OAuth state) in this value. It is not a short token.
    op.alter_column(
        "verification",
        "value",
        existing_type=sa.String(length=255),
        type_=sa.Text(),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Never truncate or silently discard an OAuth state row during rollback.
    # Refuse the downgrade until an operator has safely removed long-lived
    # verification records; expiration metadata alone is not a deletion
    # guarantee.
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM verification WHERE char_length(value) > 255) "
        "THEN RAISE EXCEPTION 'cannot downgrade 0059: verification values exceed 255 characters'; END IF; "
        "END $$"
    )
    op.alter_column(
        "verification",
        "value",
        existing_type=sa.Text(),
        type_=sa.String(length=255),
        existing_nullable=False,
    )
