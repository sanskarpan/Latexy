"""Pre-registered A/B experiments with first-party assignment and exposure.

The registry stores exactly one primary metric, one or two guardrails and a
bounded variant list. The hypothesis, metric selection, variants, feature-flag
link, minimum sample and PostHog insight link are frozen at registration time
by ``latexy_admin_experiments_guard``; only the lifecycle columns may change.
This makes a later results read evidence about the pre-registered analysis, not
a retrospective edit.

Assignments are one row per experiment and account so a subject cannot drift
between variants. Exposures are one row per experiment, account and UTC day, so
a retry or a remount cannot inflate the sample. Neither table stores email,
name, document text, prompt, token, IP address, user agent or provider payload.

The migration is additive and reversible. It writes no seed rows and reads no
customer data, so it is safe to apply while the application is serving traffic.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0106_admin_experiments"
down_revision = "0104_refund_requests"
branch_labels = None
depends_on = None

PRIMARY_METRICS = (
    "activation",
    "compile_success",
    "checkout_started",
    "retention_7d",
)
GUARDRAIL_METRICS = (
    "compile_error_rate",
    "checkout_abandonment_rate",
)
STATUSES = ("preregistered", "running", "stopped")
OPERATIONAL_FLAGS = (
    "trial_limits",
    "deep_analysis_trial",
    "compile_timeouts",
    "task_priority",
    "billing",
    "upgrade_ctas",
)
EXPERIMENT_SOURCE = "first_party_experiment_evaluation"


def _in_clause(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def upgrade() -> None:
    op.create_table(
        "admin_experiments",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("experiment_key", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("hypothesis", sa.Text(), nullable=False),
        sa.Column("primary_metric", sa.String(40), nullable=False),
        sa.Column(
            "guardrail_metrics",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "variants",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("flag_key", sa.String(100), nullable=True),
        sa.Column("posthog_insight_url", sa.String(500), nullable=True),
        sa.Column("minimum_sample_per_variant", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="preregistered",
        ),
        sa.Column("registration_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("started_by", sa.String(36), nullable=True),
        sa.Column("stopped_by", sa.String(36), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stop_reason", sa.Text(), nullable=True),
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
            "experiment_key ~ '^[a-z][a-z0-9_]{1,63}$'",
            name="ck_admin_experiments_key",
        ),
        sa.CheckConstraint(
            "length(trim(name)) BETWEEN 1 AND 160",
            name="ck_admin_experiments_name",
        ),
        sa.CheckConstraint(
            "length(trim(hypothesis)) BETWEEN 20 AND 4000",
            name="ck_admin_experiments_hypothesis",
        ),
        sa.CheckConstraint(
            _in_clause("primary_metric", PRIMARY_METRICS),
            name="ck_admin_experiments_primary_metric",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(guardrail_metrics) = 'array' "
            "AND jsonb_array_length(guardrail_metrics) BETWEEN 1 AND 2",
            name="ck_admin_experiments_guardrails",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(variants) = 'array' "
            "AND jsonb_array_length(variants) BETWEEN 2 AND 4",
            name="ck_admin_experiments_variants",
        ),
        sa.CheckConstraint(
            "flag_key IS NULL OR " + _in_clause("flag_key", OPERATIONAL_FLAGS),
            name="ck_admin_experiments_flag_key",
        ),
        sa.CheckConstraint(
            "posthog_insight_url IS NULL OR posthog_insight_url ~ "
            "'^https://(app|us|eu)[.]posthog[.]com/[A-Za-z0-9._~:/@!$&()*+,;=%-]*$'",
            name="ck_admin_experiments_posthog_url",
        ),
        sa.CheckConstraint(
            "minimum_sample_per_variant BETWEEN 5 AND 1000000",
            name="ck_admin_experiments_minimum_sample",
        ),
        sa.CheckConstraint(
            _in_clause("status", STATUSES),
            name="ck_admin_experiments_status",
        ),
        sa.CheckConstraint(
            "registration_hash ~ '^[0-9a-f]{64}$'",
            name="ck_admin_experiments_registration_hash",
        ),
        sa.CheckConstraint(
            "status = 'preregistered' OR started_at IS NOT NULL",
            name="ck_admin_experiments_started",
        ),
        sa.CheckConstraint(
            "status <> 'stopped' OR (stopped_at IS NOT NULL AND stop_reason IS NOT NULL)",
            name="ck_admin_experiments_stopped",
        ),
    )
    op.create_index(
        "idx_admin_experiments_status_created",
        "admin_experiments",
        ["status", "created_at"],
    )

    op.create_table(
        "admin_experiment_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "experiment_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("admin_experiments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("variant", sa.String(32), nullable=False),
        sa.Column("bucket", sa.Integer(), nullable=False),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "variant ~ '^[a-z][a-z0-9_]{0,31}$'",
            name="ck_admin_experiment_assignments_variant",
        ),
        sa.CheckConstraint(
            "bucket BETWEEN 0 AND 99",
            name="ck_admin_experiment_assignments_bucket",
        ),
        sa.UniqueConstraint(
            "experiment_id",
            "user_id",
            name="uq_admin_experiment_assignments_subject",
        ),
    )
    op.create_index(
        "idx_admin_experiment_assignments_experiment_variant",
        "admin_experiment_assignments",
        ["experiment_id", "variant"],
    )

    op.create_table(
        "admin_experiment_exposures",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "experiment_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("admin_experiments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "assignment_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("admin_experiment_assignments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("variant", sa.String(32), nullable=False),
        sa.Column("window_date", sa.Date(), nullable=False),
        sa.Column(
            "source",
            sa.String(40),
            nullable=False,
            server_default=EXPERIMENT_SOURCE,
        ),
        sa.Column(
            "exposed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "variant ~ '^[a-z][a-z0-9_]{0,31}$'",
            name="ck_admin_experiment_exposures_variant",
        ),
        sa.CheckConstraint(
            f"source = {EXPERIMENT_SOURCE!r}",
            name="ck_admin_experiment_exposures_source",
        ),
        sa.UniqueConstraint(
            "experiment_id",
            "user_id",
            "window_date",
            name="uq_admin_experiment_exposures_window",
        ),
    )
    op.create_index(
        "idx_admin_experiment_exposures_experiment_time",
        "admin_experiment_exposures",
        ["experiment_id", "exposed_at"],
    )
    op.create_index(
        "idx_admin_experiment_exposures_experiment_variant",
        "admin_experiment_exposures",
        ["experiment_id", "variant"],
    )

    op.execute(
        """
        CREATE FUNCTION latexy_admin_experiments_guard()
        RETURNS trigger AS $$
        BEGIN
            IF NEW.experiment_key <> OLD.experiment_key
                OR NEW.name <> OLD.name
                OR NEW.hypothesis <> OLD.hypothesis
                OR NEW.primary_metric <> OLD.primary_metric
                OR NEW.guardrail_metrics IS DISTINCT FROM OLD.guardrail_metrics
                OR NEW.variants IS DISTINCT FROM OLD.variants
                OR NEW.flag_key IS DISTINCT FROM OLD.flag_key
                OR NEW.posthog_insight_url IS DISTINCT FROM OLD.posthog_insight_url
                OR NEW.minimum_sample_per_variant <> OLD.minimum_sample_per_variant
                OR NEW.registration_hash <> OLD.registration_hash
                OR NEW.created_by <> OLD.created_by
                OR NEW.created_at <> OLD.created_at
            THEN
                RAISE EXCEPTION 'admin_experiments preregistration is immutable';
            END IF;
            IF NEW.status IS DISTINCT FROM OLD.status
                AND NOT (
                    (OLD.status = 'preregistered' AND NEW.status = 'running')
                    OR (OLD.status = 'running' AND NEW.status = 'stopped')
                )
            THEN
                RAISE EXCEPTION 'invalid admin_experiments status transition';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER admin_experiments_guard
        BEFORE UPDATE ON admin_experiments
        FOR EACH ROW EXECUTE FUNCTION latexy_admin_experiments_guard()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS admin_experiments_guard ON admin_experiments")
    op.execute("DROP FUNCTION IF EXISTS latexy_admin_experiments_guard()")
    op.drop_index(
        "idx_admin_experiment_exposures_experiment_variant",
        table_name="admin_experiment_exposures",
    )
    op.drop_index(
        "idx_admin_experiment_exposures_experiment_time",
        table_name="admin_experiment_exposures",
    )
    op.drop_table("admin_experiment_exposures")
    op.drop_index(
        "idx_admin_experiment_assignments_experiment_variant",
        table_name="admin_experiment_assignments",
    )
    op.drop_table("admin_experiment_assignments")
    op.drop_index(
        "idx_admin_experiments_status_created",
        table_name="admin_experiments",
    )
    op.drop_table("admin_experiments")
