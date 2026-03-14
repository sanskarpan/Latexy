"""Add cover_letters table

Revision ID: 0006_add_cover_letters
Revises: 0005_add_checkpoint_columns
Create Date: 2026-03-13
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0006_add_cover_letters"
down_revision = "0005_add_checkpoint_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cover_letters",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "resume_id",
            UUID(as_uuid=False),
            sa.ForeignKey("resumes.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("job_description", sa.Text(), nullable=True),
        sa.Column("company_name", sa.String(255), nullable=True),
        sa.Column("role_title", sa.String(255), nullable=True),
        sa.Column("tone", sa.String(50), nullable=False, server_default="formal"),
        sa.Column(
            "length_preference",
            sa.String(50),
            nullable=False,
            server_default="3_paragraphs",
        ),
        sa.Column("latex_content", sa.Text(), nullable=True),
        sa.Column("pdf_path", sa.String(500), nullable=True),
        sa.Column("generation_job_id", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("cover_letters")
