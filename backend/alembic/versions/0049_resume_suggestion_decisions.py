"""Persist authoritative suggesting-mode decisions.

Revision ID: 0049
Revises: 0048
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resume_suggestion_decisions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "resume_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("resumes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("suggestion_id", sa.String(512), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "decided_by_user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decided_by_role", sa.String(16), nullable=False),
        sa.Column("expected_content_sha256", sa.String(64), nullable=False),
        sa.Column("result_content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "resume_id",
            "suggestion_id",
            name="uq_resume_suggestion_decisions_resume_suggestion",
        ),
    )
    op.create_index(
        "ix_resume_suggestion_decisions_resume_created",
        "resume_suggestion_decisions",
        ["resume_id", "created_at"],
    )
    op.create_index(
        "ix_resume_suggestion_decisions_rate",
        "resume_suggestion_decisions",
        ["resume_id", "decided_by_user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_resume_suggestion_decisions_rate", table_name="resume_suggestion_decisions")
    op.drop_index(
        "ix_resume_suggestion_decisions_resume_created",
        table_name="resume_suggestion_decisions",
    )
    op.drop_table("resume_suggestion_decisions")
