"""Add UNIQUE(resume_id, jd_hash) to resume_job_matches.

Duplicate cache rows made the semantic-match cache lookup (.scalar_one_or_none())
raise MultipleResultsFound, breaking all subsequent match reads. Dedup existing
rows (keep the most recent per key), then enforce uniqueness at the DB level.

Revision ID: 0033
Revises: 0032
Create Date: 2026-07-02
"""

from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Remove duplicates, keeping the most recent row per (resume_id, jd_hash).
    op.execute(
        """
        DELETE FROM resume_job_matches a
        USING resume_job_matches b
        WHERE a.resume_id = b.resume_id
          AND a.jd_hash = b.jd_hash
          AND (a.created_at < b.created_at
               OR (a.created_at = b.created_at AND a.id < b.id))
        """
    )
    # Add the constraint idempotently.
    op.execute(
        """
        DO $$ BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'uq_resume_job_matches_resume_jd'
          ) THEN
            ALTER TABLE resume_job_matches
              ADD CONSTRAINT uq_resume_job_matches_resume_jd UNIQUE (resume_id, jd_hash);
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE resume_job_matches DROP CONSTRAINT IF EXISTS uq_resume_job_matches_resume_jd"
    )
