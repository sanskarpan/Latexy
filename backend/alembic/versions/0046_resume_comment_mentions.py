"""Persist resume-comment mentions and their email delivery state.

Revision ID: 0046
Revises: 0045
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resume_comment_mentions",
        sa.Column(
            "id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "comment_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("resume_comments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "resume_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("resumes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "mentioned_user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # The row id is the durable provider idempotency key. Keep the key
        # stable when a comment is edited and a mention is retained.
        sa.Column("delivery_sent_at", sa.DateTime(timezone=True)),
        sa.Column("delivery_claimed_at", sa.DateTime(timezone=True)),
        sa.Column("delivery_claim_token", sa.String(64)),
        sa.Column("delivery_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("delivery_last_error", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("comment_id", "mentioned_user_id", name="uq_comment_mentions_comment_user"),
    )
    op.create_index("ix_comment_mentions_comment_id", "resume_comment_mentions", ["comment_id"])
    op.create_index("ix_comment_mentions_resume_id", "resume_comment_mentions", ["resume_id"])
    op.create_index("ix_comment_mentions_user_id", "resume_comment_mentions", ["mentioned_user_id"])
    op.create_index(
        "ix_comment_mentions_delivery",
        "resume_comment_mentions",
        ["delivery_sent_at", "delivery_claimed_at", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_comment_mentions_delivery", table_name="resume_comment_mentions")
    op.drop_index("ix_comment_mentions_user_id", table_name="resume_comment_mentions")
    op.drop_index("ix_comment_mentions_resume_id", table_name="resume_comment_mentions")
    op.drop_index("ix_comment_mentions_comment_id", table_name="resume_comment_mentions")
    op.drop_table("resume_comment_mentions")
