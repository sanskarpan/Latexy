"""Add recruiter_notes table (Feature 73)."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = '0017'
down_revision = '0016'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'recruiter_notes',
        sa.Column('id', UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('workspace_id', UUID(as_uuid=False), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('resume_id', UUID(as_uuid=False), sa.ForeignKey('resumes.id', ondelete='CASCADE'), nullable=False),
        sa.Column('author_id', UUID(as_uuid=False), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('idx_recruiter_notes_workspace_resume', 'recruiter_notes', ['workspace_id', 'resume_id'])
    op.create_index('idx_recruiter_notes_author_id', 'recruiter_notes', ['author_id'])


def downgrade() -> None:
    op.drop_index('idx_recruiter_notes_author_id', table_name='recruiter_notes')
    op.drop_index('idx_recruiter_notes_workspace_resume', table_name='recruiter_notes')
    op.drop_table('recruiter_notes')
