"""Two-person approval records for sensitive administrative actions.

Refunds, account deletion, impersonation/view-as, role escalation and bulk
entitlement changes must be requested by one admin and approved by another.
This table stores only the canonical request payload hash and a small bounded
payload (identifiers, roles, feature keys and booleans). It never stores
documents, prompts, emails, provider payloads, tokens or raw request metadata.

Workflow state is mutable so a request can move from ``pending`` to a decision
and then to execution. The payload and requester fields are protected by a
trigger, deletes are rejected, and every transition is written to the
append-only ``admin_audit_log``.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0097_two_person_approvals"
down_revision = "0096_retention_controls"
branch_labels = None
depends_on = None

REQUEST_TYPES = (
    "refund",
    "account_deletion",
    "impersonation",
    "role_escalation",
    "bulk_entitlement_change",
)
STATUSES = (
    "pending",
    "approved",
    "rejected",
    "executing",
    "executed",
    "failed",
    "expired",
    "cancelled",
)


def _in_clause(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def upgrade() -> None:
    op.create_table(
        "admin_approvals",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("request_type", sa.String(32), nullable=False),
        sa.Column("resource_type", sa.String(32), nullable=True),
        sa.Column("resource_id", sa.String(255), nullable=True),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("requested_by", sa.String(36), nullable=False),
        sa.Column("approved_by", sa.String(36), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("execution_note", sa.Text(), nullable=True),
        sa.Column("executed_by", sa.String(36), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "audit_request_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("admin_audit_log.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "audit_decision_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("admin_audit_log.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "audit_execution_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("admin_audit_log.id", ondelete="RESTRICT"),
            nullable=True,
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
            _in_clause("request_type", REQUEST_TYPES),
            name="ck_admin_approvals_request_type",
        ),
        sa.CheckConstraint(
            _in_clause("status", STATUSES),
            name="ck_admin_approvals_status",
        ),
        sa.CheckConstraint(
            "payload_hash ~ '^[0-9a-f]{64}$'",
            name="ck_admin_approvals_payload_hash",
        ),
        sa.CheckConstraint(
            "expires_at > requested_at",
            name="ck_admin_approvals_expiry",
        ),
        sa.CheckConstraint(
            "approved_by IS NULL OR approved_by <> requested_by",
            name="ck_admin_approvals_separation_of_duties",
        ),
        sa.CheckConstraint(
            "status NOT IN ('approved', 'executing', 'executed') OR approved_by IS NOT NULL",
            name="ck_admin_approvals_approved_actor",
        ),
        sa.CheckConstraint(
            "status <> 'executed' OR executed_at IS NOT NULL",
            name="ck_admin_approvals_executed_at",
        ),
        sa.CheckConstraint(
            "status <> 'rejected' OR decided_at IS NOT NULL",
            name="ck_admin_approvals_rejected_at",
        ),
    )
    op.create_index(
        "idx_admin_approvals_status_requested",
        "admin_approvals",
        ["status", "requested_at"],
    )
    op.create_index(
        "idx_admin_approvals_request_type_requested",
        "admin_approvals",
        ["request_type", "requested_at"],
    )
    op.create_index(
        "idx_admin_approvals_requester_requested",
        "admin_approvals",
        ["requested_by", "requested_at"],
    )
    op.create_index(
        "idx_admin_approvals_expires",
        "admin_approvals",
        ["expires_at"],
    )
    op.create_index(
        "idx_admin_approvals_resource",
        "admin_approvals",
        ["resource_type", "resource_id"],
    )
    # Only one open approval may exist for a given action payload. Rejected,
    # expired, cancelled and executed rows are retained, so a new reviewer can
    # still authorize a fresh attempt without reusing the old decision.
    op.create_index(
        "uq_admin_approvals_open_payload",
        "admin_approvals",
        ["request_type", "payload_hash"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'approved', 'executing')"),
    )

    op.execute(
        """
        CREATE FUNCTION latexy_admin_approvals_guard()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'admin_approvals rows cannot be deleted';
            END IF;
            IF NEW.request_type <> OLD.request_type
                OR NEW.resource_type IS DISTINCT FROM OLD.resource_type
                OR NEW.resource_id IS DISTINCT FROM OLD.resource_id
                OR NEW.payload_hash <> OLD.payload_hash
                OR NEW.payload IS DISTINCT FROM OLD.payload
                OR NEW.reason <> OLD.reason
                OR NEW.requested_by <> OLD.requested_by
                OR NEW.requested_at <> OLD.requested_at
                OR NEW.expires_at <> OLD.expires_at
                OR (OLD.audit_request_id IS NOT NULL
                    AND NEW.audit_request_id IS DISTINCT FROM OLD.audit_request_id)
            THEN
                RAISE EXCEPTION 'admin_approvals request identity is immutable';
            END IF;
            IF NOT (
                NEW.status = OLD.status
                OR (OLD.status = 'pending' AND NEW.status IN ('approved', 'rejected', 'cancelled', 'expired'))
                OR (OLD.status = 'approved' AND NEW.status IN ('executing', 'executed', 'cancelled', 'expired'))
                OR (OLD.status = 'executing' AND NEW.status IN ('executed', 'failed'))
                OR (OLD.status = 'failed' AND NEW.status = 'executed')
            ) THEN
                RAISE EXCEPTION 'invalid admin_approvals status transition';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER admin_approvals_guard
        BEFORE UPDATE OR DELETE ON admin_approvals
        FOR EACH ROW EXECUTE FUNCTION latexy_admin_approvals_guard()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS admin_approvals_guard ON admin_approvals")
    op.execute("DROP FUNCTION IF EXISTS latexy_admin_approvals_guard()")
    op.drop_index("uq_admin_approvals_open_payload", table_name="admin_approvals")
    op.drop_index("idx_admin_approvals_resource", table_name="admin_approvals")
    op.drop_index("idx_admin_approvals_expires", table_name="admin_approvals")
    op.drop_index("idx_admin_approvals_requester_requested", table_name="admin_approvals")
    op.drop_index("idx_admin_approvals_request_type_requested", table_name="admin_approvals")
    op.drop_index("idx_admin_approvals_status_requested", table_name="admin_approvals")
    op.drop_table("admin_approvals")
