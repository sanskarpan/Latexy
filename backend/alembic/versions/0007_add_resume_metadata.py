"""add_resume_metadata

Revision ID: 0007_add_resume_metadata
Revises: 1a059d00cd5e
Create Date: 2026-03-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = '0007_add_resume_metadata'
down_revision: Union[str, Sequence[str], None] = '1a059d00cd5e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add metadata JSONB column to resumes table for per-resume settings (compiler, etc.)."""
    op.add_column(
        'resumes',
        sa.Column(
            'metadata',
            JSONB,
            nullable=True,
            server_default='{}',
            comment='Per-resume settings: compiler, custom flags, etc.',
        ),
    )


def downgrade() -> None:
    """Remove metadata column from resumes."""
    op.drop_column('resumes', 'metadata')
