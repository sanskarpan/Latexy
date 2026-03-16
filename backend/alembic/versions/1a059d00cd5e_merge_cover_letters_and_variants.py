"""merge_cover_letters_and_variants

Revision ID: 1a059d00cd5e
Revises: 0006_add_cover_letters, 0006_add_resume_parent
Create Date: 2026-03-16 12:23:08.409295

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1a059d00cd5e'
down_revision: Union[str, Sequence[str], None] = ('0006_add_cover_letters', '0006_add_resume_parent')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
