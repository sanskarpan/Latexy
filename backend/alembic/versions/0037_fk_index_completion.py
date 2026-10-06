"""Complete foreign-key indexes and remove a redundant session index.

Revision ID: 0037
Revises: 0036
Create Date: 2026-08-31
"""

from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


_FK_INDEXES = (
    ("career_analyses", "resume_id", "ix_career_analyses_resume_id"),
    ("recruiter_notes", "resume_id", "ix_recruiter_notes_resume_id"),
    ("snippet_installs", "user_id", "ix_snippet_installs_user_id"),
    ("snippet_upvotes", "user_id", "ix_snippet_upvotes_user_id"),
    ("users", "default_tenant_id", "ix_users_default_tenant_id"),
    ("workspace_members", "invited_by", "ix_workspace_members_invited_by"),
    ("workspace_resumes", "resume_id", "ix_workspace_resumes_resume_id"),
    ("workspace_resumes", "shared_by", "ix_workspace_resumes_shared_by"),
)


def upgrade() -> None:
    for table, column, name in _FK_INDEXES:
        op.execute(f'CREATE INDEX IF NOT EXISTS {name} ON {table} ("{column}")')

    # uq_session_token already provides the same btree lookup path.
    op.execute("DROP INDEX IF EXISTS idx_session_token")


def downgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS idx_session_token ON session (token)")
    for table, _column, name in reversed(_FK_INDEXES):
        op.execute(f"DROP INDEX IF EXISTS {name}")
