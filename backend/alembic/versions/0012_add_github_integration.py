"""add_github_integration

Revision ID: 0012_add_github_integration
Revises: 66f23068b722
Create Date: 2026-04-01

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = '0012_add_github_integration'
down_revision: Union[str, Sequence[str], None] = '66f23068b722'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # -- users table --
    user_cols = [c['name'] for c in inspector.get_columns('users')]
    if 'github_access_token' not in user_cols:
        op.add_column('users', sa.Column('github_access_token', sa.Text, nullable=True))
    if 'github_username' not in user_cols:
        op.add_column('users', sa.Column('github_username', sa.String(255), nullable=True))

    # -- resumes table --
    resume_cols = [c['name'] for c in inspector.get_columns('resumes')]
    if 'github_sync_enabled' not in resume_cols:
        op.add_column(
            'resumes',
            sa.Column('github_sync_enabled', sa.Boolean, nullable=False, server_default='false'),
        )
    if 'github_repo_name' not in resume_cols:
        op.add_column('resumes', sa.Column('github_repo_name', sa.Text, nullable=True))
    if 'github_last_sync_at' not in resume_cols:
        op.add_column(
            'resumes',
            sa.Column('github_last_sync_at', sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    resume_cols = [c['name'] for c in inspector.get_columns('resumes')]
    for col in ('github_last_sync_at', 'github_repo_name', 'github_sync_enabled'):
        if col in resume_cols:
            op.drop_column('resumes', col)

    user_cols = [c['name'] for c in inspector.get_columns('users')]
    for col in ('github_username', 'github_access_token'):
        if col in user_cols:
            op.drop_column('users', col)
