"""add resume archive field

Revision ID: 0014
Revises: 0013_add_collaboration
Create Date: 2026-04-08
"""
from alembic import op
import sqlalchemy as sa

revision = '0014'
down_revision = '0013_add_collaboration'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('resumes', sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True))

def downgrade() -> None:
    op.drop_column('resumes', 'archived_at')
