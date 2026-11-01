"""Permit a declared spare handover of durable Redis authority.

This migration does not move any authority. It only widens the singleton
control row so a later, separately authorized handover transaction can name
the spare backend. Phase and backend remain 'frozen'/'primary' until that
handover commits; startup and admission gates keep blocking until then.
"""

from alembic import op

revision = "0076_spare_authority_handover"
down_revision = "0075_durable_quota_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("redis_authority_control") as batch_op:
        batch_op.drop_constraint("ck_redis_authority_phase")
        batch_op.create_check_constraint(
            "ck_redis_authority_phase",
            "phase IN ('legacy', 'frozen', 'spare')",
        )
        batch_op.drop_constraint("ck_redis_authority_primary_only")
        batch_op.create_check_constraint(
            "ck_redis_authority_primary_only",
            "active_backend IN ('primary', 'spare')",
        )
        batch_op.drop_constraint("ck_redis_authority_freeze_reason")
        batch_op.create_check_constraint(
            "ck_redis_authority_freeze_reason",
            "(phase = 'legacy' AND freeze_reason IS NULL AND freeze_id IS NULL) OR "
            "(phase IN ('frozen', 'spare') AND freeze_reason IS NOT NULL AND freeze_id IS NOT NULL)",
        )


def downgrade() -> None:
    # Dropping or narrowing these constraints races a concurrent handover the
    # same way dropping the table races a freeze. Recovery requires a separate
    # operator-reviewed plan, never a generic downgrade.
    raise RuntimeError("redis_authority_control requires an explicit recovery migration")
