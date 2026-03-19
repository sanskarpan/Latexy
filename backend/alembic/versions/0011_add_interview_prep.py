"""add_interview_prep

Revision ID: 0011_add_interview_prep
Revises: 0010_add_job_applications
Create Date: 2026-03-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0011_add_interview_prep'
down_revision: Union[str, None] = '0010_add_job_applications'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'interview_prep' not in inspector.get_table_names():
        op.create_table(
            'interview_prep',
            sa.Column(
                'id',
                postgresql.UUID(as_uuid=False),
                primary_key=True,
                server_default=sa.text('gen_random_uuid()'),
            ),
            sa.Column('user_id', sa.Text(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=True),
            sa.Column(
                'resume_id',
                postgresql.UUID(as_uuid=False),
                sa.ForeignKey('resumes.id', ondelete='CASCADE'),
                nullable=False,
            ),
            sa.Column('job_description', sa.Text(), nullable=True),
            sa.Column('company_name', sa.Text(), nullable=True),
            sa.Column('role_title', sa.Text(), nullable=True),
            sa.Column('questions', postgresql.JSONB(), nullable=False, server_default='[]'),
            sa.Column('generation_job_id', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column(
                'updated_at',
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                onupdate=sa.func.now(),
            ),
        )
        op.create_index('idx_interview_prep_resume', 'interview_prep', ['resume_id'])
        op.create_index('idx_interview_prep_user', 'interview_prep', ['user_id'])


def downgrade() -> None:
    op.drop_index('idx_interview_prep_user', table_name='interview_prep')
    op.drop_index('idx_interview_prep_resume', table_name='interview_prep')
    op.drop_table('interview_prep')
