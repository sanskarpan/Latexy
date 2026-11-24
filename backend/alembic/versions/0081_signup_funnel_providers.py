"""Persist auth provider and signup/verification funnel events.

The auth provider on ``users`` is derived from Better Auth's server-owned
``account`` rows, never from a client claim. Existing accounts are backfilled
once (earliest linked account wins, ``credential`` becomes ``email`` and any
non-Google/GitHub social provider is bucketed as ``oidc``); every other account
keeps the ``unknown`` default.

``signup_funnel_events`` stores only an event name, the allowlisted provider
bucket, an optional coarse failure code and timestamps. It deliberately has no
email, name, IP, user-agent, OAuth token or other credential columns.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0081_signup_funnel_providers"
down_revision = "0080_queue_snapshots"
branch_labels = None
depends_on = None

PROVIDERS = ("email", "google", "github", "oidc", "passkey", "unknown")
EVENTS = ("signup_started", "signup_completed", "email_verified", "oauth_failure")
FAILURE_CODES = (
    "access_denied",
    "account_not_linked",
    "callback_failed",
    "provider_error",
    "state_mismatch",
    "unknown",
)


def _in_clause(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "auth_provider",
            sa.String(20),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.create_check_constraint(
        "ck_users_auth_provider",
        "users",
        _in_clause("auth_provider", PROVIDERS),
    )

    # One-time, server-side backfill from Better Auth's account table. Earlier
    # rows win so a later account link never rewrites the signup provider.
    op.execute(
        """
        UPDATE users AS u
        SET auth_provider = COALESCE(
            (
                SELECT CASE
                    WHEN a."providerId" = 'credential' THEN 'email'
                    WHEN a."providerId" = 'google' THEN 'google'
                    WHEN a."providerId" = 'github' THEN 'github'
                    WHEN a."providerId" = 'passkey' THEN 'passkey'
                    WHEN a."providerId" IS NOT NULL AND a."providerId" <> '' THEN 'oidc'
                    ELSE 'unknown'
                END
                FROM account AS a
                WHERE a."userId" = u.id::text
                ORDER BY a."createdAt" ASC NULLS LAST, a.id ASC
                LIMIT 1
            ),
            'unknown'
        )
        WHERE u.auth_provider = 'unknown'
        """
    )

    op.create_table(
        "signup_funnel_events",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("event", sa.String(32), nullable=False),
        sa.Column(
            "provider",
            sa.String(20),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("failure_code", sa.String(32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            _in_clause("event", EVENTS),
            name="ck_signup_funnel_events_event",
        ),
        sa.CheckConstraint(
            _in_clause("provider", PROVIDERS),
            name="ck_signup_funnel_events_provider",
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR "
            + _in_clause("failure_code", FAILURE_CODES),
            name="ck_signup_funnel_events_failure_code",
        ),
    )
    op.create_index(
        "idx_signup_funnel_events_event_provider_time",
        "signup_funnel_events",
        ["event", "provider", "created_at"],
    )
    op.create_index(
        "idx_signup_funnel_events_user_event",
        "signup_funnel_events",
        ["user_id", "event"],
    )
    # Completion and verification are once-per-account facts; an anonymous
    # started event is not. Enforce that in the database so retries and
    # concurrent auth callbacks cannot double-count the funnel.
    op.create_index(
        "uq_signup_funnel_events_user_milestone",
        "signup_funnel_events",
        ["user_id", "event"],
        unique=True,
        postgresql_where=sa.text(
            "user_id IS NOT NULL AND event IN ('signup_completed', 'email_verified')"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_signup_funnel_events_user_milestone",
        table_name="signup_funnel_events",
    )
    op.drop_index(
        "idx_signup_funnel_events_user_event",
        table_name="signup_funnel_events",
    )
    op.drop_index(
        "idx_signup_funnel_events_event_provider_time",
        table_name="signup_funnel_events",
    )
    op.drop_table("signup_funnel_events")
    op.drop_constraint("ck_users_auth_provider", "users", type_="check")
    op.drop_column("users", "auth_provider")
