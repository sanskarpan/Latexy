"""Append-only LLM call attempt telemetry for latency and retry analytics.

Every row is one provider attempt (not one user or document). Only bounded,
low-cardinality dimensions are persisted: provider, model, feature, plan, an
opaque run reference, attempt number, normalized outcome/error class, retry
reason and latency. Prompts, document/LaTeX content, job descriptions, raw
provider errors, API keys and user identifiers are never written here.

The table is intentionally append-only. Admin surfaces read aggregate
percentiles and rates; they never expose per-row data or raw error text.

Revision ID: 0089_ai_latency_retry
Revises: 0088_admin_incidents
"""

import sqlalchemy as sa

from alembic import op

revision = "0089_ai_latency_retry"
down_revision = "0088_admin_incidents"
branch_labels = None
depends_on = None

STATUSES = ("success", "error", "timeout", "cancelled")
RETRY_REASONS = (
    "none",
    "timeout",
    "rate_limit",
    "connection",
    "provider_error",
    "empty_output",
    "truncated",
    "invalid_response",
    "cancelled",
    "unknown",
)
ERROR_CLASSES = (
    "timeout",
    "rate_limit",
    "connection",
    "provider_error",
    "invalid_response",
    "cancelled",
    "unknown",
)


def _in_clause(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"


def upgrade() -> None:
    op.create_table(
        "llm_call_attempts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "provider",
            sa.String(length=64),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column(
            "model",
            sa.String(length=160),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column(
            "feature",
            sa.String(length=120),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column(
            "plan",
            sa.String(length=50),
            nullable=False,
            server_default="unknown",
        ),
        # SHA-256-derived opaque reference: never a job/user/document id.
        sa.Column("run_ref", sa.String(length=64), nullable=True),
        sa.Column(
            "attempt_number",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="success",
        ),
        sa.Column(
            "retry_reason",
            sa.String(length=64),
            nullable=False,
            server_default="none",
        ),
        sa.Column("error_class", sa.String(length=64), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.CheckConstraint(
            _in_clause("status", STATUSES),
            name="ck_llm_call_attempts_status",
        ),
        sa.CheckConstraint(
            _in_clause("retry_reason", RETRY_REASONS),
            name="ck_llm_call_attempts_retry_reason",
        ),
        sa.CheckConstraint(
            "error_class IS NULL OR " + _in_clause("error_class", ERROR_CLASSES),
            name="ck_llm_call_attempts_error_class",
        ),
        sa.CheckConstraint(
            "attempt_number >= 1",
            name="ck_llm_call_attempts_attempt_number",
        ),
        sa.CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0",
            name="ck_llm_call_attempts_latency",
        ),
    )
    op.create_index(
        "idx_llm_attempts_occurred",
        "llm_call_attempts",
        ["occurred_at"],
    )
    op.create_index(
        "idx_llm_attempts_provider_occurred",
        "llm_call_attempts",
        ["provider", "occurred_at"],
    )
    op.create_index(
        "idx_llm_attempts_model_occurred",
        "llm_call_attempts",
        ["provider", "model", "occurred_at"],
    )
    op.create_index(
        "idx_llm_attempts_feature_occurred",
        "llm_call_attempts",
        ["feature", "occurred_at"],
    )
    op.create_index(
        "idx_llm_attempts_plan_occurred",
        "llm_call_attempts",
        ["plan", "occurred_at"],
    )
    op.create_index(
        "idx_llm_attempts_run",
        "llm_call_attempts",
        ["run_ref"],
    )


def downgrade() -> None:
    op.drop_index("idx_llm_attempts_run", table_name="llm_call_attempts")
    op.drop_index("idx_llm_attempts_plan_occurred", table_name="llm_call_attempts")
    op.drop_index("idx_llm_attempts_feature_occurred", table_name="llm_call_attempts")
    op.drop_index("idx_llm_attempts_model_occurred", table_name="llm_call_attempts")
    op.drop_index("idx_llm_attempts_provider_occurred", table_name="llm_call_attempts")
    op.drop_index("idx_llm_attempts_occurred", table_name="llm_call_attempts")
    op.drop_table("llm_call_attempts")
