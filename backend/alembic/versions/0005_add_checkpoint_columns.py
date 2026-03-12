"""Add checkpoint columns to optimizations table

Revision ID: 0005_add_checkpoint_columns
Revises: 0004_add_resume_templates
Create Date: 2026-03-12
"""

from alembic import op
import sqlalchemy as sa

revision = "0005_add_checkpoint_columns"
down_revision = "0004_add_resume_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("optimizations", sa.Column("checkpoint_label", sa.Text(), nullable=True))
    op.add_column(
        "optimizations",
        sa.Column("is_checkpoint", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "optimizations",
        sa.Column("is_auto_save", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index(
        "idx_optimizations_resume_checkpoint",
        "optimizations",
        ["resume_id", "is_checkpoint"],
    )


def downgrade() -> None:
    op.drop_index("idx_optimizations_resume_checkpoint", table_name="optimizations")
    op.drop_column("optimizations", "is_auto_save")
    op.drop_column("optimizations", "is_checkpoint")
    op.drop_column("optimizations", "checkpoint_label")
