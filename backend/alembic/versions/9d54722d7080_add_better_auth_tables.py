"""Add Better-Auth tables

Revision ID: 9d54722d7080
Revises: d935687dded7
Create Date: 2025-09-26 20:57:48.757396

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9d54722d7080'
down_revision: Union[str, Sequence[str], None] = 'd935687dded7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create Better-Auth session table
    op.create_table(
        'session',
        sa.Column('id', sa.String(255), primary_key=True),
        sa.Column('userId', sa.String(255), nullable=False),
        sa.Column('expiresAt', sa.DateTime(timezone=True), nullable=False),
        sa.Column('token', sa.String(255), nullable=False, unique=True),
        sa.Column('ipAddress', sa.String(45)),
        sa.Column('userAgent', sa.Text()),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    
    # Create Better-Auth account table for social providers
    op.create_table(
        'account',
        sa.Column('id', sa.String(255), primary_key=True),
        sa.Column('userId', sa.String(255), nullable=False),
        sa.Column('accountId', sa.String(255), nullable=False),
        sa.Column('providerId', sa.String(255), nullable=False),
        sa.Column('accessToken', sa.Text()),
        sa.Column('refreshToken', sa.Text()),
        sa.Column('idToken', sa.Text()),
        sa.Column('accessTokenExpiresAt', sa.DateTime(timezone=True)),
        sa.Column('refreshTokenExpiresAt', sa.DateTime(timezone=True)),
        sa.Column('scope', sa.String(255)),
        sa.Column('password', sa.String(255)),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    
    # Create Better-Auth verification table
    op.create_table(
        'verification',
        sa.Column('id', sa.String(255), primary_key=True),
        sa.Column('identifier', sa.String(255), nullable=False),
        sa.Column('value', sa.String(255), nullable=False),
        sa.Column('expiresAt', sa.DateTime(timezone=True), nullable=False),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    
    # Add indexes
    op.create_index('idx_session_userId', 'session', ['userId'])
    op.create_index('idx_session_token', 'session', ['token'])
    op.create_index('idx_account_userId', 'account', ['userId'])
    op.create_index('idx_account_providerId', 'account', ['providerId'])
    op.create_index('idx_verification_identifier', 'verification', ['identifier'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_verification_identifier')
    op.drop_index('idx_account_providerId')
    op.drop_index('idx_account_userId')
    op.drop_index('idx_session_token')
    op.drop_index('idx_session_userId')
    op.drop_table('verification')
    op.drop_table('account')
    op.drop_table('session')
