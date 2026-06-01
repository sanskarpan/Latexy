"""add resume builder fields

Revision ID: 0029
Revises: 0028
Create Date: 2026-05-29 11:30:00.000000
"""

import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("resumes")}

    if "structured_content" not in existing_columns:
        op.add_column(
            "resumes",
            sa.Column("structured_content", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        )
    if "structured_version" not in existing_columns:
        op.add_column(
            "resumes",
            sa.Column("structured_version", sa.Integer(), nullable=False, server_default="1"),
        )
    if "selected_template_id" not in existing_columns:
        op.add_column(
            "resumes",
            sa.Column("selected_template_id", postgresql.UUID(as_uuid=False), nullable=True),
        )
    if "content_source" not in existing_columns:
        op.add_column(
            "resumes",
            sa.Column("content_source", sa.Text(), nullable=False, server_default="manual_latex"),
        )
    if "builder_status" not in existing_columns:
        op.add_column(
            "resumes",
            sa.Column("builder_status", sa.Text(), nullable=False, server_default="detached"),
        )

    inspector = inspect(bind)
    foreign_keys = {fk["name"] for fk in inspector.get_foreign_keys("resumes")}
    if "fk_resumes_selected_template_id" not in foreign_keys:
        op.create_foreign_key(
            "fk_resumes_selected_template_id",
            "resumes",
            "resume_templates",
            ["selected_template_id"],
            ["id"],
            ondelete="SET NULL",
        )

    indexes = {index["name"] for index in inspector.get_indexes("resumes")}
    if "ix_resumes_selected_template_id" not in indexes:
        op.create_index(
            "ix_resumes_selected_template_id",
            "resumes",
            ["selected_template_id"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_index("ix_resumes_selected_template_id", table_name="resumes")
    op.drop_constraint("fk_resumes_selected_template_id", "resumes", type_="foreignkey")
    op.drop_column("resumes", "builder_status")
    op.drop_column("resumes", "content_source")
    op.drop_column("resumes", "selected_template_id")
    op.drop_column("resumes", "structured_version")
    op.drop_column("resumes", "structured_content")
