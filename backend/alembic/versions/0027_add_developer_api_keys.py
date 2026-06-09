"""Add developer_api_keys table for Feature 21.

Revision ID: 0027
Revises: 0026
Create Date: 2026-05-19
"""

import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import ARRAY, UUID

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table("developer_api_keys"):
        op.create_table(
            "developer_api_keys",
            sa.Column("id", UUID(as_uuid=False), primary_key=True),
            sa.Column(
                "user_id",
                UUID(as_uuid=False),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("key_hash", sa.Text(), nullable=False),
            sa.Column("key_prefix", sa.String(length=32), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column(
                "scopes",
                ARRAY(sa.String()),
                nullable=False,
                server_default='{"compile","optimize","ats","export"}',
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )
        inspector = inspect(bind)

    indexes = {index["name"] for index in inspector.get_indexes("developer_api_keys")}
    if "ix_developer_api_keys_user_id" not in indexes:
        op.create_index("ix_developer_api_keys_user_id", "developer_api_keys", ["user_id"])

    uniques = {tuple(constraint["column_names"]) for constraint in inspector.get_unique_constraints("developer_api_keys")}
    if ("key_hash",) not in uniques:
        op.create_unique_constraint("uq_developer_api_keys_hash", "developer_api_keys", ["key_hash"])


def downgrade() -> None:
    op.drop_constraint("uq_developer_api_keys_hash", "developer_api_keys", type_="unique")
    op.drop_index("ix_developer_api_keys_user_id", table_name="developer_api_keys")
    op.drop_table("developer_api_keys")
