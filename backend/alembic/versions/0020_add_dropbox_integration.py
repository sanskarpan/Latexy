"""Add Dropbox integration columns to users and resumes (Feature 77)."""

import sqlalchemy as sa
from alembic import op

revision = '0020'
down_revision = '0019'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Users: store encrypted Dropbox tokens + account ID
    op.add_column('users', sa.Column('dropbox_access_token', sa.Text(), nullable=True))
    op.add_column('users', sa.Column('dropbox_refresh_token', sa.Text(), nullable=True))
    op.add_column('users', sa.Column('dropbox_account_id', sa.String(255), nullable=True))

    # Resumes: per-resume sync settings
    op.add_column('resumes', sa.Column('dropbox_sync_enabled', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('resumes', sa.Column('dropbox_folder_path', sa.Text(), nullable=True))
    op.add_column('resumes', sa.Column('dropbox_last_sync_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('resumes', 'dropbox_last_sync_at')
    op.drop_column('resumes', 'dropbox_folder_path')
    op.drop_column('resumes', 'dropbox_sync_enabled')
    op.drop_column('users', 'dropbox_account_id')
    op.drop_column('users', 'dropbox_refresh_token')
    op.drop_column('users', 'dropbox_access_token')
