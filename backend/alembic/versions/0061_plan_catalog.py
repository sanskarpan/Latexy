"""Admin-owned SKU merchandising and audited revisions; no billing mutations.

Revision ID: 0061_plan_catalog
Revises: 0060_capability_catalog
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0061_plan_catalog"
down_revision = "0060_capability_catalog"
branch_labels = None
depends_on = None


def _already_present(name: str, expected: dict, primary_key: set[str]) -> bool:
    """Rollback retains admin data; validate before reusing its table."""
    if op.get_context().as_sql:
        return False
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(name):
        return False
    columns = {column["name"]: column for column in inspector.get_columns(name)}
    if set(columns) != set(expected):
        raise RuntimeError(f"Cannot reuse {name}: unexpected preserved schema")
    for column_name, (kind, nullable) in expected.items():
        actual = columns[column_name]
        if not isinstance(actual["type"], type(kind)) or actual["nullable"] != nullable:
            raise RuntimeError(f"Cannot reuse {name}.{column_name}: incompatible type/nullability")
        if getattr(kind, "length", None) != getattr(actual["type"], "length", None):
            raise RuntimeError(f"Cannot reuse {name}.{column_name}: incompatible length")
        if getattr(kind, "timezone", None) != getattr(actual["type"], "timezone", None):
            raise RuntimeError(f"Cannot reuse {name}.{column_name}: incompatible timezone")
    if set(inspector.get_pk_constraint(name)["constrained_columns"]) != primary_key:
        raise RuntimeError(f"Cannot reuse {name}: incompatible primary key")
    return True


def upgrade() -> None:
    catalog_exists = _already_present("plan_catalog", {
        "sku": (sa.String(50), False), "name": (sa.String(100), False),
        "description": (sa.String(300), False), "visible": (sa.Boolean(), False),
        "purchase_enabled": (sa.Boolean(), False), "display_order": (sa.Integer(), False),
        "version": (sa.Integer(), False), "updated_by": (postgresql.UUID(), True),
        "updated_at": (sa.DateTime(timezone=True), False),
    }, {"sku"})
    revisions_exist = _already_present("plan_catalog_revisions", {
        "sku": (sa.String(50), False), "version": (sa.Integer(), False),
        "snapshot": (postgresql.JSONB(), False), "changed_by": (postgresql.UUID(), True),
        "created_at": (sa.DateTime(timezone=True), False),
    }, {"sku", "version"})
    if not catalog_exists:
        op.create_table(
            "plan_catalog",
            sa.Column("sku", sa.String(50), primary_key=True),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("description", sa.String(300), nullable=False, server_default=""),
            sa.Column("visible", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("purchase_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("updated_by", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint("version >= 1", name="ck_plan_catalog_version"),
            sa.CheckConstraint("display_order >= 0", name="ck_plan_catalog_order"),
        )
    if not revisions_exist:
        op.create_table(
            "plan_catalog_revisions",
            sa.Column("sku", sa.String(50), sa.ForeignKey("plan_catalog.sku"), primary_key=True),
            sa.Column("version", sa.Integer(), primary_key=True),
            sa.Column("snapshot", postgresql.JSONB(), nullable=False),
            sa.Column("changed_by", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
    # Missing rows intentionally use stable code defaults until the first admin
    # edit. No environment-dependent price is frozen by a migration, and no
    # existing user, subscription, checkout, quota or provider row is touched.


def downgrade() -> None:
    # Catalog visibility and sale restrictions are business state, and audit
    # history must not be destroyed by a code rollback. Older code ignores these
    # tables; a re-upgrade validates and reuses them without resetting values.
    pass
