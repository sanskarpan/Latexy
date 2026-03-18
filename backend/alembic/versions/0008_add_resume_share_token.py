"""add_resume_share_token

Revision ID: 0008_add_resume_share_token
Revises: 0007_add_resume_metadata
Create Date: 2026-03-17

Stub — columns were added externally; this file just anchors the revision chain.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0008_add_resume_share_token'
down_revision: Union[str, Sequence[str], None] = '0007_add_resume_metadata'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add share_token columns if they don't already exist (idempotent)
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing = {c['name'] for c in inspector.get_columns('resumes')}
    if 'share_token' not in existing:
        op.add_column('resumes', sa.Column('share_token', sa.Text(), nullable=True))
        op.add_column('resumes', sa.Column('share_token_created_at', sa.DateTime(timezone=True), nullable=True))
        op.create_index(
            'idx_resumes_share_token',
            'resumes',
            ['share_token'],
            unique=True,
            postgresql_where=sa.text('share_token IS NOT NULL'),
        )


def downgrade() -> None:
    op.drop_index('idx_resumes_share_token', table_name='resumes')
    op.drop_column('resumes', 'share_token_created_at')
    op.drop_column('resumes', 'share_token')
