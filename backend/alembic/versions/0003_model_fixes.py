"""Model fixes: FK on resume_job_matches, index on usage_analytics.created_at, ats_score Float

Revision ID: 0003_model_fixes
Revises: 0002_ats_pgvector
Create Date: 2026-03-10
"""


from alembic import op

revision = "0003_model_fixes"
down_revision = "0002_ats_pgvector"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Cast resume_job_matches.user_id from varchar to uuid (required for FK to users.id)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'resume_job_matches'
                AND column_name = 'user_id'
                AND data_type = 'character varying'
            ) THEN
                ALTER TABLE resume_job_matches
                ALTER COLUMN user_id TYPE UUID USING user_id::uuid;
            END IF;
        END $$;
    """)

    # Add FK constraint to resume_job_matches.user_id
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE constraint_name = 'fk_resume_job_matches_user_id'
                AND table_name = 'resume_job_matches'
            ) THEN
                ALTER TABLE resume_job_matches
                ADD CONSTRAINT fk_resume_job_matches_user_id
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
            END IF;
        END $$;
    """)

    # Add index on usage_analytics.created_at
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_usage_analytics_created_at
        ON usage_analytics(created_at);
    """)

    # Add index on resume_job_matches.user_id (if not exists)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_rjm_user_id
        ON resume_job_matches(user_id);
    """)

    # Add device_fingerprint column + index to optimizations (L23)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'optimizations'
                AND column_name = 'device_fingerprint'
            ) THEN
                ALTER TABLE optimizations ADD COLUMN device_fingerprint VARCHAR(255);
            END IF;
        END $$;
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_optimizations_device_fp ON optimizations(device_fingerprint);")

    # Change ats_score from JSON to FLOAT
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'optimizations'
                AND column_name = 'ats_score'
                AND data_type = 'json'
            ) THEN
                ALTER TABLE optimizations
                ALTER COLUMN ats_score TYPE FLOAT USING COALESCE(ats_score::text::float, NULL);
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_usage_analytics_created_at")
    op.execute("DROP INDEX IF EXISTS idx_rjm_user_id")
    op.execute("""
        ALTER TABLE resume_job_matches
        DROP CONSTRAINT IF EXISTS fk_resume_job_matches_user_id;
    """)
    op.execute("""
        ALTER TABLE optimizations
        ALTER COLUMN ats_score TYPE JSON USING ats_score::text::json;
    """)
