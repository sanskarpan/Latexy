"""Quarantine oversized pre-cap macro actions without data loss.

Revision ID: 0053
Revises: 0052
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_macros",
        sa.Column("legacy_actions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    # Preserve the exact JSONB value, but leave only a bounded, non-executable
    # active representation.  The nullable archive is intentionally not
    # exposed by the normal API response.
    op.execute(
        "UPDATE user_macros SET legacy_actions = actions, actions = '[]'::jsonb "
        "WHERE octet_length(actions::text) > 65536 AND legacy_actions IS NULL"
    )
    op.execute("ALTER TABLE user_macros VALIDATE CONSTRAINT ck_user_macros_actions_size")


def downgrade() -> None:
    # Do not overwrite a user's replacement actions during rollback.  An
    # operator can delete/re-record the macro or explicitly remove the
    # quarantine first, but an automatic downgrade must fail closed.
    op.execute("ALTER TABLE user_macros DROP CONSTRAINT IF EXISTS ck_user_macros_actions_size")
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM user_macros WHERE legacy_actions IS NOT NULL AND actions <> '[]'::jsonb) "
        "THEN RAISE EXCEPTION 'cannot downgrade 0053: quarantined macro actions were replaced'; END IF; "
        "END $$"
    )
    op.execute(
        "UPDATE user_macros SET actions = legacy_actions WHERE legacy_actions IS NOT NULL AND actions = '[]'::jsonb"
    )
    op.drop_column("user_macros", "legacy_actions")
    # Restore the 0052 compatibility behavior: existing oversized rows are
    # allowed to remain, while future writes and updates are constrained.
    op.execute(
        "ALTER TABLE user_macros ADD CONSTRAINT ck_user_macros_actions_size "
        "CHECK (octet_length(actions::text) <= 65536) NOT VALID"
    )
