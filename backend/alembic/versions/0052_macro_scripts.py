"""Add bounded deterministic macro scripts (B53c).

Revision ID: 0052
Revises: 0051
"""

import sqlalchemy as sa
from alembic import op

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_macros", sa.Column("script", sa.Text(), nullable=True))
    op.add_column("user_macros", sa.Column("script_version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("user_macros", sa.Column("script_hash", sa.String(length=64), nullable=True))
    op.create_check_constraint(
        "ck_user_macros_script_size",
        "user_macros",
        "script IS NULL OR octet_length(script) <= 16384",
    )
    op.create_check_constraint(
        "ck_user_macros_script_version",
        "user_macros",
        "script_version >= 1",
    )
    op.create_check_constraint(
        "ck_user_macros_script_hash",
        "user_macros",
        "script_hash IS NULL OR script_hash ~ '^[0-9a-f]{64}$'",
    )
    op.create_check_constraint(
        "ck_user_macros_script_hash_complete",
        "user_macros",
        "(script IS NULL AND script_hash IS NULL) OR (script IS NOT NULL AND script_hash IS NOT NULL)",
    )
    # Existing recorded macros predate the cap. NOT VALID preserves those rows
    # while enforcing the bound for every new write/update; operators can
    # validate it after auditing oversized legacy payloads.
    op.execute(
        "ALTER TABLE user_macros ADD CONSTRAINT ck_user_macros_actions_size "
        "CHECK (octet_length(actions::text) <= 65536) NOT VALID"
    )


def downgrade() -> None:
    # IF EXISTS keeps downgrade safe when an operator applied an earlier
    # revision of this migration before the later hardening checks were added.
    for constraint in (
        "ck_user_macros_actions_size",
        "ck_user_macros_script_hash_complete",
        "ck_user_macros_script_hash",
        "ck_user_macros_script_version",
        "ck_user_macros_script_size",
    ):
        op.execute(f'ALTER TABLE user_macros DROP CONSTRAINT IF EXISTS {constraint}')
    op.drop_column("user_macros", "script_hash")
    op.drop_column("user_macros", "script_version")
    op.drop_column("user_macros", "script")
