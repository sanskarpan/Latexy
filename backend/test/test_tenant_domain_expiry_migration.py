"""Migration/model contract for custom-domain expiry metadata."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from sqlalchemy import DateTime


def _migration():
    path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "0079_tenant_domain_expiry.py"
    )
    spec = importlib.util.spec_from_file_location("tenant_domain_expiry_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_chains_from_admin_alerts_and_is_additive():
    migration = _migration()
    calls: list[tuple] = []

    class FakeOp:
        def add_column(self, table: str, column) -> None:
            calls.append(("add_column", table, column.name, column.nullable, column.type))

        def drop_column(self, table: str, column: str) -> None:
            calls.append(("drop_column", table, column))

    migration.op = FakeOp()
    migration.upgrade()
    assert migration.revision == "0079_tenant_domain_expiry"
    assert migration.down_revision == "0078_admin_alerts"
    assert calls == [
        ("add_column", "tenants", "domain_expires_at", True, calls[0][4]),
        ("add_column", "tenants", "domain_certificate_expires_at", True, calls[1][4]),
    ]
    assert all(isinstance(call[4], DateTime) for call in calls)

    calls.clear()
    migration.downgrade()
    assert calls == [
        ("drop_column", "tenants", "domain_certificate_expires_at"),
        ("drop_column", "tenants", "domain_expires_at"),
    ]


def test_tenant_model_declares_nullable_expiry_columns():
    from app.database.models import Tenant

    for name in ("domain_expires_at", "domain_certificate_expires_at"):
        column = Tenant.__table__.c[name]
        assert column.nullable is True
        assert isinstance(column.type, DateTime)
        assert column.type.timezone is True
