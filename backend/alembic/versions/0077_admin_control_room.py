"""Admin control room: immutable audit log, refund approvals, webhook review.

The audit log is append-only at the database layer. Refund requests are a
separate approval workflow; no provider refund is issued from a pending row.
Webhook acknowledgement is deliberately independent of provider status so an
operator can clear a known provider-side event without pretending it was
locally processed.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0077_admin_control_room"
down_revision = "0076_spare_authority_handover"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("actor_user_id", sa.String(36), nullable=True),
        sa.Column("actor_email", sa.String(255), nullable=True),
        sa.Column("action", sa.String(120), nullable=False),
        sa.Column("target_type", sa.String(50), nullable=False),
        sa.Column("target_id", sa.String(255), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("request_id", sa.String(255), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("before", postgresql.JSONB(), nullable=True),
        sa.Column("after", postgresql.JSONB(), nullable=True),
        sa.Column("event_metadata", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_admin_audit_created", "admin_audit_log", ["created_at"]
    )
    op.create_index(
        "idx_admin_audit_actor", "admin_audit_log", ["actor_user_id", "created_at"]
    )
    op.create_index(
        "idx_admin_audit_target",
        "admin_audit_log",
        ["target_type", "target_id", "created_at"],
    )
    op.create_index(
        "idx_admin_audit_action", "admin_audit_log", ["action", "created_at"]
    )

    # Append-only at the storage layer: a bug or compromised ORM session must
    # not be able to rewrite history. Retention is handled by explicitly
    # reviewed operator maintenance, never by routine application code.
    op.execute(
        """
        CREATE FUNCTION latexy_admin_audit_append_only()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'admin_audit_log is append-only';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER admin_audit_log_append_only
        BEFORE UPDATE OR DELETE ON admin_audit_log
        FOR EACH ROW EXECUTE FUNCTION latexy_admin_audit_append_only();
        """
    )

    op.create_table(
        "admin_refund_requests",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "payment_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("payments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("amount", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("provider_item_id", sa.String(255), nullable=True),
        sa.Column("tax_inclusive", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.String(36), nullable=False),
        sa.Column("requested_email", sa.String(255), nullable=True),
        sa.Column("approved_by", sa.String(36), nullable=True),
        sa.Column("approved_email", sa.String(255), nullable=True),
        sa.Column("executed_by", sa.String(36), nullable=True),
        sa.Column("provider_refund_id", sa.String(255), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'executing', 'executed', 'failed', 'cancelled')",
            name="ck_admin_refund_status",
        ),
        sa.CheckConstraint(
            "amount IS NULL OR amount > 0", name="ck_admin_refund_amount"
        ),
    )
    op.create_index(
        "idx_admin_refund_status", "admin_refund_requests", ["status", "requested_at"]
    )
    op.create_index(
        "idx_admin_refund_payment", "admin_refund_requests", ["payment_id"]
    )
    # Only one open request per payment; settled/rejected rows remain as history.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_admin_refund_open_payment
        ON admin_refund_requests (payment_id)
        WHERE status IN ('pending', 'approved', 'executing')
        """
    )

    op.add_column(
        "billing_webhook_events",
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "billing_webhook_events",
        sa.Column("acknowledged_by", sa.String(36), nullable=True),
    )
    op.add_column(
        "billing_webhook_events",
        sa.Column("acknowledgement_note", sa.Text(), nullable=True),
    )
    op.add_column(
        "billing_webhook_events",
        sa.Column("reconcile_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "billing_webhook_events",
        sa.Column("last_reconcile_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "billing_webhook_events",
        sa.Column("last_reconcile_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "billing_webhook_events",
        sa.Column("last_reconcile_outcome", sa.String(32), nullable=True),
    )
    op.create_index(
        "idx_billing_webhook_status_received",
        "billing_webhook_events",
        ["status", "received_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_billing_webhook_status_received", table_name="billing_webhook_events"
    )
    op.drop_column("billing_webhook_events", "last_reconcile_outcome")
    op.drop_column("billing_webhook_events", "last_reconcile_error")
    op.drop_column("billing_webhook_events", "last_reconcile_at")
    op.drop_column("billing_webhook_events", "reconcile_attempts")
    op.drop_column("billing_webhook_events", "acknowledgement_note")
    op.drop_column("billing_webhook_events", "acknowledged_by")
    op.drop_column("billing_webhook_events", "acknowledged_at")
    op.execute("DROP INDEX IF EXISTS uq_admin_refund_open_payment")
    op.drop_index("idx_admin_refund_payment", table_name="admin_refund_requests")
    op.drop_index("idx_admin_refund_status", table_name="admin_refund_requests")
    op.drop_table("admin_refund_requests")
    op.execute("DROP TRIGGER IF EXISTS admin_audit_log_append_only ON admin_audit_log")
    op.execute("DROP FUNCTION IF EXISTS latexy_admin_audit_append_only()")
    op.drop_index("idx_admin_audit_action", table_name="admin_audit_log")
    op.drop_index("idx_admin_audit_target", table_name="admin_audit_log")
    op.drop_index("idx_admin_audit_actor", table_name="admin_audit_log")
    op.drop_index("idx_admin_audit_created", table_name="admin_audit_log")
    op.drop_table("admin_audit_log")
