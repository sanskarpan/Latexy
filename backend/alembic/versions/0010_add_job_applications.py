"""add_job_applications

Revision ID: 0010_add_job_applications
Revises: 0009_add_feature_flags
Create Date: 2026-03-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0010_add_job_applications'
down_revision: Union[str, None] = '0009_add_feature_flags'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'job_applications' not in inspector.get_table_names():
        op.create_table(
            'job_applications',
            sa.Column(
                'id',
                postgresql.UUID(as_uuid=False),
                primary_key=True,
                server_default=sa.text('gen_random_uuid()'),
            ),
            sa.Column('user_id', postgresql.UUID(as_uuid=False), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('company_name', sa.Text(), nullable=False),
            sa.Column('role_title', sa.Text(), nullable=False),
            sa.Column('status', sa.Text(), nullable=False, server_default='applied'),
            sa.Column(
                'resume_id',
                postgresql.UUID(as_uuid=False),
                sa.ForeignKey('resumes.id', ondelete='SET NULL'),
                nullable=True,
            ),
            sa.Column('ats_score_at_submission', sa.Float(), nullable=True),
            sa.Column('job_description_text', sa.Text(), nullable=True),
            sa.Column('job_url', sa.Text(), nullable=True),
            sa.Column('company_logo_url', sa.Text(), nullable=True),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('applied_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column(
                'updated_at',
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                onupdate=sa.func.now(),
            ),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index('idx_job_applications_user_id', 'job_applications', ['user_id'])
        op.create_index('idx_job_applications_status', 'job_applications', ['status'])
        op.create_index('idx_job_applications_resume_id', 'job_applications', ['resume_id'])


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'job_applications' in inspector.get_table_names():
        op.drop_index('idx_job_applications_resume_id', table_name='job_applications')
        op.drop_index('idx_job_applications_status', table_name='job_applications')
        op.drop_index('idx_job_applications_user_id', table_name='job_applications')
        op.drop_table('job_applications')
