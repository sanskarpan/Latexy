"""Aggregate error groups and rate-limited threshold alert state (#2166).

One row per ``(source, route, release, error_class)``. The row carries lifetime
occurrence counts for the admin feed, a rolling burst window used by the alert
threshold, and the last delivery timestamp used to rate-limit repeat alerts.

Privacy
-------
The table stores only a sanitized route template, a bounded release identifier,
a bounded error class, counters and timestamps. It never stores an exception
message, stack trace, source snippet, prompt, document content, email, token,
user id, IP address or user agent. Route/class values are sanitized again in the
service before they reach this table.

The migration is additive and reversible. It creates an empty table, so it is
safe to apply while the application is serving traffic.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0109_error_alerts"
down_revision = "0108_cohort_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_error_groups",
        sa.Column(
            "id",
            sa.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("route", sa.String(128), nullable=False),
        sa.Column("release", sa.String(64), nullable=False),
        sa.Column("error_class", sa.String(80), nullable=False),
        sa.Column(
            "occurrence_count",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "window_events",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "window_started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_alerted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "alert_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "source IN ('frontend', 'backend')",
            name="ck_admin_error_groups_source",
        ),
        sa.CheckConstraint(
            "occurrence_count >= 0 AND window_events >= 0 AND alert_count >= 0",
            name="ck_admin_error_groups_non_negative",
        ),
        sa.CheckConstraint(
            "length(trim(route)) > 0 AND length(trim(release)) > 0 "
            "AND length(trim(error_class)) > 0",
            name="ck_admin_error_groups_required_text",
        ),
        sa.UniqueConstraint(
            "source",
            "route",
            "release",
            "error_class",
            name="uq_admin_error_groups_key",
        ),
    )
    op.create_index(
        "idx_admin_error_groups_last_seen",
        "admin_error_groups",
        ["last_seen_at"],
    )
    op.create_index(
        "idx_admin_error_groups_source_last_seen",
        "admin_error_groups",
        ["source", "last_seen_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_admin_error_groups_source_last_seen",
        table_name="admin_error_groups",
    )
    op.drop_index("idx_admin_error_groups_last_seen", table_name="admin_error_groups")
    op.drop_table("admin_error_groups")
