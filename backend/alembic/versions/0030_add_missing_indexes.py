"""Add missing indexes: session.userId, account.userId, compilations.resume_id, optimizations.resume_id.

Revision ID: 0030
Revises: 0029
Create Date: 2026-06-11
"""

from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # DB-003: session.userId — scanned on every authenticated request
    op.create_index("idx_session_user_id", "session", ["userId"])
    # DB-003: account.userId — no indexes existed on account table
    op.create_index("idx_account_user_id", "account", ["userId"])
    # DB-001: compilations.resume_id — queried heavily for resume history
    op.create_index("idx_compilations_resume_id", "compilations", ["resume_id"])
    # DB-002: optimizations.resume_id — queried heavily for resume optimization history
    op.create_index("idx_optimizations_resume_id", "optimizations", ["resume_id"])


def downgrade() -> None:
    op.drop_index("idx_optimizations_resume_id", "optimizations")
    op.drop_index("idx_compilations_resume_id", "compilations")
    op.drop_index("idx_account_user_id", "account")
    op.drop_index("idx_session_user_id", "session")
