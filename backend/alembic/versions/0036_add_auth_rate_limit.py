"""Auth rate-limit counters shared across Next.js instances.

The Next server enforces per-IP rate limits on the Better Auth endpoints
(sign-in / sign-up / password reset / verification email). Those counters have
to be shared across instances, so they live in Postgres rather than in a
per-process Map. The table is owned by this migration — application code must
never issue DDL on the request path (a DB role without DDL rights would then
break every auth request).

Revision ID: 0036
Revises: 0035
Create Date: 2026-07-27
"""

from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS auth_rate_limit (
            key          text PRIMARY KEY,
            count        integer NOT NULL,
            last_request bigint  NOT NULL
        )
        """
    )
    # Supports the periodic pruning sweep of long-expired counters.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_auth_rate_limit_last_request "
        "ON auth_rate_limit (last_request)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_auth_rate_limit_last_request")
    op.execute("DROP TABLE IF EXISTS auth_rate_limit")
