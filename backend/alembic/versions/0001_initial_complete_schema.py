"""Complete initial schema — all app tables and Better Auth tables.

Revision ID: 0001_initial_complete_schema
Revises:
Create Date: 2026-03-07
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "0001_initial_complete_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Better Auth tables (managed by auth library, created here for completeness) ──

    op.create_table(
        "session",
        sa.Column("id", sa.String(255), primary_key=True),
        sa.Column("userId", sa.String(255), nullable=False),
        sa.Column("expiresAt", sa.DateTime(timezone=True), nullable=False),
        sa.Column("token", sa.String(255), nullable=False),
        sa.Column("ipAddress", sa.String(45), nullable=True),
        sa.Column("userAgent", sa.Text(), nullable=True),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("token", name="uq_session_token"),
    )

    op.create_table(
        "account",
        sa.Column("id", sa.String(255), primary_key=True),
        sa.Column("userId", sa.String(255), nullable=False),
        sa.Column("accountId", sa.String(255), nullable=False),
        sa.Column("providerId", sa.String(255), nullable=False),
        sa.Column("accessToken", sa.Text(), nullable=True),
        sa.Column("refreshToken", sa.Text(), nullable=True),
        sa.Column("idToken", sa.Text(), nullable=True),
        sa.Column("accessTokenExpiresAt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refreshTokenExpiresAt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scope", sa.String(255), nullable=True),
        sa.Column("password", sa.String(255), nullable=True),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table(
        "verification",
        sa.Column("id", sa.String(255), primary_key=True),
        sa.Column("identifier", sa.String(255), nullable=False),
        sa.Column("value", sa.String(255), nullable=False),
        sa.Column("expiresAt", sa.DateTime(timezone=True), nullable=False),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # ── Application tables ────────────────────────────────────────────────────────

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("avatar_url", sa.String(500), nullable=True),
        sa.Column("subscription_plan", sa.String(50), nullable=False, server_default="free"),
        sa.Column("subscription_status", sa.String(50), nullable=False, server_default="inactive"),
        sa.Column("subscription_id", sa.String(255), nullable=True),
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("trial_used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("idx_users_email", "users", ["email"])

    op.create_table(
        "device_trials",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("device_fingerprint", sa.String(255), nullable=False),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("session_id", sa.String(255), nullable=True),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_used", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("blocked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("device_fingerprint", name="uq_device_trials_fingerprint"),
    )
    op.create_index("idx_device_trials_fingerprint", "device_trials", ["device_fingerprint"])
    op.create_index("idx_device_trials_ip", "device_trials", ["ip_address"])

    op.create_table(
        "user_api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("encrypted_key", sa.Text(), nullable=False),
        sa.Column("key_name", sa.String(100), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_validated", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_user_api_keys_user_id", "user_api_keys", ["user_id"])

    op.create_table(
        "resumes",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("latex_content", sa.Text(), nullable=False),
        sa.Column("is_template", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("tags", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_resumes_user_id", "resumes", ["user_id"])

    op.create_table(
        "compilations",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "resume_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("resumes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("device_fingerprint", sa.String(255), nullable=True),
        sa.Column("job_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("pdf_path", sa.String(500), nullable=True),
        sa.Column("compilation_time", sa.Float(), nullable=True),
        sa.Column("pdf_size", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("job_id", name="uq_compilations_job_id"),
    )
    op.create_index("idx_compilations_user_id", "compilations", ["user_id"])
    op.create_index("idx_compilations_device", "compilations", ["device_fingerprint"])

    op.create_table(
        "optimizations",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "resume_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("resumes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("job_description", sa.Text(), nullable=False),
        sa.Column("original_latex", sa.Text(), nullable=False),
        sa.Column("optimized_latex", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("tokens_used", sa.Integer(), nullable=True),
        sa.Column("optimization_time", sa.Float(), nullable=True),
        sa.Column("ats_score", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("changes_made", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_optimizations_user_id", "optimizations", ["user_id"])

    op.create_table(
        "usage_analytics",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("device_fingerprint", sa.String(255), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=True),
        sa.Column("event_metadata", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_usage_analytics_user_id", "usage_analytics", ["user_id"])
    op.create_index("idx_usage_analytics_device", "usage_analytics", ["device_fingerprint"])

    op.create_table(
        "subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("razorpay_subscription_id", sa.String(255), nullable=True),
        sa.Column("plan_id", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("razorpay_subscription_id", name="uq_subscriptions_razorpay_id"),
    )
    op.create_index("idx_subscriptions_user_id", "subscriptions", ["user_id"])

    op.create_table(
        "payments",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "subscription_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("subscriptions.id"),
            nullable=True,
        ),
        sa.Column("razorpay_payment_id", sa.String(255), nullable=True),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="INR"),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("payment_method", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("razorpay_payment_id", name="uq_payments_razorpay_id"),
    )
    op.create_index("idx_payments_user_id", "payments", ["user_id"])


def downgrade() -> None:
    op.drop_table("payments")
    op.drop_table("subscriptions")
    op.drop_table("usage_analytics")
    op.drop_table("optimizations")
    op.drop_table("compilations")
    op.drop_table("resumes")
    op.drop_table("user_api_keys")
    op.drop_table("device_trials")
    op.drop_table("users")
    op.drop_table("verification")
    op.drop_table("account")
    op.drop_table("session")
