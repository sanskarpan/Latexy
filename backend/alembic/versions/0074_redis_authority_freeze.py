"""Reserve one durable Redis authority generation before any future cutover.

This migration does not enable backup routing.  The seeded legacy state records
the existing primary; a frozen state deliberately cannot name an active backup.
"""

import sqlalchemy as sa

from alembic import op

revision = "0074_redis_authority_freeze"
down_revision = "0073_d14_subfeatures"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "redis_authority_control",
        sa.Column("id", sa.SmallInteger(), primary_key=True),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("phase", sa.String(16), nullable=False),
        sa.Column("active_backend", sa.String(16), nullable=False),
        sa.Column("freeze_reason", sa.String(32), nullable=True),
        sa.Column("freeze_id", sa.String(36), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("id = 1", name="ck_redis_authority_singleton"),
        sa.CheckConstraint("generation >= 0", name="ck_redis_authority_generation"),
        sa.CheckConstraint("phase IN ('legacy', 'frozen')", name="ck_redis_authority_phase"),
        sa.CheckConstraint("active_backend = 'primary'", name="ck_redis_authority_primary_only"),
        sa.CheckConstraint(
            "(phase = 'legacy' AND freeze_reason IS NULL AND freeze_id IS NULL) OR "
            "(phase = 'frozen' AND freeze_reason IS NOT NULL AND freeze_id IS NOT NULL)",
            name="ck_redis_authority_freeze_reason",
        ),
    )
    op.execute(
        "INSERT INTO redis_authority_control "
        "(id, generation, phase, active_backend) VALUES (1, 0, 'legacy', 'primary')"
    )


def downgrade() -> None:
    conn = op.get_bind()
    row = conn.execute(sa.text(
        "SELECT generation, phase FROM redis_authority_control WHERE id = 1"
    )).first()
    if row is None or row.generation != 0 or row.phase != "legacy":
        # Never erase evidence that a cutover was attempted.
        raise RuntimeError("redis_authority_control requires an explicit recovery migration")
    op.drop_table("redis_authority_control")
