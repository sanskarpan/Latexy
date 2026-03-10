"""Add pgvector extension, content_embedding to resumes, job_desc_embedding to optimizations,
deep_analysis_trials table, and resume_job_matches table.

Revision ID: 0002_ats_pgvector
Revises: 0001_initial_complete_schema
Create Date: 2026-03-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_ats_pgvector"
down_revision = "0001_initial_complete_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Try to enable pgvector extension (optional — only available on pgvector-enabled postgres)
    op.execute("""
        DO $$
        BEGIN
            CREATE EXTENSION IF NOT EXISTS vector;
        EXCEPTION WHEN OTHERS THEN
            RAISE WARNING 'pgvector extension not available: %. HNSW index will be skipped.', SQLERRM;
        END;
        $$
    """)

    # Add content_embedding column to resumes (idempotent via raw SQL)
    op.execute("""
        ALTER TABLE resumes
        ADD COLUMN IF NOT EXISTS content_embedding FLOAT[]
    """)
    # HNSW index — only if pgvector is available
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
                CREATE INDEX IF NOT EXISTS idx_resumes_embedding_hnsw
                ON resumes
                USING hnsw ((content_embedding::vector(1536)) vector_cosine_ops)
                WITH (m = 16, ef_construction = 64);
            END IF;
        END;
        $$
    """)

    # Add job_desc_embedding column to optimizations (idempotent)
    op.execute("""
        ALTER TABLE optimizations
        ADD COLUMN IF NOT EXISTS job_desc_embedding FLOAT[]
    """)

    # Create deep_analysis_trials table (idempotent)
    op.execute("""
        CREATE TABLE IF NOT EXISTS deep_analysis_trials (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            device_fingerprint VARCHAR(255) NOT NULL UNIQUE,
            usage_count INTEGER NOT NULL DEFAULT 0,
            last_used TIMESTAMPTZ
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_deep_analysis_trials_fingerprint
        ON deep_analysis_trials (device_fingerprint)
    """)

    # Create resume_job_matches table (idempotent)
    op.execute("""
        CREATE TABLE IF NOT EXISTS resume_job_matches (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id VARCHAR(255),
            resume_id UUID NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
            jd_hash VARCHAR(64) NOT NULL,
            similarity_score FLOAT NOT NULL,
            matched_keywords TEXT[],
            missing_keywords TEXT[],
            semantic_gaps JSONB,
            created_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_rjm_resume_jd
        ON resume_job_matches (resume_id, jd_hash)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_rjm_user_id
        ON resume_job_matches (user_id)
    """)


def downgrade() -> None:
    op.drop_table("resume_job_matches")
    op.drop_table("deep_analysis_trials")
    op.drop_column("optimizations", "job_desc_embedding")
    op.execute("DROP INDEX IF EXISTS idx_resumes_embedding_hnsw")
    op.drop_column("resumes", "content_embedding")
