"""Add application_submissions table for one-click job applications (Feature 87).

Revision ID: 0026
Revises: 0025
Create Date: 2026-05-07
"""

from alembic import op
import sqlalchemy as sa

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "application_submissions",
        sa.Column("id", sa.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            sa.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "resume_id",
            sa.UUID(as_uuid=False),
            sa.ForeignKey("resumes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "job_tracker_id",
            sa.UUID(as_uuid=False),
            sa.ForeignKey("job_applications.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("platform_job_id", sa.Text(), nullable=True),
        sa.Column("application_url", sa.Text(), nullable=False),
        sa.Column("job_title", sa.Text(), nullable=True),
        sa.Column("company_name", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_application_submissions_user_id",
        "application_submissions",
        ["user_id"],
    )
    op.create_index(
        "ix_application_submissions_status",
        "application_submissions",
        ["user_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_application_submissions_status", table_name="application_submissions")
    op.drop_index("ix_application_submissions_user_id", table_name="application_submissions")
    op.drop_table("application_submissions")
