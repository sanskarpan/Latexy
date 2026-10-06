"""Add normalized rendered-document anchors to peer-review comments.

Revision ID: 0050
Revises: 0049
"""

import sqlalchemy as sa

from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("resume_review_comments", sa.Column("page_number", sa.Integer(), nullable=True))
    op.add_column("resume_review_comments", sa.Column("x", sa.Float(), nullable=True))
    op.add_column("resume_review_comments", sa.Column("y", sa.Float(), nullable=True))
    op.create_check_constraint(
        "ck_review_comment_anchor_complete",
        "resume_review_comments",
        "(page_number IS NULL AND x IS NULL AND y IS NULL) OR "
        "(page_number IS NOT NULL AND x IS NOT NULL AND y IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_review_comment_anchor_x_range",
        "resume_review_comments",
        "x IS NULL OR (x >= 0 AND x <= 1)",
    )
    op.create_check_constraint(
        "ck_review_comment_anchor_y_range",
        "resume_review_comments",
        "y IS NULL OR (y >= 0 AND y <= 1)",
    )
    op.create_check_constraint(
        "ck_review_comment_anchor_page_range",
        "resume_review_comments",
        "page_number IS NULL OR (page_number >= 1 AND page_number <= 10000)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_review_comment_anchor_page_range", "resume_review_comments", type_="check")
    op.drop_constraint("ck_review_comment_anchor_y_range", "resume_review_comments", type_="check")
    op.drop_constraint("ck_review_comment_anchor_x_range", "resume_review_comments", type_="check")
    op.drop_constraint("ck_review_comment_anchor_complete", "resume_review_comments", type_="check")
    op.drop_column("resume_review_comments", "y")
    op.drop_column("resume_review_comments", "x")
    op.drop_column("resume_review_comments", "page_number")
