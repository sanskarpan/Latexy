"""Add per-resume public portfolio visibility.

Revision ID: 0038
Revises: 0037
Create Date: 2026-09-07
"""

from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE resumes ADD COLUMN IF NOT EXISTS "
        "portfolio_visible boolean NOT NULL DEFAULT false"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_resumes_public_portfolio "
        "ON resumes (user_id, updated_at DESC) "
        "WHERE portfolio_visible = true AND archived_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_resumes_public_portfolio")
    op.execute("ALTER TABLE resumes DROP COLUMN IF EXISTS portfolio_visible")
