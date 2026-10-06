"""Require DNS ownership verification before serving tenant custom domains.

Revision ID: 0042
Revises: 0041
Create Date: 2026-09-12
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing custom domains were never verified, so they intentionally start
    # inactive and must pass the new DNS proof before middleware uses them.
    op.add_column(
        "tenants",
        sa.Column("domain_verified_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_tenants_verified_custom_domain",
        "tenants",
        ["custom_domain"],
        unique=False,
        postgresql_where=sa.text("domain_verified_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_tenants_verified_custom_domain", table_name="tenants")
    op.drop_column("tenants", "domain_verified_at")
