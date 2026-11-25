"""Append-only subscription plan/status history for movement and churn metrics.

Every provider checkout/lifecycle transition is written by the billing service
inside the same transaction that mutates ``subscriptions``. The natural key
``(subscription_id, effective_at, plan_id, status)`` makes retries and duplicate
webhook deliveries idempotent, so one observed transition cannot be recorded
twice.

Backfill behaviour for existing rows
------------------------------------
``subscriptions`` only stores the current plan/status, so pre-0083 history
cannot be replayed from logs. This migration therefore writes exactly one
baseline snapshot per existing subscription:

* ``effective_at`` is ``provider_event_at`` when known, otherwise the local
  ``updated_at``/``created_at``;
* ``previous_plan_id`` and ``previous_status`` stay NULL because the preceding
  state is unknown;
* ``event_type`` is ``backfill``, ``reason`` is ``backfill`` and ``source`` is
  ``backfill``.

Backfill rows are state snapshots, not reconstructed transitions. Movement,
cancellation and churn counters deliberately exclude them; they only seed the
state-at-period-start/end calculation. Re-running the backfill is safe because
it uses ``ON CONFLICT DO NOTHING``.

Privacy: the table stores a user UUID, plan/status identifiers and period
timestamps only. It has no email, name, document, provider payload, token or
free-form reason columns.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0083_subscription_history"
down_revision = "0082_signup_funnel_providers"
branch_labels = None
depends_on = None

EVENT_TYPES = (
    "subscription_created",
    "plan_changed",
    "status_changed",
    "activated",
    "renewed",
    "period_updated",
    "cancellation_scheduled",
    "cancelled",
    "expired",
    "payment_failed",
    "refunded",
    "checkout_failed",
    "checkout_unknown",
    "admin_override",
    "backfill",
)
SOURCES = ("billing", "checkout", "reconcile", "admin", "backfill")

BACKFILL_SQL = """
INSERT INTO subscription_history (
    id, user_id, subscription_id, plan_id, previous_plan_id, status,
    previous_status, current_period_start, current_period_end, event_type,
    reason, source, effective_at, recorded_at
)
SELECT
    gen_random_uuid(),
    s.user_id,
    s.id,
    s.plan_id,
    NULL,
    s.status,
    NULL,
    s.current_period_start,
    s.current_period_end,
    'backfill',
    'backfill',
    'backfill',
    COALESCE(s.provider_event_at, s.updated_at, s.created_at, now()),
    now()
FROM subscriptions AS s
ON CONFLICT (subscription_id, effective_at, plan_id, status) DO NOTHING
"""


def _in_clause(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def upgrade() -> None:
    op.create_table(
        "subscription_history",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "subscription_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("subscriptions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("plan_id", sa.String(50), nullable=False),
        sa.Column("previous_plan_id", sa.String(50), nullable=True),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("previous_status", sa.String(50), nullable=True),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(64), nullable=False),
        sa.Column(
            "source",
            sa.String(24),
            nullable=False,
            server_default="billing",
        ),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            _in_clause("event_type", EVENT_TYPES),
            name="ck_subscription_history_event_type",
        ),
        sa.CheckConstraint(
            _in_clause("source", SOURCES),
            name="ck_subscription_history_source",
        ),
        sa.UniqueConstraint(
            "subscription_id",
            "effective_at",
            "plan_id",
            "status",
            name="uq_subscription_history_transition",
        ),
    )
    op.create_index(
        "idx_subscription_history_user_effective",
        "subscription_history",
        ["user_id", "effective_at"],
    )
    op.create_index(
        "idx_subscription_history_effective_type",
        "subscription_history",
        ["effective_at", "event_type"],
    )
    op.create_index(
        "idx_subscription_history_subscription_effective",
        "subscription_history",
        ["subscription_id", "effective_at"],
    )
    op.execute(BACKFILL_SQL)


def downgrade() -> None:
    op.drop_index(
        "idx_subscription_history_subscription_effective",
        table_name="subscription_history",
    )
    op.drop_index(
        "idx_subscription_history_effective_type",
        table_name="subscription_history",
    )
    op.drop_index(
        "idx_subscription_history_user_effective",
        table_name="subscription_history",
    )
    op.drop_table("subscription_history")
