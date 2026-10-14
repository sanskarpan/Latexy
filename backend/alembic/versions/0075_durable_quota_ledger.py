"""Create a disabled quota ledger; existing Redis balances remain unknown.

No application path writes these tables. An operator must fence legacy writes
and verify opening balances and outstanding receipts before reconciliation.
"""

import sqlalchemy as sa

from alembic import op

revision = "0075_durable_quota_ledger"
down_revision = "0074_redis_authority_freeze"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quota_ledger_accounts",
        sa.Column("user_id", sa.String(36), primary_key=True),
        sa.Column("dimension", sa.String(64), primary_key=True),
        sa.Column("period", sa.String(8), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("used", sa.BigInteger(), nullable=True),
        sa.Column("opening_used", sa.BigInteger(), nullable=True),
        sa.Column("source_ref", sa.String(255), nullable=True),
        sa.Column("source_sha256", sa.String(64), nullable=True),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('unknown', 'reconciled')", name="ck_quota_account_status"),
        sa.CheckConstraint(
            "(status = 'unknown' AND used IS NULL AND opening_used IS NULL AND "
            "source_ref IS NULL AND source_sha256 IS NULL AND reconciled_at IS NULL) OR "
            "(status = 'reconciled' AND used IS NOT NULL AND used >= 0 AND "
            "opening_used IS NOT NULL AND opening_used >= 0 AND "
            "source_ref IS NOT NULL AND length(trim(source_ref)) > 0 AND "
            "source_sha256 IS NOT NULL AND length(source_sha256) = 64 AND "
            "reconciled_at IS NOT NULL)",
            name="ck_quota_account_reconciliation",
        ),
    )
    op.create_table(
        "quota_ledger_reservations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("dimension", sa.String(64), nullable=False),
        sa.Column("period", sa.String(8), nullable=False),
        sa.Column("window", sa.String(8), nullable=False),
        sa.Column("intent_fingerprint", sa.String(64), nullable=False),
        sa.Column("cost", sa.BigInteger(), nullable=False),
        sa.Column("limit_value", sa.BigInteger(), nullable=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("used_after", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id", "dimension", "period"],
            ["quota_ledger_accounts.user_id", "quota_ledger_accounts.dimension", "quota_ledger_accounts.period"],
            name="fk_quota_reservation_account", ondelete="RESTRICT",
        ),
        sa.CheckConstraint("cost > 0", name="ck_quota_reservation_cost"),
        sa.CheckConstraint("limit_value IS NULL OR limit_value >= 0", name="ck_quota_reservation_limit"),
        sa.CheckConstraint("used_after >= 0", name="ck_quota_reservation_used"),
        sa.CheckConstraint(
            "(window = 'day' AND length(period) = 8) OR "
            "(window = 'month' AND length(period) = 6)",
            name="ck_quota_reservation_window",
        ),
        sa.CheckConstraint("length(intent_fingerprint) = 64", name="ck_quota_reservation_intent"),
        sa.CheckConstraint(
            "(state IN ('allowed', 'denied') AND refunded_at IS NULL AND settled_at IS NULL) OR "
            "(state = 'refunded' AND refunded_at IS NOT NULL AND settled_at IS NULL) OR "
            "(state = 'settled' AND settled_at IS NOT NULL AND refunded_at IS NULL)",
            name="ck_quota_reservation_state",
        ),
        sa.UniqueConstraint(
            "user_id", "dimension", "period", "intent_fingerprint",
            name="uq_quota_reservation_intent",
        ),
    )
    op.create_index(
        "ix_quota_reservations_account",
        "quota_ledger_reservations", ["user_id", "dimension", "period"],
    )


def downgrade() -> None:
    # Dropping an apparently empty ledger races a writer or pending migration.
    raise RuntimeError("quota ledger requires an explicit operator-reviewed recovery migration")
