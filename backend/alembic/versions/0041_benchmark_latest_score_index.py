"""Index the latest valid benchmark score per resume.

Revision ID: 0041
Revises: 0040
Create Date: 2026-09-12
"""

from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_optimizations_resume_latest_score
        ON optimizations (resume_id, created_at DESC, id DESC)
        WHERE ats_score BETWEEN 0 AND 100
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_optimizations_resume_latest_score")
