"""Abuse-signal review queue and device whitelist state (issue #2131).

The queue aggregates existing persisted abuse signals into one human-review
row per opaque subject and signal bucket. It never stores a raw device
fingerprint, IP address, account identifier, email, document or provider
payload: ``subject_key`` is an MD5 computed inside PostgreSQL from the source
column, and evidence is limited to numeric aggregates and allowlisted labels.

Enforcement is never automatic. A row may be acknowledged or dismissed by one
reviewer, while block/unblock/whitelist require a second admin through the
existing ``admin_approvals`` workflow. ``device_trials.whitelisted`` is the
only behaviour change outside the new table: a whitelisted device is exempt
from automatic trial blocking and the usage ceiling.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0103_abuse_review"
down_revision = "0102_admin_user_notes"
branch_labels = None
depends_on = None

SIGNAL_TYPES = (
    "blocked_device",
    "trial_limit_reached",
    "repeat_ip_cluster",
    "trial_velocity",
    "payment_failure",
    "referral_rejection",
    "coupon_reuse",
    "rate_limit_pressure",
)
SUBJECT_TYPES = ("device", "ip", "account", "reason", "coupon")
SEVERITIES = ("low", "medium", "high", "critical")
STATUSES = ("open", "approved", "dismissed", "actioned")
DECISIONS = ("approve", "dismiss", "action")
ENFORCEMENT_ACTIONS = ("block", "unblock", "whitelist")
APPROVAL_TYPES = (
    "refund",
    "account_deletion",
    "impersonation",
    "role_escalation",
    "bulk_entitlement_change",
    "abuse_review_action",
)


def _in_clause(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def upgrade() -> None:
    op.add_column(
        "device_trials",
        sa.Column(
            "whitelisted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    op.drop_constraint(
        "ck_admin_approvals_request_type", "admin_approvals", type_="check"
    )
    op.create_check_constraint(
        "ck_admin_approvals_request_type",
        "admin_approvals",
        _in_clause("request_type", APPROVAL_TYPES),
    )

    op.create_table(
        "abuse_review_items",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("signal_type", sa.String(32), nullable=False),
        sa.Column("subject_type", sa.String(16), nullable=False),
        sa.Column("subject_key", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("dedupe_key", sa.String(160), nullable=False),
        sa.Column(
            "occurrence_count", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column("window_days", sa.Integer(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "evidence",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "evidence_links",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("assigned_to", sa.String(36), nullable=True),
        sa.Column("assigned_by", sa.String(36), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision", sa.String(16), nullable=True),
        sa.Column("decided_by", sa.String(36), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("enforcement_action", sa.String(16), nullable=True),
        sa.Column(
            "approval_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("admin_approvals.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "execution_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("last_executed_at", sa.DateTime(timezone=True), nullable=True),
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
            _in_clause("signal_type", SIGNAL_TYPES),
            name="ck_abuse_review_signal_type",
        ),
        sa.CheckConstraint(
            _in_clause("subject_type", SUBJECT_TYPES),
            name="ck_abuse_review_subject_type",
        ),
        sa.CheckConstraint(
            _in_clause("severity", SEVERITIES),
            name="ck_abuse_review_severity",
        ),
        sa.CheckConstraint(
            _in_clause("status", STATUSES),
            name="ck_abuse_review_status",
        ),
        sa.CheckConstraint(
            "decision IS NULL OR " + _in_clause("decision", DECISIONS),
            name="ck_abuse_review_decision",
        ),
        sa.CheckConstraint(
            "enforcement_action IS NULL OR "
            + _in_clause("enforcement_action", ENFORCEMENT_ACTIONS),
            name="ck_abuse_review_enforcement_action",
        ),
        sa.CheckConstraint(
            "occurrence_count > 0",
            name="ck_abuse_review_occurrences",
        ),
        sa.CheckConstraint(
            "execution_count >= 0",
            name="ck_abuse_review_execution_count",
        ),
        sa.CheckConstraint(
            "status = 'open' OR (decision IS NOT NULL AND decided_by IS NOT NULL "
            "AND decided_at IS NOT NULL)",
            name="ck_abuse_review_decided",
        ),
        sa.CheckConstraint(
            "status <> 'approved' OR decision = 'approve'",
            name="ck_abuse_review_approved",
        ),
        sa.CheckConstraint(
            "status <> 'dismissed' OR decision = 'dismiss'",
            name="ck_abuse_review_dismissed",
        ),
        sa.CheckConstraint(
            "status <> 'actioned' OR (decision = 'action' "
            "AND enforcement_action IS NOT NULL AND approval_id IS NOT NULL "
            "AND execution_count > 0)",
            name="ck_abuse_review_actioned",
        ),
        sa.CheckConstraint(
            "assigned_to IS NULL OR length(assigned_to) = 36",
            name="ck_abuse_review_assignee",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evidence) = 'object'",
            name="ck_abuse_review_evidence_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evidence_links) = 'array'",
            name="ck_abuse_review_links_array",
        ),
        sa.UniqueConstraint("dedupe_key", name="uq_abuse_review_dedupe"),
    )
    op.create_index(
        "idx_abuse_review_status_severity",
        "abuse_review_items",
        ["status", "severity", "last_seen_at"],
    )
    op.create_index(
        "idx_abuse_review_signal_last_seen",
        "abuse_review_items",
        ["signal_type", "last_seen_at"],
    )
    op.create_index(
        "idx_abuse_review_assignee_status",
        "abuse_review_items",
        ["assigned_to", "status"],
    )
    op.create_index(
        "idx_abuse_review_approval",
        "abuse_review_items",
        ["approval_id"],
    )

    op.execute(
        """
        CREATE FUNCTION latexy_abuse_review_guard()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'abuse_review_items rows cannot be deleted';
            END IF;
            IF NEW.signal_type IS DISTINCT FROM OLD.signal_type
                OR NEW.subject_type IS DISTINCT FROM OLD.subject_type
                OR NEW.subject_key IS DISTINCT FROM OLD.subject_key
                OR NEW.dedupe_key IS DISTINCT FROM OLD.dedupe_key
                OR NEW.first_seen_at IS DISTINCT FROM OLD.first_seen_at
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
            THEN
                RAISE EXCEPTION 'abuse_review_items identity is immutable';
            END IF;
            IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
                (OLD.status = 'open' AND NEW.status IN ('approved', 'dismissed', 'actioned'))
                OR (OLD.status = 'approved' AND NEW.status IN ('dismissed', 'actioned'))
            ) THEN
                RAISE EXCEPTION 'invalid abuse_review_items status transition';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER abuse_review_items_guard
        BEFORE UPDATE OR DELETE ON abuse_review_items
        FOR EACH ROW EXECUTE FUNCTION latexy_abuse_review_guard()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS abuse_review_items_guard ON abuse_review_items")
    op.execute("DROP FUNCTION IF EXISTS latexy_abuse_review_guard()")
    op.drop_index("idx_abuse_review_approval", table_name="abuse_review_items")
    op.drop_index("idx_abuse_review_assignee_status", table_name="abuse_review_items")
    op.drop_index("idx_abuse_review_signal_last_seen", table_name="abuse_review_items")
    op.drop_index("idx_abuse_review_status_severity", table_name="abuse_review_items")
    op.drop_table("abuse_review_items")

    op.drop_constraint(
        "ck_admin_approvals_request_type", "admin_approvals", type_="check"
    )
    op.create_check_constraint(
        "ck_admin_approvals_request_type",
        "admin_approvals",
        _in_clause(
            "request_type",
            (
                "refund",
                "account_deletion",
                "impersonation",
                "role_escalation",
                "bulk_entitlement_change",
            ),
        ),
    )
    op.drop_column("device_trials", "whitelisted")
