"""Schema hardening: FK indexes, payments FK SET NULL, coupon redemption uniqueness, JSONB.

Addresses several db-models audit findings:
- DB-005: UNIQUE(coupon_id, user_id) on coupon_redemptions (dedup first).
- DB-006: payments.subscription_id FK -> ON DELETE SET NULL (+ index).
- DB-007/DB-008: indexes on FK columns used in filters/joins.
- DB-012: changes_made / event_metadata converted JSON -> JSONB.

Revision ID: 0034
Revises: 0033
Create Date: 2026-07-02
"""

from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


# (table, column, index_name) — SQLAlchemy default naming ix_<table>_<column>
_FK_INDEXES = [
    ("payments", "subscription_id", "ix_payments_subscription_id"),
    ("team_seats", "member_user_id", "ix_team_seats_member_user_id"),
    ("resume_collaborators", "user_id", "ix_resume_collaborators_user_id"),
    ("resume_collaborators", "invited_by", "ix_resume_collaborators_invited_by"),
    ("recruiter_notes", "author_id", "ix_recruiter_notes_author_id"),
    ("resume_comments", "author_id", "ix_resume_comments_author_id"),
    ("snippets", "author_id", "ix_snippets_author_id"),
    ("job_applications", "resume_id", "ix_job_applications_resume_id"),
    ("application_submissions", "resume_id", "ix_application_submissions_resume_id"),
    ("application_submissions", "job_tracker_id", "ix_application_submissions_job_tracker_id"),
    ("career_analyses", "target_role_id", "ix_career_analyses_target_role_id"),
    ("career_transitions", "to_role_id", "ix_career_transitions_to_role_id"),
]


def upgrade() -> None:
    # DB-006: recreate payments.subscription_id FK with ON DELETE SET NULL so deleting
    # a subscription with existing payments no longer fails on the NO ACTION default.
    op.execute("ALTER TABLE payments DROP CONSTRAINT IF EXISTS payments_subscription_id_fkey")
    op.execute(
        """
        ALTER TABLE payments
          ADD CONSTRAINT payments_subscription_id_fkey
          FOREIGN KEY (subscription_id) REFERENCES subscriptions (id) ON DELETE SET NULL
        """
    )

    # DB-007/DB-008: add missing indexes on FK columns used in filters/joins.
    for table, column, name in _FK_INDEXES:
        op.execute(f'CREATE INDEX IF NOT EXISTS {name} ON {table} ("{column}")')

    # DB-005: remove duplicate redemptions (keep earliest per coupon+user), then
    # enforce one redemption per (coupon, user). NULL coupon_id/user_id rows are left
    # alone (Postgres treats NULLs as distinct in unique constraints).
    op.execute(
        """
        DELETE FROM coupon_redemptions a
        USING coupon_redemptions b
        WHERE a.coupon_id IS NOT NULL
          AND a.user_id IS NOT NULL
          AND a.coupon_id = b.coupon_id
          AND a.user_id = b.user_id
          AND (a.redeemed_at > b.redeemed_at
               OR (a.redeemed_at = b.redeemed_at AND a.id > b.id))
        """
    )
    op.execute(
        """
        DO $$ BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'uq_coupon_redemptions_coupon_user'
          ) THEN
            ALTER TABLE coupon_redemptions
              ADD CONSTRAINT uq_coupon_redemptions_coupon_user UNIQUE (coupon_id, user_id);
          END IF;
        END $$;
        """
    )

    # DB-012: JSON -> JSONB for consistency and index-ability.
    op.execute(
        "ALTER TABLE optimizations ALTER COLUMN changes_made TYPE jsonb USING changes_made::jsonb"
    )
    op.execute(
        "ALTER TABLE usage_analytics ALTER COLUMN event_metadata TYPE jsonb USING event_metadata::jsonb"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE usage_analytics ALTER COLUMN event_metadata TYPE json USING event_metadata::json"
    )
    op.execute(
        "ALTER TABLE optimizations ALTER COLUMN changes_made TYPE json USING changes_made::json"
    )

    op.execute(
        "ALTER TABLE coupon_redemptions DROP CONSTRAINT IF EXISTS uq_coupon_redemptions_coupon_user"
    )

    for table, _column, name in _FK_INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")

    op.execute("ALTER TABLE payments DROP CONSTRAINT IF EXISTS payments_subscription_id_fkey")
    op.execute(
        """
        ALTER TABLE payments
          ADD CONSTRAINT payments_subscription_id_fkey
          FOREIGN KEY (subscription_id) REFERENCES subscriptions (id)
        """
    )
