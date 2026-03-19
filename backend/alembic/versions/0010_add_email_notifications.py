"""add_email_notifications

Revision ID: 0010_add_email_notifications
Revises: 0009_add_feature_flags
Create Date: 2026-03-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = '0010_add_email_notifications'
down_revision: Union[str, Sequence[str], None] = '0009_add_feature_flags'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c['name'] for c in inspector.get_columns('users')]
    if 'email_notifications' not in columns:
        op.add_column(
            'users',
            sa.Column(
                'email_notifications',
                JSONB,
                nullable=True,
                server_default='{"job_completed": true, "weekly_digest": false}',
            ),
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c['name'] for c in inspector.get_columns('users')]
    if 'email_notifications' in columns:
        op.drop_column('users', 'email_notifications')
