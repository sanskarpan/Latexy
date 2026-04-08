"""Add user_metadata JSONB column for reference manager tokens (Feature 42)."""

import sqlalchemy as sa
from alembic import op

revision = '0015'
down_revision = '55aac6ecde7f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('user_metadata', sa.dialects.postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('users', 'user_metadata')
