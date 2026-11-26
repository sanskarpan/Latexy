"""Versioned data-retention policies, bounded runs and immutable policy history.

Retention policy changes are stored as append-only revisions so an operator can
always reconstruct the configured window and schedule that applied at a given
time. Every run is persisted with the cutoff, configured/effective retention,
bounded counts and protection reasons; a partial unique index guarantees at most
one running job per data class.

The seeded windows are safety defaults, not automatic deletion orders: purges
remain explicit, reason-bearing, confirmed admin actions. The append-only
``admin_audit_log`` is seeded as an immutable class and can be previewed but not
deleted through this surface.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0096_retention_controls"
down_revision = "0092_document_complexity"
branch_labels = None
depends_on = None

DATA_CLASSES = ("pdfs", "job_finalizations", "analytics", "audit", "exports")
RUN_MODES = ("dry_run", "purge")
RUN_STATUSES = ("running", "completed", "refused", "failed")

DEFAULT_POLICIES = (
    ("pdfs", 24, 24, True),
    ("job_finalizations", 24, 24, True),
    ("analytics", 8760, 168, True),
    ("audit", 61320, 168, True),
    ("exports", 720, 24, True),
)


def _in_clause(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def upgrade() -> None:
    op.create_table(
        "retention_policies",
        sa.Column("data_class", sa.String(32), primary_key=True),
        sa.Column("configured_hours", sa.Integer(), nullable=False),
        sa.Column("schedule_hours", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            _in_clause("data_class", DATA_CLASSES),
            name="ck_retention_policies_data_class",
        ),
        sa.CheckConstraint(
            "configured_hours BETWEEN 1 AND 87600",
            name="ck_retention_policies_configured_hours",
        ),
        sa.CheckConstraint(
            "schedule_hours BETWEEN 1 AND 8760",
            name="ck_retention_policies_schedule_hours",
        ),
        sa.CheckConstraint("version >= 1", name="ck_retention_policies_version"),
    )

    op.create_table(
        "retention_policy_revisions",
        sa.Column(
            "data_class",
            sa.String(32),
            sa.ForeignKey("retention_policies.data_class", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("changed_by", sa.String(36), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("version >= 1", name="ck_retention_policy_revisions_version"),
    )

    op.create_table(
        "retention_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
        ),
        sa.Column(
            "data_class",
            sa.String(32),
            sa.ForeignKey("retention_policies.data_class", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("retention_hours", sa.Integer(), nullable=False),
        sa.Column("effective_hours", sa.Integer(), nullable=False),
        sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scanned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("eligible", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("protected_active_jobs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("protected_legal_hold", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("protected_immutable", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("affected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("batch_limit", sa.Integer(), nullable=False, server_default="200"),
        sa.Column("has_more", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("started_by", sa.String(36), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("detail", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            _in_clause("data_class", DATA_CLASSES),
            name="ck_retention_runs_data_class",
        ),
        sa.CheckConstraint(_in_clause("mode", RUN_MODES), name="ck_retention_runs_mode"),
        sa.CheckConstraint(
            _in_clause("status", RUN_STATUSES),
            name="ck_retention_runs_status",
        ),
        sa.CheckConstraint("batch_limit BETWEEN 1 AND 1000", name="ck_retention_runs_batch_limit"),
        sa.CheckConstraint(
            "scanned >= 0 AND eligible >= 0 AND affected >= 0",
            name="ck_retention_runs_counts",
        ),
    )
    op.create_index(
        "idx_retention_runs_class_started",
        "retention_runs",
        ["data_class", "started_at"],
    )
    # One in-flight run per class. A second admin cannot start a purge or
    # dry-run while the first transaction still holds the class.
    op.create_index(
        "uq_retention_runs_active_class",
        "retention_runs",
        ["data_class"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )
    # Idempotent replay: the same caller key returns the first run instead of
    # repeating a destructive operation.
    op.create_index(
        "uq_retention_runs_idempotency",
        "retention_runs",
        ["data_class", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    # Policy revisions are evidence: reject UPDATE and DELETE at the database
    # layer even if an ORM session or future maintenance script tries.
    op.execute(
        """
        CREATE FUNCTION latexy_retention_revisions_append_only()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'retention_policy_revisions is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER retention_policy_revisions_append_only
        BEFORE UPDATE OR DELETE ON retention_policy_revisions
        FOR EACH ROW EXECUTE FUNCTION latexy_retention_revisions_append_only()
        """
    )

    values = ", ".join(
        f"('{data_class}', {configured}, {schedule}, "
        f"{'true' if enabled else 'false'}, 1, 'Initial retention policy')"
        for data_class, configured, schedule, enabled in DEFAULT_POLICIES
    )
    op.execute(
        f"""
        INSERT INTO retention_policies
            (data_class, configured_hours, schedule_hours, enabled, version, change_reason)
        VALUES {values}
        ON CONFLICT (data_class) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO retention_policy_revisions
            (data_class, version, snapshot, changed_by, reason)
        SELECT data_class, version,
               jsonb_build_object(
                   'data_class', data_class,
                   'configured_hours', configured_hours,
                   'schedule_hours', schedule_hours,
                   'enabled', enabled,
                   'version', version
               ),
               'system', 'Initial retention policy'
        FROM retention_policies
        ON CONFLICT (data_class, version) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS retention_policy_revisions_append_only "
        "ON retention_policy_revisions"
    )
    op.execute("DROP FUNCTION IF EXISTS latexy_retention_revisions_append_only()")
    op.drop_index("uq_retention_runs_idempotency", table_name="retention_runs")
    op.drop_index("uq_retention_runs_active_class", table_name="retention_runs")
    op.drop_index("idx_retention_runs_class_started", table_name="retention_runs")
    op.drop_table("retention_runs")
    op.drop_table("retention_policy_revisions")
    op.drop_table("retention_policies")
