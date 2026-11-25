"""GDPR data-subject request queue, append-only transitions and legal holds.

``gdpr_requests`` is the mutable queue row (status/timestamps). Every
transition is appended to ``gdpr_request_events``, which rejects UPDATE and
DELETE at the database layer. Deleting a request row is also rejected so the
audit trail cannot be erased through the ORM.

``gdpr_legal_holds`` records counsel/ops holds that block a deletion job until
explicitly released. Financial records (payments, subscriptions, refunds,
billing webhooks) and the append-only admin audit log are deliberately never
deleted by the erasure job; the API reports them as retention exceptions.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0083_gdpr_requests"
down_revision = "0082_signup_funnel_providers"
branch_labels = None
depends_on = None

REQUEST_TYPES = ("export", "deletion")
REQUEST_STATUSES = (
    "pending",
    "legal_review",
    "approved",
    "processing",
    "ready",
    "completed",
    "failed",
    "rejected",
    "cancelled",
    "blocked",
    "expired",
)
LEGAL_REVIEW_STATUSES = ("not_required", "pending", "approved", "rejected")
EVENT_ACTOR_TYPES = ("user", "admin", "system")


def _in_clause(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def upgrade() -> None:
    op.create_table(
        "gdpr_requests",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("request_type", sa.String(16), nullable=False),
        sa.Column(
            "status",
            sa.String(24),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "legal_review_status",
            sa.String(16),
            nullable=False,
            server_default="not_required",
        ),
        sa.Column("identity_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reauthenticated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("legal_reviewed_by", sa.String(36), nullable=True),
        sa.Column("legal_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("legal_review_note", sa.Text(), nullable=True),
        sa.Column(
            "legal_hold_blocked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("export_token_hash", sa.String(64), nullable=True),
        sa.Column("export_issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("export_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("export_downloaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("export_sha256", sa.String(64), nullable=True),
        sa.Column("export_size_bytes", sa.Integer(), nullable=True),
        sa.Column("failure_code", sa.String(64), nullable=True),
        sa.Column("failure_detail", sa.Text(), nullable=True),
        sa.Column(
            "table_results",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "retention_exceptions",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "attempts",
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
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            _in_clause("request_type", REQUEST_TYPES),
            name="ck_gdpr_requests_type",
        ),
        sa.CheckConstraint(
            _in_clause("status", REQUEST_STATUSES),
            name="ck_gdpr_requests_status",
        ),
        sa.CheckConstraint(
            _in_clause("legal_review_status", LEGAL_REVIEW_STATUSES),
            name="ck_gdpr_requests_legal_review_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_gdpr_requests_attempts"),
        sa.CheckConstraint(
            "export_size_bytes IS NULL OR export_size_bytes >= 0",
            name="ck_gdpr_requests_export_size",
        ),
    )
    op.create_index(
        "idx_gdpr_requests_user_created",
        "gdpr_requests",
        ["user_id", "created_at"],
    )
    op.create_index(
        "idx_gdpr_requests_status_created",
        "gdpr_requests",
        ["status", "created_at"],
    )
    op.create_index(
        "idx_gdpr_requests_type_status",
        "gdpr_requests",
        ["request_type", "status"],
    )
    op.create_index(
        "idx_gdpr_requests_export_expiry",
        "gdpr_requests",
        ["export_expires_at"],
    )

    op.create_table(
        "gdpr_request_events",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "request_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("gdpr_requests.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("event", sa.String(64), nullable=False),
        sa.Column("actor_type", sa.String(16), nullable=False),
        sa.Column("actor_user_id", sa.String(36), nullable=True),
        sa.Column("from_status", sa.String(24), nullable=True),
        sa.Column("to_status", sa.String(24), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "event_metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            _in_clause("actor_type", EVENT_ACTOR_TYPES),
            name="ck_gdpr_request_events_actor_type",
        ),
    )
    op.create_index(
        "idx_gdpr_request_events_request_created",
        "gdpr_request_events",
        ["request_id", "created_at"],
    )
    op.create_index(
        "idx_gdpr_request_events_actor_created",
        "gdpr_request_events",
        ["actor_user_id", "created_at"],
    )

    op.create_table(
        "gdpr_legal_holds",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("placed_by", sa.String(36), nullable=False),
        sa.Column("placed_email", sa.String(255), nullable=True),
        sa.Column(
            "placed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("released_by", sa.String(36), nullable=True),
        sa.Column("released_email", sa.String(255), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("release_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "active OR released_at IS NOT NULL",
            name="ck_gdpr_legal_holds_released",
        ),
    )
    op.create_index(
        "idx_gdpr_legal_holds_user_active",
        "gdpr_legal_holds",
        ["user_id", "active"],
    )
    op.create_index(
        "uq_gdpr_legal_holds_active_user",
        "gdpr_legal_holds",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("active"),
    )

    # Transitions are history, not a mutable cache. A bug or compromised ORM
    # session must not be able to rewrite or erase what an operator did.
    op.execute(
        """
        CREATE FUNCTION latexy_gdpr_events_append_only()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'gdpr_request_events is append-only';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER gdpr_request_events_append_only
        BEFORE UPDATE OR DELETE ON gdpr_request_events
        FOR EACH ROW EXECUTE FUNCTION latexy_gdpr_events_append_only();
        """
    )
    op.execute(
        """
        CREATE FUNCTION latexy_gdpr_requests_no_delete()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'gdpr_requests rows are retained for audit';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER gdpr_requests_no_delete
        BEFORE DELETE ON gdpr_requests
        FOR EACH ROW EXECUTE FUNCTION latexy_gdpr_requests_no_delete();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS gdpr_requests_no_delete ON gdpr_requests")
    op.execute("DROP FUNCTION IF EXISTS latexy_gdpr_requests_no_delete()")
    op.execute("DROP TRIGGER IF EXISTS gdpr_request_events_append_only ON gdpr_request_events")
    op.execute("DROP FUNCTION IF EXISTS latexy_gdpr_events_append_only()")
    op.drop_index("uq_gdpr_legal_holds_active_user", table_name="gdpr_legal_holds")
    op.drop_index("idx_gdpr_legal_holds_user_active", table_name="gdpr_legal_holds")
    op.drop_table("gdpr_legal_holds")
    op.drop_index("idx_gdpr_request_events_actor_created", table_name="gdpr_request_events")
    op.drop_index("idx_gdpr_request_events_request_created", table_name="gdpr_request_events")
    op.drop_table("gdpr_request_events")
    op.drop_index("idx_gdpr_requests_export_expiry", table_name="gdpr_requests")
    op.drop_index("idx_gdpr_requests_type_status", table_name="gdpr_requests")
    op.drop_index("idx_gdpr_requests_status_created", table_name="gdpr_requests")
    op.drop_index("idx_gdpr_requests_user_created", table_name="gdpr_requests")
    op.drop_table("gdpr_requests")
