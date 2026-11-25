"""Persist consented trial attribution and trial-to-user/subscription linkage.

A row is keyed by the anonymous ``device_trials`` row and carries only the
allowlisted first-touch campaign labels, the trial/signup/paid timestamps and
the eventual account/subscription link. It deliberately has no email, name,
raw device fingerprint, IP address, user-agent, token or document columns.

``user_id`` is nullable while the trial is anonymous and becomes non-null when
the signed-in visitor claims the trial. Deleting the account cascades the row
so deletion also removes the attribution; the anonymous trial itself remains
(a trial use is not a durable personal identifier in this report).

The partial unique index allows many anonymous rows but at most one linked
trial per account, so a cohort cannot double-count an account across devices.

NOTE: The wave-4 integration branch already contains ``0083_compile_error_taxonomy``.
Per the task contract this revision intentionally declares ``0082`` as its
parent; integration will re-chain/renumber the delivered migrations.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0086_trial_attribution"
down_revision = "0085_gdpr_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trial_attributions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "trial_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("device_trials.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "subscription_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("subscriptions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "consent_granted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("acquisition_source", sa.String(64), nullable=True),
        sa.Column("acquisition_medium", sa.String(64), nullable=True),
        sa.Column("acquisition_campaign", sa.String(64), nullable=True),
        sa.Column("acquisition_content", sa.String(64), nullable=True),
        sa.Column("acquisition_term", sa.String(64), nullable=True),
        sa.Column("referrer_host", sa.String(253), nullable=True),
        sa.Column("landing_path", sa.String(240), nullable=True),
        sa.Column("plan_id", sa.String(50), nullable=True),
        sa.Column(
            "trial_started_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("signup_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "consent_granted OR ("
            "acquisition_source IS NULL AND acquisition_medium IS NULL AND "
            "acquisition_campaign IS NULL AND acquisition_content IS NULL AND "
            "acquisition_term IS NULL AND referrer_host IS NULL AND "
            "landing_path IS NULL)",
            name="ck_trial_attributions_consent_source",
        ),
        sa.UniqueConstraint(
            "trial_id",
            name="uq_trial_attributions_trial",
        ),
    )
    op.create_index(
        "uq_trial_attributions_user",
        "trial_attributions",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index(
        "idx_trial_attributions_source",
        "trial_attributions",
        ["acquisition_source"],
    )
    op.create_index(
        "idx_trial_attributions_user_created",
        "trial_attributions",
        ["user_id", "created_at"],
    )
    op.create_index(
        "idx_trial_attributions_paid",
        "trial_attributions",
        ["paid_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_trial_attributions_paid", table_name="trial_attributions")
    op.drop_index(
        "idx_trial_attributions_user_created", table_name="trial_attributions"
    )
    op.drop_index("idx_trial_attributions_source", table_name="trial_attributions")
    op.drop_index("uq_trial_attributions_user", table_name="trial_attributions")
    op.drop_table("trial_attributions")
