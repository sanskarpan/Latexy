"""Audited read-only view-as-user preview sessions (issue #2125).

A preview session is a server-composed snapshot, not a target-user login. It
stores only the approving admin, the explicit target user, a hashed one-time
start token, a fixed ``read_only`` scope and a hard 15-minute deadline. No
target session, password, token or document content is copied or minted.

Every session is bound to one executed two-person approval. Deleting the target
or the operator cascades the preview session, and the unique approval binding
prevents replaying an approval into a second session.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0101_view_as_user"
down_revision = "0100_daily_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_view_as_sessions",
        sa.Column("id", sa.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "approval_id",
            sa.UUID(as_uuid=False),
            sa.ForeignKey("admin_approvals.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "admin_user_id",
            sa.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_user_id",
            sa.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column(
            "scope",
            sa.String(length=20),
            nullable=False,
            server_default="read_only",
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "ended_by",
            sa.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("end_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "scope = 'read_only'",
            name="ck_admin_view_as_scope",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_admin_view_as_expiry",
        ),
        sa.CheckConstraint(
            "expires_at <= created_at + interval '15 minutes'",
            name="ck_admin_view_as_max_expiry",
        ),
        sa.CheckConstraint(
            "ended_at IS NULL OR ended_at >= created_at",
            name="ck_admin_view_as_ended_after_start",
        ),
        sa.CheckConstraint(
            "token_hash ~ '^[0-9a-f]{64}$'",
            name="ck_admin_view_as_token_hash",
        ),
        sa.CheckConstraint(
            "admin_user_id <> target_user_id",
            name="ck_admin_view_as_distinct_target",
        ),
    )
    op.create_index(
        "idx_admin_view_as_admin_created",
        "admin_view_as_sessions",
        ["admin_user_id", "created_at"],
    )
    op.create_index(
        "idx_admin_view_as_target_created",
        "admin_view_as_sessions",
        ["target_user_id", "created_at"],
    )
    op.create_index(
        "idx_admin_view_as_expires",
        "admin_view_as_sessions",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_admin_view_as_expires",
        table_name="admin_view_as_sessions",
    )
    op.drop_index(
        "idx_admin_view_as_target_created",
        table_name="admin_view_as_sessions",
    )
    op.drop_index(
        "idx_admin_view_as_admin_created",
        table_name="admin_view_as_sessions",
    )
    op.drop_table("admin_view_as_sessions")
