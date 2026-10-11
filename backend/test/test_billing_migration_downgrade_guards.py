from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

MIGRATION_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"


class _Result:
    def __init__(self, exists: bool):
        self.exists = exists

    def scalar_one(self) -> bool:
        return self.exists


class _Bind:
    def __init__(self, has_data: bool):
        self.has_data = has_data
        self.queries: list[str] = []

    def execute(self, statement: Any) -> _Result:
        self.queries.append(str(statement))
        return _Result(self.has_data)


class _Operations:
    def __init__(self, has_data: bool):
        self.bind = _Bind(has_data)
        self.ddl: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def get_bind(self) -> _Bind:
        return self.bind

    def __getattr__(self, name: str):
        def record(*args: Any, **kwargs: Any) -> None:
            self.ddl.append((name, args, kwargs))

        return record


def _migration(filename: str):
    path = MIGRATION_DIR / filename
    spec = importlib.util.spec_from_file_location(f"test_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MIGRATIONS = [
    (
        "0065_provider_neutral_billing.py",
        "cannot downgrade billing revision 0065",
    ),
    (
        "0066_subscription_quote_tax_basis.py",
        "cannot downgrade billing revision 0066",
    ),
    (
        "0067_coupon_reservation_state.py",
        "cannot downgrade billing revision 0067",
    ),
    (
        "0068_webhook_resource_identity.py",
        "cannot downgrade billing revision 0068",
    ),
]


@pytest.mark.parametrize(("filename", "message"), MIGRATIONS)
def test_downgrade_refuses_when_billing_evidence_would_be_lost(
    monkeypatch: pytest.MonkeyPatch, filename: str, message: str,
) -> None:
    migration = _migration(filename)
    operations = _Operations(has_data=True)
    monkeypatch.setattr(migration, "op", operations)

    with pytest.raises(RuntimeError, match=message):
        migration.downgrade()

    assert len(operations.bind.queries) == 1
    assert operations.ddl == []


@pytest.mark.parametrize(("filename", "_message"), MIGRATIONS)
def test_fresh_empty_billing_schema_remains_reversible(
    monkeypatch: pytest.MonkeyPatch, filename: str, _message: str,
) -> None:
    migration = _migration(filename)
    operations = _Operations(has_data=False)
    monkeypatch.setattr(migration, "op", operations)

    migration.downgrade()

    assert len(operations.bind.queries) == 1
    assert operations.ddl


def test_revision_0065_guard_covers_provider_fields_that_legacy_columns_cannot_restore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _migration("0065_provider_neutral_billing.py")
    operations = _Operations(has_data=False)
    monkeypatch.setattr(migration, "op", operations)

    migration.downgrade()

    query = " ".join(operations.bind.queries[0].lower().split())
    for condition in (
        "provider_subscription_id is distinct from razorpay_subscription_id",
        "provider_checkout_session_id is not null",
        "provider_customer_id is not null",
        "provider_product_id is not null",
        "provider_payment_id is distinct from razorpay_payment_id",
    ):
        assert condition in query
