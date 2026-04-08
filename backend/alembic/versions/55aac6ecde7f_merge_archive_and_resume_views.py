"""merge_archive_and_resume_views

Revision ID: 55aac6ecde7f
Revises: 0014, 0014_add_resume_views
Create Date: 2026-04-08 15:19:22.731997

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '55aac6ecde7f'
down_revision: Union[str, Sequence[str], None] = ('0014', '0014_add_resume_views')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
