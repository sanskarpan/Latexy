"""add_feature_flags

Revision ID: 0009_add_feature_flags
Revises: 0008_add_resume_share_token
Create Date: 2026-03-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0009_add_feature_flags'
down_revision: Union[str, Sequence[str], None] = '0008_add_resume_share_token'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SEED_FLAGS = [
    ('trial_limits', True, 'Trial Limits', 'Anonymous: 3 uses, 5-min cooldown'),
    ('deep_analysis_trial', True, 'Deep Analysis Trial', '2 free deep analyses per device'),
    ('compile_timeouts', True, 'Compile Timeouts', 'free=30s, basic=120s, pro=240s'),
    ('task_priority', True, 'Task Priority', 'Higher plans get priority queue position'),
    ('billing', True, 'Billing & Payments', 'Billing page, nav link, subscriptions'),
    ('upgrade_ctas', True, 'Upgrade CTAs', 'Timeout banners and trial exhausted prompts'),
]


def upgrade() -> None:
    # Create table only if it doesn't already exist (idempotent)
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'feature_flags' not in inspector.get_table_names():
        op.create_table(
            'feature_flags',
            sa.Column('key', sa.String(100), primary_key=True),
            sa.Column('enabled', sa.Boolean(), nullable=False, server_default='true'),
            sa.Column('label', sa.String(255), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        )

    op.execute(
        sa.text(
            "INSERT INTO feature_flags (key, enabled, label, description) VALUES "
            "(:key0, :en0, :lb0, :ds0), "
            "(:key1, :en1, :lb1, :ds1), "
            "(:key2, :en2, :lb2, :ds2), "
            "(:key3, :en3, :lb3, :ds3), "
            "(:key4, :en4, :lb4, :ds4), "
            "(:key5, :en5, :lb5, :ds5) "
            "ON CONFLICT (key) DO NOTHING"
        ).bindparams(
            key0=_SEED_FLAGS[0][0], en0=_SEED_FLAGS[0][1], lb0=_SEED_FLAGS[0][2], ds0=_SEED_FLAGS[0][3],
            key1=_SEED_FLAGS[1][0], en1=_SEED_FLAGS[1][1], lb1=_SEED_FLAGS[1][2], ds1=_SEED_FLAGS[1][3],
            key2=_SEED_FLAGS[2][0], en2=_SEED_FLAGS[2][1], lb2=_SEED_FLAGS[2][2], ds2=_SEED_FLAGS[2][3],
            key3=_SEED_FLAGS[3][0], en3=_SEED_FLAGS[3][1], lb3=_SEED_FLAGS[3][2], ds3=_SEED_FLAGS[3][3],
            key4=_SEED_FLAGS[4][0], en4=_SEED_FLAGS[4][1], lb4=_SEED_FLAGS[4][2], ds4=_SEED_FLAGS[4][3],
            key5=_SEED_FLAGS[5][0], en5=_SEED_FLAGS[5][1], lb5=_SEED_FLAGS[5][2], ds5=_SEED_FLAGS[5][3],
        )
    )


def downgrade() -> None:
    op.drop_table('feature_flags')
