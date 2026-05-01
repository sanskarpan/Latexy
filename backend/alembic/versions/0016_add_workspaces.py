"""Add team workspace tables (Feature 66)."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'workspaces',
        sa.Column('id', UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('owner_id', UUID(as_uuid=False), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('plan_id', sa.String(50), nullable=False, server_default='free'),
        sa.Column('max_members', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('idx_workspaces_owner_id', 'workspaces', ['owner_id'])

    op.create_table(
        'workspace_members',
        sa.Column('workspace_id', UUID(as_uuid=False), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', UUID(as_uuid=False), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(20), nullable=False, server_default='editor'),
        sa.Column('invited_by', UUID(as_uuid=False), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('invited_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('joined_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('workspace_id', 'user_id'),
    )
    op.create_index('idx_workspace_members_user_id', 'workspace_members', ['user_id'])

    op.create_table(
        'workspace_resumes',
        sa.Column('workspace_id', UUID(as_uuid=False), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('resume_id', UUID(as_uuid=False), sa.ForeignKey('resumes.id', ondelete='CASCADE'), nullable=False),
        sa.Column('shared_by', UUID(as_uuid=False), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('shared_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('workspace_id', 'resume_id'),
    )


def downgrade() -> None:
    op.drop_table('workspace_resumes')
    op.drop_index('idx_workspace_members_user_id', table_name='workspace_members')
    op.drop_table('workspace_members')
    op.drop_index('idx_workspaces_owner_id', table_name='workspaces')
    op.drop_table('workspaces')
