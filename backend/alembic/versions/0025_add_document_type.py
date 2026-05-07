"""Add document_type column to resumes and resume_templates for Beamer support (Feature 86).

Revision ID: 0025
Revises: 0024
Create Date: 2026-05-07
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── resumes.document_type ─────────────────────────────────────────────────
    op.add_column(
        "resumes",
        sa.Column(
            "document_type",
            sa.Text(),
            nullable=False,
            server_default="resume",
        ),
    )
    op.create_index(
        "ix_resumes_user_document_type",
        "resumes",
        ["user_id", "document_type"],
    )

    # ── resume_templates.document_type ────────────────────────────────────────
    op.add_column(
        "resume_templates",
        sa.Column(
            "document_type",
            sa.Text(),
            nullable=False,
            server_default="resume",
        ),
    )


def downgrade() -> None:
    op.drop_column("resume_templates", "document_type")
    op.drop_index("ix_resumes_user_document_type", table_name="resumes")
    op.drop_column("resumes", "document_type")
