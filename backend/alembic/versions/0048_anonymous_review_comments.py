"""Add anonymous comments for review-capable share links.

Revision ID: 0048
Revises: 0047 (auth two-factor/passkey tables)
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resume_review_comments",
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
        sa.Column("share_token_hash", sa.String(64), nullable=False),
        sa.Column("reviewer_label", sa.String(32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=True),
        sa.Column("section_tag", sa.String(100), nullable=True),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_resume_review_comments_token",
        "resume_review_comments",
        ["share_token_hash", "created_at"],
    )
    op.create_index(
        "ix_resume_review_comments_resume",
        "resume_review_comments",
        ["resume_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_resume_review_comments_resume", table_name="resume_review_comments")
    op.drop_index("ix_resume_review_comments_token", table_name="resume_review_comments")
    op.drop_table("resume_review_comments")
