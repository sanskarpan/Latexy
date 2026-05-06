"""Add career path tables (Feature 80).

Revision ID: 0021
Revises: 0020
Create Date: 2026-05-06
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = '0021'
down_revision = '0020'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── career_roles ──────────────────────────────────────────────────────────
    op.create_table(
        'career_roles',
        sa.Column('id', UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('level', sa.Text(), nullable=False),
        sa.Column('industry', sa.Text(), nullable=False),
        sa.Column('required_skills', sa.ARRAY(sa.Text()), nullable=False,
                  server_default='{}'),
        sa.Column('typical_yoe_min', sa.Integer(), nullable=True),
        sa.Column('typical_yoe_max', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
    )
    op.create_index('ix_career_roles_industry', 'career_roles', ['industry'])
    op.create_index('ix_career_roles_level', 'career_roles', ['level'])

    # ── career_transitions ────────────────────────────────────────────────────
    op.create_table(
        'career_transitions',
        sa.Column('from_role_id', UUID(as_uuid=False),
                  sa.ForeignKey('career_roles.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('to_role_id', UUID(as_uuid=False),
                  sa.ForeignKey('career_roles.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('avg_years', sa.Numeric(3, 1), nullable=True),
        sa.Column('difficulty', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('from_role_id', 'to_role_id'),
    )

    # ── career_analyses ───────────────────────────────────────────────────────
    op.create_table(
        'career_analyses',
        sa.Column('id', UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', UUID(as_uuid=False),
                  sa.ForeignKey('users.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('resume_id', UUID(as_uuid=False),
                  sa.ForeignKey('resumes.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('target_role_id', UUID(as_uuid=False),
                  sa.ForeignKey('career_roles.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('target_role_freetext', sa.Text(), nullable=True),
        sa.Column('current_skills', sa.ARRAY(sa.Text()), nullable=False,
                  server_default='{}'),
        sa.Column('gap_skills', sa.ARRAY(sa.Text()), nullable=False,
                  server_default='{}'),
        sa.Column('path_role_ids', sa.ARRAY(sa.Text()), nullable=True),
        sa.Column('timeline_months', sa.Integer(), nullable=True),
        sa.Column('llm_analysis', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
    )
    op.create_index('ix_career_analyses_user_resume',
                    'career_analyses', ['user_id', 'resume_id'])


def downgrade() -> None:
    op.drop_table('career_analyses')
    op.drop_table('career_transitions')
    op.drop_index('ix_career_roles_level', 'career_roles')
    op.drop_index('ix_career_roles_industry', 'career_roles')
    op.drop_table('career_roles')
