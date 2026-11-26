"""Append-only subscription status history for dunning and recovery metrics.

Provider lifecycle webhooks already mutate the current ``subscriptions`` row,
but that row cannot explain how a past-due or on-hold account reached its
current state. This ledger records every observed status transition with the
provider event time, an allowlisted reason and the source that observed it.

Out-of-order ingestion
----------------------
Rows are keyed by ``(subscription_id, provider_event_at, status)``. A duplicate
webhook delivery therefore writes one row. An older provider event is still
recorded for chronological reconstruction but is marked ``applied = false`` so
it cannot regress the current subscription state. Readers order by
``provider_event_at`` (then ``recorded_at``) rather than insertion order.

Privacy
-------
The table stores a user UUID, subscription UUID, plan/status identifiers,
timestamps and allowlisted metadata. It has no email, name, document content,
provider payload, token or free-form note column.

Backfill behaviour
------------------
Only subscriptions that are currently in a dunning state are seeded as one
``backfill`` observation. Their original start time is unknown, so the report
labels those cases as open-at-period-start instead of inventing a recovery
history. Re-running the backfill is safe because it uses ``ON CONFLICT DO
NOTHING``.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0091_dunning_history"
down_revision = "0088_admin_incidents"
branch_labels = None
depends_on = None

EVENT_TYPES = (
    "dunning_started",
    "dunning_escalated",
    "recovered",
    "cancelled",
    "expired",
    "failed",
    "status_observed",
    "backfill",
)
SOURCES = ("billing", "checkout", "reconcile", "admin", "backfill")

BACKFILL_SQL = """
INSERT INTO subscription_status_history (
    id, user_id, subscription_id, plan_id, status, previous_status,
    event_type, reason, source, provider_event_at, applied
)
SELECT
    gen_random_uuid(),
    s.user_id,
    s.id,
    s.plan_id,
    s.status,
    NULL,
    'backfill',
    'backfill',
    'backfill',
    COALESCE(s.provider_event_at, s.updated_at, s.created_at, now()),
    true
FROM subscriptions AS s
WHERE s.status IN ('past_due', 'on_hold', 'paused')
ON CONFLICT (subscription_id, provider_event_at, status) DO NOTHING
"""


def _in_clause(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def upgrade() -> None:
    op.create_table(
        "subscription_status_history",
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
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("previous_status", sa.String(50), nullable=True),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(64), nullable=False),
        sa.Column("source", sa.String(24), nullable=False, server_default="billing"),
        sa.Column("provider_event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_event_id", sa.String(255), nullable=True),
        sa.Column("applied", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            _in_clause("event_type", EVENT_TYPES),
            name="ck_subscription_status_history_event_type",
        ),
        sa.CheckConstraint(
            _in_clause("source", SOURCES),
            name="ck_subscription_status_history_source",
        ),
        sa.UniqueConstraint(
            "subscription_id",
            "provider_event_at",
            "status",
            name="uq_subscription_status_history_transition",
        ),
    )
    op.create_index(
        "idx_subscription_status_history_subscription_effective",
        "subscription_status_history",
        ["subscription_id", "provider_event_at"],
    )
    op.create_index(
        "idx_subscription_status_history_user_effective",
        "subscription_status_history",
        ["user_id", "provider_event_at"],
    )
    op.create_index(
        "idx_subscription_status_history_effective_status",
        "subscription_status_history",
        ["provider_event_at", "status"],
    )
    op.create_index(
        "idx_subscription_status_history_plan_effective",
        "subscription_status_history",
        ["plan_id", "provider_event_at"],
    )
    op.execute(BACKFILL_SQL)
    op.execute(
        """
        CREATE FUNCTION latexy_subscription_status_history_append_only()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'subscription_status_history is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER subscription_status_history_append_only
        BEFORE UPDATE ON subscription_status_history
        FOR EACH ROW EXECUTE FUNCTION latexy_subscription_status_history_append_only()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS subscription_status_history_append_only ON subscription_status_history")
    op.execute("DROP FUNCTION IF EXISTS latexy_subscription_status_history_append_only()")
    op.drop_index(
        "idx_subscription_status_history_plan_effective",
        table_name="subscription_status_history",
    )
    op.drop_index(
        "idx_subscription_status_history_effective_status",
        table_name="subscription_status_history",
    )
    op.drop_index(
        "idx_subscription_status_history_user_effective",
        table_name="subscription_status_history",
    )
    op.drop_index(
        "idx_subscription_status_history_subscription_effective",
        table_name="subscription_status_history",
    )
    op.drop_table("subscription_status_history")
