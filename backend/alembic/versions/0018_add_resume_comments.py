"""Add resume_comments table (Feature 74)."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = '0018'
down_revision = '0017'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'resume_comments',
        sa.Column('id', UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('resume_id', UUID(as_uuid=False), sa.ForeignKey('resumes.id', ondelete='CASCADE'), nullable=False),
        sa.Column('workspace_id', UUID(as_uuid=False), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=True),
        sa.Column('author_id', UUID(as_uuid=False), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('line_number', sa.Integer(), nullable=True),
        sa.Column('section_tag', sa.String(100), nullable=True),
        sa.Column('resolved', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('idx_resume_comments_resume_id', 'resume_comments', ['resume_id'])
    op.create_index('idx_resume_comments_workspace_id', 'resume_comments', ['workspace_id'])
    op.create_index('idx_resume_comments_author_id', 'resume_comments', ['author_id'])


def downgrade() -> None:
    op.drop_index('idx_resume_comments_author_id', table_name='resume_comments')
    op.drop_index('idx_resume_comments_workspace_id', table_name='resume_comments')
    op.drop_index('idx_resume_comments_resume_id', table_name='resume_comments')
    op.drop_table('resume_comments')
