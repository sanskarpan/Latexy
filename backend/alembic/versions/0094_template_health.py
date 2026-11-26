"""Persist append-only template verification evidence.

Template popularity and compile aggregates are already derived from
``compilations``, ``resumes`` and ``usage_analytics``.  This migration adds the
one piece those tables cannot own: the latest operator/CI verification of a
catalog template's rendered assets, compile contract and visual check.

Rows are deliberately evidence snapshots, not a second copy of template
source.  They store only allowlisted status/error-class values, an optional
validated commit SHA or CI run id, aggregate compile counts and a bounded
status detail.  Template source, document content, logs and provider
credentials are never written here.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0094_template_health"
down_revision = "0093_admin_saved_views"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "template_health_checks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "template_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("resume_templates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="unknown"),
        sa.Column("error_class", sa.String(length=32), nullable=True),
        sa.Column("visual_test", sa.String(length=16), nullable=False, server_default="unknown"),
        sa.Column("commit_sha", sa.String(length=40), nullable=True),
        sa.Column("ci_run_id", sa.String(length=32), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="admin_retry"),
        sa.Column("assets_present", sa.Boolean(), nullable=True),
        sa.Column("compile_samples", sa.Integer(), nullable=True),
        sa.Column("compile_failures", sa.Integer(), nullable=True),
        sa.Column("status_detail", sa.String(length=240), nullable=True),
        sa.Column("idempotency_key", sa.String(length=120), nullable=True),
        sa.Column(
            "checked_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('pass', 'fail', 'unknown')",
            name="ck_template_health_checks_status",
        ),
        sa.CheckConstraint(
            "visual_test IN ('pass', 'fail', 'unknown')",
            name="ck_template_health_checks_visual_test",
        ),
        sa.CheckConstraint(
            "error_class IS NULL OR error_class IN "
            "('missing_asset', 'compile_error', 'syntax', 'missing_package', "
            "'timeout', 'engine', 'storage', 'pdf_limit', 'visual_regression', 'unknown')",
            name="ck_template_health_checks_error_class",
        ),
        sa.CheckConstraint(
            "source IN ('admin_retry', 'compile_batch', 'ci', 'backfill')",
            name="ck_template_health_checks_source",
        ),
        sa.CheckConstraint(
            "commit_sha IS NULL OR commit_sha ~ '^[0-9a-f]{40}$'",
            name="ck_template_health_checks_commit_sha",
        ),
        sa.CheckConstraint(
            "ci_run_id IS NULL OR ci_run_id ~ '^[0-9]{1,32}$'",
            name="ck_template_health_checks_ci_run_id",
        ),
        sa.CheckConstraint(
            "compile_samples IS NULL OR compile_samples >= 0",
            name="ck_template_health_checks_compile_samples",
        ),
        sa.CheckConstraint(
            "compile_failures IS NULL OR compile_failures >= 0",
            name="ck_template_health_checks_compile_failures",
        ),
        sa.CheckConstraint(
            "compile_samples IS NULL OR compile_failures IS NULL "
            "OR compile_failures <= compile_samples",
            name="ck_template_health_checks_compile_failures_bounded",
        ),
        sa.UniqueConstraint(
            "template_id",
            "idempotency_key",
            name="uq_template_health_checks_template_idempotency",
        ),
    )
    op.create_index(
        "ix_template_health_checks_template_checked",
        "template_health_checks",
        ["template_id", sa.text("checked_at DESC")],
    )
    op.create_index(
        "ix_template_health_checks_checked",
        "template_health_checks",
        ["checked_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_template_health_checks_checked", table_name="template_health_checks")
    op.drop_index(
        "ix_template_health_checks_template_checked",
        table_name="template_health_checks",
    )
    op.drop_table("template_health_checks")
