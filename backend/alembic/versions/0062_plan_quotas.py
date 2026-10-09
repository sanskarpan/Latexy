"""Versioned quota limits without changing windows, counters or receipts."""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0062_plan_quotas"
down_revision = "0061_plan_catalog"
branch_labels = None
depends_on = None


def _already_present(name: str, expected: dict, primary_key: set[str]) -> bool:
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
        for attr in ("length", "timezone"):
            if getattr(kind, attr, None) != getattr(actual["type"], attr, None):
                raise RuntimeError(f"Cannot reuse {name}.{column_name}: incompatible {attr}")
    if set(inspector.get_pk_constraint(name)["constrained_columns"]) != primary_key:
        raise RuntimeError(f"Cannot reuse {name}: incompatible primary key")
    return True


def upgrade() -> None:
    if not _already_present("plan_quota_overrides", {
        "sku": (sa.String(50), False), "dimension": (sa.String(30), False),
        "limit_value": (sa.Integer(), True), "version": (sa.Integer(), False),
        "updated_by": (postgresql.UUID(), True), "updated_at": (sa.DateTime(timezone=True), False),
    }, {"sku", "dimension"}):
        op.create_table(
            "plan_quota_overrides",
            sa.Column("sku", sa.String(50), primary_key=True),
            sa.Column("dimension", sa.String(30), primary_key=True),
            sa.Column("limit_value", sa.Integer(), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("updated_by", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint("dimension IN ('compilations', 'optimizations', 'ai_assists')", name="ck_plan_quota_dimension"),
            sa.CheckConstraint("limit_value IS NULL OR (limit_value >= 0 AND limit_value <= 1000000000)", name="ck_plan_quota_limit"),
            sa.CheckConstraint("version >= 1", name="ck_plan_quota_version"),
        )
    if not _already_present("plan_quota_revisions", {
        "sku": (sa.String(50), False), "dimension": (sa.String(30), False),
        "limit_value": (sa.Integer(), True), "version": (sa.Integer(), False),
        "changed_by": (postgresql.UUID(), True), "created_at": (sa.DateTime(timezone=True), False),
    }, {"sku", "dimension", "version"}):
        op.create_table(
            "plan_quota_revisions",
            sa.Column("sku", sa.String(50), primary_key=True),
            sa.Column("dimension", sa.String(30), primary_key=True),
            sa.Column("version", sa.Integer(), primary_key=True),
            sa.Column("limit_value", sa.Integer(), nullable=True),
            sa.Column("changed_by", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )


def downgrade() -> None:
    # Quota settings and audit history are administrator-owned state. Older code
    # ignores these tables; re-upgrade validates and retains all edits.
    pass
