"""Add persisted per-job bullet variant sets.

Revision ID: 0039
Revises: 0038
Create Date: 2026-09-08
"""

from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE bullet_variant_sets (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            resume_id uuid NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
            source_text text NOT NULL,
            source_hash varchar(64) NOT NULL,
            job_context_hash varchar(64) NOT NULL,
            target_label varchar(200) NOT NULL DEFAULT 'General',
            options jsonb NOT NULL DEFAULT '[]'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_bullet_variant_sets_resume_source_job
                UNIQUE (resume_id, source_hash, job_context_hash)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_bullet_variant_sets_user_id "
        "ON bullet_variant_sets (user_id)"
    )
    op.execute(
        "CREATE INDEX ix_bullet_variant_sets_resume_id "
        "ON bullet_variant_sets (resume_id)"
    )
    op.execute(
        "CREATE INDEX ix_bullet_variant_sets_resume_created "
        "ON bullet_variant_sets (resume_id, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS bullet_variant_sets")
