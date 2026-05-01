"""Add portfolio columns to users table (Feature 67)."""

import sqlalchemy as sa
from alembic import op

revision = '0019'
down_revision = '0018'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('public_username', sa.Text(), nullable=True, unique=True))
    op.add_column('users', sa.Column('portfolio_enabled', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('users', sa.Column('portfolio_custom_domain', sa.Text(), nullable=True, unique=True))
    op.add_column('users', sa.Column('portfolio_theme', sa.Text(), nullable=False, server_default='minimal'))
    op.add_column('users', sa.Column('portfolio_tagline', sa.Text(), nullable=True))
    op.create_index('idx_users_public_username', 'users', ['public_username'])


def downgrade() -> None:
    op.drop_index('idx_users_public_username', table_name='users')
    op.drop_column('users', 'portfolio_tagline')
    op.drop_column('users', 'portfolio_theme')
    op.drop_column('users', 'portfolio_custom_domain')
    op.drop_column('users', 'portfolio_enabled')
    op.drop_column('users', 'public_username')
