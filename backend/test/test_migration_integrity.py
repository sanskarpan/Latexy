"""Focused regression checks for migration ownership and downgrade safety."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_migration(filename: str):
    path = Path(__file__).parents[1] / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location("latexy_test_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_admin_control_plane_downgrade_does_not_delete_shared_feature_flags():
    migration = _load_migration("0035_admin_control_plane.py")
    calls: list[tuple[str, str]] = []

    class FakeOp:
        def get_bind(self):  # pragma: no cover - proves no destructive bind call
            raise AssertionError("downgrade must not delete unowned feature flags")

        def drop_table(self, table: str) -> None:
            calls.append(("drop_table", table))

        def drop_column(self, table: str, column: str) -> None:
            calls.append(("drop_column", f"{table}.{column}"))

    migration.op = FakeOp()
    migration.downgrade()

    assert calls == [
        ("drop_table", "plan_features"),
        ("drop_column", "users.role"),
    ]


def test_user_model_declares_0047_two_factor_column():
    from app.database.models import User

    column = User.__table__.c.two_factor_enabled
    assert column.nullable is False
    assert str(column.server_default.arg).lower() == "false"
