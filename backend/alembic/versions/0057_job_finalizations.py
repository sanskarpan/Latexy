"""Add the durable cross-store job finalization arbiter.

Revision ID: 0057
Revises: 0056
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_finalizations",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("job_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("compilation_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("resume_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("cover_letter_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("owner_token", sa.String(length=128), nullable=True),
        sa.Column("owner_epoch", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("state", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("terminal_result", sa.String(length=16), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("result_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("pdf_path", sa.String(length=500), nullable=True),
        sa.Column("pdf_sha256", sa.String(length=64), nullable=True),
        sa.Column("pdf_size", sa.Integer(), nullable=True),
        sa.Column("resume_apply_requested", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("resume_applied", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("cover_letter_applied", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("cover_letter_apply_requested", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_job_finalizations_job_id"),
        sa.CheckConstraint(
            "state IN ('pending', 'committing', 'completed', 'failed', 'cancelled', 'fenced')",
            name="ck_job_finalizations_state",
        ),
        sa.CheckConstraint("owner_epoch >= 0", name="ck_job_finalizations_owner_epoch_nonnegative"),
        sa.CheckConstraint(
            "pdf_size IS NULL OR pdf_size BETWEEN 0 AND 20971520",
            name="ck_job_finalizations_pdf_size_bounded",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["compilation_id"], ["compilations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["cover_letter_id"], ["cover_letters.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_job_finalizations_user_id", "job_finalizations", ["user_id"])
    op.create_index(
        "idx_job_finalizations_recovery",
        "job_finalizations",
        ["state", "lease_expires_at"],
    )
    op.create_index("idx_job_finalizations_expiry", "job_finalizations", ["expires_at"])


def downgrade() -> None:
    op.drop_index("idx_job_finalizations_expiry", table_name="job_finalizations")
    op.drop_index("idx_job_finalizations_recovery", table_name="job_finalizations")
    op.drop_index("ix_job_finalizations_user_id", table_name="job_finalizations")
    op.drop_table("job_finalizations")
