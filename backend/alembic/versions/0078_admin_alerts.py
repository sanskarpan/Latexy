"""Admin alert strip: durable, deduplicated operational alerts.

The table keeps one active row per dedupe key. A resolved incident may create a
new row if the same condition returns later, preserving history.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0078_admin_alerts"
down_revision = "0077_admin_control_room"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("owner", sa.String(32), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("dedupe_key", sa.String(200), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("runbook_url", sa.Text(), nullable=True),
        sa.Column("state", sa.String(16), nullable=False, server_default="open"),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("acknowledged_by", sa.String(36), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledgement_note", sa.Text(), nullable=True),
        sa.Column("snoozed_by", sa.String(36), nullable=True),
        sa.Column("snoozed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snooze_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "state IN ('open', 'acknowledged', 'snoozed', 'resolved')",
            name="ck_admin_alerts_state",
        ),
        sa.CheckConstraint(
            "severity IN ('critical', 'high', 'medium', 'low')",
            name="ck_admin_alerts_severity",
        ),
    )
    op.create_index(
        "idx_admin_alerts_state_severity",
        "admin_alerts",
        ["state", "severity", "last_seen_at"],
    )
    op.create_index("idx_admin_alerts_kind", "admin_alerts", ["kind"])
    op.create_index(
        "uq_admin_alerts_active_dedupe",
        "admin_alerts",
        ["dedupe_key"],
        unique=True,
        postgresql_where=sa.text("state IN ('open', 'acknowledged', 'snoozed')"),
    )


def downgrade() -> None:
    op.drop_index("uq_admin_alerts_active_dedupe", table_name="admin_alerts")
    op.drop_index("idx_admin_alerts_kind", table_name="admin_alerts")
    op.drop_index("idx_admin_alerts_state_severity", table_name="admin_alerts")
    op.drop_table("admin_alerts")
