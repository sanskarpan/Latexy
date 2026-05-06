"""add snippet marketplace tables

Revision ID: 0022
Revises: 0021
Create Date: 2026-05-06
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers
revision = '0022'
down_revision = '0021'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── snippets ──────────────────────────────────────────────────────────────
    op.create_table(
        'snippets',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('author_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('category', sa.Text(), nullable=False),
        sa.Column('tags', postgresql.ARRAY(sa.Text()), nullable=False, server_default='{}'),
        sa.Column('is_official', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('installs_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('upvotes_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_snippets_category', 'snippets', ['category'])
    op.create_index('ix_snippets_installs_count', 'snippets', [sa.text('installs_count DESC')])

    # ── snippet_installs ──────────────────────────────────────────────────────
    op.create_table(
        'snippet_installs',
        sa.Column('snippet_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('installed_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['snippet_id'], ['snippets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('snippet_id', 'user_id'),
    )

    # ── snippet_upvotes ───────────────────────────────────────────────────────
    op.create_table(
        'snippet_upvotes',
        sa.Column('snippet_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(['snippet_id'], ['snippets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('snippet_id', 'user_id'),
    )


def downgrade() -> None:
    op.drop_table('snippet_upvotes')
    op.drop_table('snippet_installs')
    op.drop_index('ix_snippets_installs_count', table_name='snippets')
    op.drop_index('ix_snippets_category', table_name='snippets')
    op.drop_table('snippets')
