"""merge_email_notifs_and_interview_prep

Revision ID: 66f23068b722
Revises: 0010_add_email_notifications, 0011_add_interview_prep
Create Date: 2026-03-25 13:26:29.049454

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '66f23068b722'
down_revision: Union[str, Sequence[str], None] = ('0010_add_email_notifications', '0011_add_interview_prep')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
