"""Add session token index and composite performance indexes for resumes, compilations, and resume_views.

Revision ID: 0032
Revises: 0030
Create Date: 2026-06-11
"""

from alembic import op

revision = "0032"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # DB-003: session.token — looked up on every authenticated request (exact lookup)
    op.execute('CREATE INDEX IF NOT EXISTS idx_session_token ON session (token)')
    # DB-003: session.userId — re-apply idempotently (may already exist from 0030)
    op.execute('CREATE INDEX IF NOT EXISTS idx_session_user_id ON session ("userId")')
    # DB-003: account.userId — re-apply idempotently (may already exist from 0030)
    op.execute('CREATE INDEX IF NOT EXISTS idx_account_user_id ON account ("userId")')

    # DB-014: resume_views.viewed_at — range queries for analytics time windows
    op.execute("CREATE INDEX IF NOT EXISTS idx_resume_views_viewed_at ON resume_views (viewed_at)")

    # DB-015: resumes composite (user_id, updated_at DESC) — workspace list sorted by most recent
    op.execute("CREATE INDEX IF NOT EXISTS idx_resumes_user_updated ON resumes (user_id, updated_at DESC)")

    # DB-013: compilations composite (resume_id, status) — history queries filtered by status
    op.execute("CREATE INDEX IF NOT EXISTS idx_compilations_resume_status ON compilations (resume_id, status)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_compilations_resume_status")
    op.execute("DROP INDEX IF EXISTS idx_resumes_user_updated")
    op.execute("DROP INDEX IF EXISTS idx_resume_views_viewed_at")
    op.execute("DROP INDEX IF EXISTS idx_account_user_id")
    op.execute("DROP INDEX IF EXISTS idx_session_user_id")
    op.execute("DROP INDEX IF EXISTS idx_session_token")
