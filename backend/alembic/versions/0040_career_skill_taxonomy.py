"""Persist ESCO provenance for career skill-gap analyses.

Revision ID: 0040
Revises: 0039
Create Date: 2026-09-08
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("career_analyses", sa.Column("skill_taxonomy", sa.String(40), nullable=True))
    op.add_column("career_analyses", sa.Column("skill_taxonomy_language", sa.String(5), nullable=True))
    op.add_column("career_analyses", sa.Column("skill_taxonomy_mappings", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("career_analyses", "skill_taxonomy_mappings")
    op.drop_column("career_analyses", "skill_taxonomy_language")
    op.drop_column("career_analyses", "skill_taxonomy")
