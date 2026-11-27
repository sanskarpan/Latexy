"""Saved admin views and reusable aggregate cohort segments.

Two operator-owned tables share one persistence model:

* ``admin_saved_views`` stores a named tab state (scope, allowlisted filters,
  columns, sort and range) with private/shared visibility, a per-scope default
  and optimistic-concurrency ``version``.
* ``admin_segments`` stores a typed filter DSL (``match`` plus conditions over
  allowlisted user/event dimensions). The compiler is code-owned; this table
  never stores SQL, identifiers, documents, prompts or per-user rows.

Both tables use soft deletes so a stale browser cannot silently lose a shared
view, and names are unique per owner (and per scope for views) while active.
No customer PII is duplicated here.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0093_admin_saved_views"
down_revision = "0092_document_complexity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_saved_views",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "owner_user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("name_key", sa.String(80), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column(
            "filters",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "columns",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("sort", postgresql.JSONB(), nullable=True),
        sa.Column("range_days", sa.Integer(), nullable=True),
        sa.Column("shared", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
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
        sa.CheckConstraint(
            "length(trim(name)) BETWEEN 1 AND 80 AND length(name_key) BETWEEN 1 AND 80",
            name="ck_admin_saved_views_name",
        ),
        sa.CheckConstraint(
            "scope IN ('analytics', 'operations', 'quality', 'billing', "
            "'subscriptions', 'email', 'growth', 'customers')",
            name="ck_admin_saved_views_scope",
        ),
        sa.CheckConstraint(
            "range_days IS NULL OR (range_days >= 1 AND range_days <= 365)",
            name="ck_admin_saved_views_range",
        ),
        sa.CheckConstraint("version >= 1", name="ck_admin_saved_views_version"),
        sa.CheckConstraint(
            "jsonb_typeof(filters) = 'object'",
            name="ck_admin_saved_views_filters_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(columns) = 'array'",
            name="ck_admin_saved_views_columns_array",
        ),
        sa.CheckConstraint(
            "sort IS NULL OR jsonb_typeof(sort) = 'object'",
            name="ck_admin_saved_views_sort_object",
        ),
    )
    op.create_index(
        "uq_admin_saved_views_owner_scope_name",
        "admin_saved_views",
        ["owner_user_id", "scope", "name_key"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_admin_saved_views_owner_default",
        "admin_saved_views",
        ["owner_user_id", "scope"],
        unique=True,
        postgresql_where=sa.text("is_default AND deleted_at IS NULL"),
    )
    op.create_index(
        "idx_admin_saved_views_scope_updated",
        "admin_saved_views",
        ["scope", "updated_at"],
    )
    op.create_index(
        "idx_admin_saved_views_owner_updated",
        "admin_saved_views",
        ["owner_user_id", "updated_at"],
    )
    op.create_index(
        "idx_admin_saved_views_shared_updated",
        "admin_saved_views",
        ["shared", "updated_at"],
    )

    op.create_table(
        "admin_segments",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "owner_user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("name_key", sa.String(80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "definition",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("shared", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
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
        sa.CheckConstraint(
            "length(trim(name)) BETWEEN 1 AND 80 AND length(name_key) BETWEEN 1 AND 80",
            name="ck_admin_segments_name",
        ),
        sa.CheckConstraint(
            "description IS NULL OR length(description) <= 280",
            name="ck_admin_segments_description",
        ),
        sa.CheckConstraint("version >= 1", name="ck_admin_segments_version"),
        sa.CheckConstraint(
            "jsonb_typeof(definition) = 'object'",
            name="ck_admin_segments_definition_object",
        ),
    )
    op.create_index(
        "uq_admin_segments_owner_name",
        "admin_segments",
        ["owner_user_id", "name_key"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "idx_admin_segments_owner_updated",
        "admin_segments",
        ["owner_user_id", "updated_at"],
    )
    op.create_index(
        "idx_admin_segments_shared_updated",
        "admin_segments",
        ["shared", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_admin_segments_shared_updated", table_name="admin_segments")
    op.drop_index("idx_admin_segments_owner_updated", table_name="admin_segments")
    op.drop_index("uq_admin_segments_owner_name", table_name="admin_segments")
    op.drop_table("admin_segments")

    op.drop_index("idx_admin_saved_views_shared_updated", table_name="admin_saved_views")
    op.drop_index("idx_admin_saved_views_owner_updated", table_name="admin_saved_views")
    op.drop_index("idx_admin_saved_views_scope_updated", table_name="admin_saved_views")
    op.drop_index("uq_admin_saved_views_owner_default", table_name="admin_saved_views")
    op.drop_index("uq_admin_saved_views_owner_scope_name", table_name="admin_saved_views")
    op.drop_table("admin_saved_views")
