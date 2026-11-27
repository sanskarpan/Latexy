"""Internal user notes and tags for the User 360 support timeline (issue #2129).

Two operator-only tables are added:

* ``admin_user_notes`` stores an author, target user, bounded body, visibility,
  tags, optimistic concurrency version and soft-delete metadata.
* ``admin_user_tags`` stores a small lowercase label per target user. Active
  labels are unique per user; removals are soft so history is retained.

Neither table is exposed on a customer-facing route. The migration is additive
and reversible and writes no seed rows.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0102_admin_user_notes"
down_revision = "0100_daily_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_user_notes",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "target_user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "author_user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("author_role", sa.String(16), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "tags",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "visibility",
            sa.String(16),
            nullable=False,
            server_default="internal",
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "updated_by",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "deleted_by",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("delete_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "length(trim(body)) BETWEEN 3 AND 4000",
            name="ck_admin_user_notes_body",
        ),
        sa.CheckConstraint(
            "visibility IN ('internal', 'admin_only')",
            name="ck_admin_user_notes_visibility",
        ),
        sa.CheckConstraint(
            "author_role IN ('admin', 'support')",
            name="ck_admin_user_notes_author_role",
        ),
        sa.CheckConstraint("version >= 1", name="ck_admin_user_notes_version"),
        sa.CheckConstraint(
            "jsonb_typeof(tags) = 'array'",
            name="ck_admin_user_notes_tags_array",
        ),
    )
    op.create_index(
        "idx_admin_user_notes_target_created",
        "admin_user_notes",
        ["target_user_id", "created_at"],
    )
    op.create_index(
        "idx_admin_user_notes_author_created",
        "admin_user_notes",
        ["author_user_id", "created_at"],
    )
    op.create_index(
        "idx_admin_user_notes_visibility",
        "admin_user_notes",
        ["visibility", "created_at"],
    )
    op.create_index(
        "idx_admin_user_notes_tags",
        "admin_user_notes",
        ["tags"],
        postgresql_using="gin",
    )

    op.create_table(
        "admin_user_tags",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "target_user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tag", sa.String(32), nullable=False),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_by_role", sa.String(16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "removed_by",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("remove_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "tag ~ '^[a-z0-9][a-z0-9_-]{0,31}$'",
            name="ck_admin_user_tags_tag",
        ),
        sa.CheckConstraint(
            "created_by_role IN ('admin', 'support')",
            name="ck_admin_user_tags_created_by_role",
        ),
    )
    op.create_index(
        "uq_admin_user_tags_active",
        "admin_user_tags",
        ["target_user_id", "tag"],
        unique=True,
        postgresql_where=sa.text("removed_at IS NULL"),
    )
    op.create_index(
        "idx_admin_user_tags_target_created",
        "admin_user_tags",
        ["target_user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_admin_user_tags_target_created", table_name="admin_user_tags")
    op.drop_index("uq_admin_user_tags_active", table_name="admin_user_tags")
    op.drop_table("admin_user_tags")

    op.drop_index("idx_admin_user_notes_tags", table_name="admin_user_notes")
    op.drop_index("idx_admin_user_notes_visibility", table_name="admin_user_notes")
    op.drop_index("idx_admin_user_notes_author_created", table_name="admin_user_notes")
    op.drop_index("idx_admin_user_notes_target_created", table_name="admin_user_notes")
    op.drop_table("admin_user_notes")
