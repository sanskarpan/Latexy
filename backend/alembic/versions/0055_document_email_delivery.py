"""Persist compiled-document email attempts and provider acceptance (B50d).

Revision ID: 0055
Revises: 0054
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_email_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("resume_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("compilation_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("recipient_email", sa.String(length=320), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(length=100), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_token", sa.String(length=64), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["compilation_id"], ["compilations.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("idempotency_key", name="uq_document_email_deliveries_idempotency"),
    )
    op.create_index(
        "ix_document_email_deliveries_pending",
        "document_email_deliveries",
        ["status", "next_attempt_at", "claimed_at"],
    )
    op.create_index(
        "ix_document_email_deliveries_user_created",
        "document_email_deliveries",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_document_email_deliveries_user_created", table_name="document_email_deliveries")
    op.drop_index("ix_document_email_deliveries_pending", table_name="document_email_deliveries")
    op.drop_table("document_email_deliveries")
