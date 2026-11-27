"""PostHog cohort definitions, synced membership and flag mappings (issue #2165).

Additive and reversible. The migration stores only bounded cohort
configuration, opaque account membership and flag mappings:

* ``feature_cohorts`` holds the PostHog cohort id, optional tenant scope, the
  freshness budget, aggregate size and a bounded error code. It never stores a
  PostHog payload, email, name, document, prompt, token, IP address or user
  agent.
* ``feature_cohort_members`` stores only ``(cohort_id, user_id, synced_at)``.
  A successful sync replaces a cohort's rows in the same transaction.
* ``feature_cohort_flag_mappings`` maps cohorts to existing first-party
  ``feature_flags`` rows.

The minimum cohort size is enforced at the database layer (>= 5) as well as in
the service. The table is seeded empty, so applying it cannot enable a flag or
change runtime behaviour.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0108_cohort_sync"
down_revision = "0102_admin_user_notes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feature_cohorts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("posthog_cohort_id", sa.String(64), nullable=True),
        sa.Column("minimum_size", sa.Integer(), nullable=False, server_default="5"),
        sa.Column(
            "stale_after_seconds",
            sa.Integer(),
            nullable=False,
            server_default="86400",
        ),
        sa.Column(
            "sync_state",
            sa.String(24),
            nullable=False,
            server_default="never_synced",
        ),
        sa.Column("synced_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "last_sync_attempt_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_error", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("key", name="uq_feature_cohorts_key"),
        sa.CheckConstraint("minimum_size >= 5", name="ck_feature_cohorts_minimum_size"),
        sa.CheckConstraint(
            "stale_after_seconds >= 300 AND stale_after_seconds <= 604800",
            name="ck_feature_cohorts_stale_window",
        ),
        sa.CheckConstraint("synced_size >= 0", name="ck_feature_cohorts_synced_size"),
        sa.CheckConstraint(
            "sync_state IN ('never_synced', 'synced', 'error', 'below_minimum')",
            name="ck_feature_cohorts_sync_state",
        ),
        sa.CheckConstraint(
            "posthog_cohort_id IS NULL OR length(posthog_cohort_id) BETWEEN 1 AND 64",
            name="ck_feature_cohorts_posthog_id",
        ),
    )
    op.create_index(
        "ix_feature_cohorts_tenant_id", "feature_cohorts", ["tenant_id"]
    )

    op.create_table(
        "feature_cohort_members",
        sa.Column(
            "cohort_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("feature_cohorts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "synced_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("cohort_id", "user_id"),
    )
    op.create_index(
        "ix_feature_cohort_members_user", "feature_cohort_members", ["user_id"]
    )

    op.create_table(
        "feature_cohort_flag_mappings",
        sa.Column(
            "cohort_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("feature_cohorts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "flag_key",
            sa.String(100),
            sa.ForeignKey("feature_flags.key", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("cohort_id", "flag_key"),
    )
    op.create_index(
        "ix_feature_cohort_flag_mappings_flag",
        "feature_cohort_flag_mappings",
        ["flag_key"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_feature_cohort_flag_mappings_flag",
        table_name="feature_cohort_flag_mappings",
    )
    op.drop_table("feature_cohort_flag_mappings")
    op.drop_index(
        "ix_feature_cohort_members_user", table_name="feature_cohort_members"
    )
    op.drop_table("feature_cohort_members")
    op.drop_index("ix_feature_cohorts_tenant_id", table_name="feature_cohorts")
    op.drop_table("feature_cohorts")
