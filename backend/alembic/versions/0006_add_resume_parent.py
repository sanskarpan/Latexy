"""Add parent_resume_id to resumes table for variant/fork system

Revision ID: 0006_add_resume_parent
Revises: 0005_add_checkpoint_columns
Create Date: 2026-03-13
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0006_add_resume_parent"
down_revision = "0005_add_checkpoint_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "resumes",
        sa.Column(
            "parent_resume_id",
            UUID(as_uuid=False),
            sa.ForeignKey("resumes.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("idx_resumes_parent_id", "resumes", ["parent_resume_id"])


def downgrade() -> None:
    op.drop_index("idx_resumes_parent_id", table_name="resumes")
    op.drop_column("resumes", "parent_resume_id")
