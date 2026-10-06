"""Link career-centre cohorts to tenants and track student milestones.

Revision ID: 0043
Revises: 0042
Create Date: 2026-09-12
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_workspaces_tenant_id",
        "workspaces",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_workspaces_tenant_id", "workspaces", ["tenant_id"])
    op.add_column(
        "workspace_resumes",
        sa.Column("opened_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "workspace_resumes",
        sa.Column("downloaded_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workspace_resumes", "downloaded_at")
    op.drop_column("workspace_resumes", "opened_at")
    op.drop_index("ix_workspaces_tenant_id", table_name="workspaces")
    op.drop_constraint("fk_workspaces_tenant_id", "workspaces", type_="foreignkey")
    op.drop_column("workspaces", "tenant_id")
