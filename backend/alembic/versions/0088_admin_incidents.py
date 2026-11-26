"""Operational incident timeline for the admin control plane.

``admin_incidents`` is an operator-owned record of an incident: when it began,
when it ended, its severity, the affected services, a short summary, an owner,
and supporting links. Rows are deliberately free of customer identifiers,
document content, provider credentials and raw provider errors. Every write is
performed by an admin and mirrored into the append-only ``admin_audit_log`` by
the service layer.

``deploy_sha``/``deploy_url`` are optional deploy markers so a timeline entry
can be correlated with a release when a deployment identity is available.
``related_alert_keys`` stores bounded admin-alert dedupe keys, not alert
payloads, so an incident can be correlated with the durable alert strip without
copying provider data.

The status/end-time invariant is enforced by the database: an open incident has
no end timestamp, and a resolved incident always has one.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0088_admin_incidents"
down_revision = "0086_trial_attribution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_incidents",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "services",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("owner", sa.String(64), nullable=False),
        sa.Column(
            "links",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "related_alert_keys",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("deploy_sha", sa.String(40), nullable=True),
        sa.Column("deploy_url", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("updated_by", sa.String(36), nullable=True),
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
            "status IN ('open', 'resolved')",
            name="ck_admin_incidents_status",
        ),
        sa.CheckConstraint(
            "severity IN ('critical', 'high', 'medium', 'low')",
            name="ck_admin_incidents_severity",
        ),
        sa.CheckConstraint(
            "(status = 'open' AND ended_at IS NULL) OR "
            "(status = 'resolved' AND ended_at IS NOT NULL)",
            name="ck_admin_incidents_state_end",
        ),
        sa.CheckConstraint(
            "ended_at IS NULL OR ended_at >= started_at",
            name="ck_admin_incidents_time_order",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(services) = 'array' AND jsonb_array_length(services) > 0",
            name="ck_admin_incidents_services",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(links) = 'array'",
            name="ck_admin_incidents_links",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(related_alert_keys) = 'array'",
            name="ck_admin_incidents_alert_keys",
        ),
        sa.CheckConstraint(
            "deploy_sha IS NULL OR deploy_sha ~ '^[0-9a-f]{7,40}$'",
            name="ck_admin_incidents_deploy_sha",
        ),
        sa.CheckConstraint(
            "length(trim(title)) > 0 AND length(trim(summary)) > 0 "
            "AND length(trim(owner)) > 0",
            name="ck_admin_incidents_required_text",
        ),
    )
    op.create_index(
        "idx_admin_incidents_status_started",
        "admin_incidents",
        ["status", "started_at"],
    )
    op.create_index(
        "idx_admin_incidents_severity_started",
        "admin_incidents",
        ["severity", "started_at"],
    )
    op.create_index(
        "idx_admin_incidents_started",
        "admin_incidents",
        ["started_at"],
    )
    op.create_index(
        "idx_admin_incidents_services",
        "admin_incidents",
        ["services"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("idx_admin_incidents_services", table_name="admin_incidents")
    op.drop_index("idx_admin_incidents_started", table_name="admin_incidents")
    op.drop_index("idx_admin_incidents_severity_started", table_name="admin_incidents")
    op.drop_index("idx_admin_incidents_status_started", table_name="admin_incidents")
    op.drop_table("admin_incidents")
