"""Persist ATS score baselines and aggregate analysis dimensions.

Optimization rows historically kept only the post-optimization ``ats_score``.
The admin D5 report needs a comparable baseline, so this revision adds
``ats_score_before`` and ``ats_score_after`` plus the normalized industry and
profile keys that were active for the run. Existing post-scores are copied into
``ats_score_after``; rows that predate this revision have no baseline and are
counted (not inferred) by the report.

Only numeric scores and bounded classification keys are added. Resume text,
job descriptions, prompts and identities remain in their existing columns and
are never read by the aggregate report.

Revision ID: 0090_ats_score_baseline
Revises: 0088_admin_incidents
"""

import sqlalchemy as sa

from alembic import op

revision = "0090_ats_score_baseline"
down_revision = "0089_ai_latency_retry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "optimizations",
        sa.Column("ats_score_before", sa.Float(), nullable=True),
    )
    op.add_column(
        "optimizations",
        sa.Column("ats_score_after", sa.Float(), nullable=True),
    )
    op.add_column(
        "optimizations",
        sa.Column("industry", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "optimizations",
        sa.Column("profile", sa.String(length=100), nullable=True),
    )

    # Backfill only the post-score. Never fabricate a baseline from the
    # post-score: rows without a recorded baseline must stay visibly missing.
    op.execute(
        """
        UPDATE optimizations
           SET ats_score_after = ats_score
         WHERE ats_score IS NOT NULL
           AND ats_score >= 0
           AND ats_score <= 100
        """
    )

    op.create_check_constraint(
        "ck_optimizations_ats_score_before_range",
        "optimizations",
        "ats_score_before IS NULL OR (ats_score_before >= 0 AND ats_score_before <= 100)",
    )
    op.create_check_constraint(
        "ck_optimizations_ats_score_after_range",
        "optimizations",
        "ats_score_after IS NULL OR (ats_score_after >= 0 AND ats_score_after <= 100)",
    )

    op.create_index(
        "ix_optimizations_ats_baseline_created",
        "optimizations",
        ["created_at"],
        postgresql_where=sa.text("ats_score_before IS NOT NULL"),
    )
    op.create_index(
        "ix_optimizations_ats_baseline_industry_created",
        "optimizations",
        ["industry", "created_at"],
        postgresql_where=sa.text("ats_score_before IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_optimizations_ats_baseline_industry_created",
        table_name="optimizations",
    )
    op.drop_index(
        "ix_optimizations_ats_baseline_created",
        table_name="optimizations",
    )
    op.drop_constraint(
        "ck_optimizations_ats_score_after_range",
        "optimizations",
        type_="check",
    )
    op.drop_constraint(
        "ck_optimizations_ats_score_before_range",
        "optimizations",
        type_="check",
    )
    op.drop_column("optimizations", "profile")
    op.drop_column("optimizations", "industry")
    op.drop_column("optimizations", "ats_score_after")
    op.drop_column("optimizations", "ats_score_before")
