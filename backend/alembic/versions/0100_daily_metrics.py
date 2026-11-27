"""Daily aggregate rollup for admin analytics (issue #2181).

One row per UTC calendar day. Every column is a global count or minor-unit
amount derived from ``users``, ``compilations``, ``optimizations``,
``usage_analytics``, ``payments`` and ``payment_refunds``. The table never
stores user ids, emails, document content, prompts, tokens, IP addresses,
user agents or provider payloads.

``metric_date`` is the primary key, so a day can only exist once. The refresh
worker recomputes a bounded trailing window and applies ``ON CONFLICT DO
UPDATE``; a failed or overlapping refresh therefore leaves the previous
snapshot readable. ``refreshed_at`` records when the successful snapshot was
produced and backs the admin freshness/staleness decision.

The migration is additive and reversible. It reads no base rows and writes no
seed data, so it is safe to apply while the application is serving traffic.
"""

import sqlalchemy as sa

from alembic import op

revision = "0100_daily_metrics"
down_revision = "0099_tenant_domain_health"
branch_labels = None
depends_on = None

_NON_NEGATIVE_COUNTS = (
    "new_users >= 0",
    "active_users >= 0",
    "usage_events >= 0",
    "compilations >= 0",
    "completed_compilations >= 0",
    "failed_compilations >= 0",
    "optimizations >= 0",
    "payments_count >= 0",
    "gross_revenue_minor >= 0",
    "refunds_count >= 0",
    "refund_amount_minor >= 0",
)


def upgrade() -> None:
    op.create_table(
        "admin_daily_metrics",
        sa.Column("metric_date", sa.Date(), primary_key=True),
        sa.Column("new_users", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("active_users", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("usage_events", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("compilations", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "completed_compilations",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "failed_compilations",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("optimizations", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("payments_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "gross_revenue_minor",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("refunds_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "refund_amount_minor",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "refreshed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            " AND ".join(_NON_NEGATIVE_COUNTS),
            name="ck_admin_daily_metrics_nonnegative",
        ),
    )
    # The primary key already provides the unique date key and range scans;
    # this secondary index answers the freshness query directly.
    op.create_index(
        "idx_admin_daily_metrics_refreshed_at",
        "admin_daily_metrics",
        ["refreshed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_admin_daily_metrics_refreshed_at",
        table_name="admin_daily_metrics",
    )
    op.drop_table("admin_daily_metrics")
