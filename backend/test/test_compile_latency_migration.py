"""Migration/model contract for persisted compile-latency dimensions."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects import postgresql


def _migration():
    path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "0081_compile_latency_dimensions.py"
    )
    spec = importlib.util.spec_from_file_location("compile_latency_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_chains_from_queue_snapshots_and_is_additive():
    migration = _migration()
    calls: list[tuple] = []

    class FakeOp:
        def add_column(self, table: str, column) -> None:
            calls.append(("add_column", table, column.name, column.nullable, column.type))

        def drop_column(self, table: str, column: str) -> None:
            calls.append(("drop_column", table, column))

        def create_index(self, name: str, table: str, columns: list[str]) -> None:
            calls.append(("create_index", name, table, columns))

        def drop_index(self, name: str, table_name: str) -> None:
            calls.append(("drop_index", name, table_name))

    migration.op = FakeOp()
    migration.upgrade()

    assert migration.revision == "0081_compile_latency_dimensions"
    assert migration.down_revision == "0080_queue_snapshots"
    assert [(call[1], call[2], call[3]) for call in calls if call[0] == "add_column"] == [
        ("compilations", "plan_family", True),
        ("compilations", "compiler", True),
        ("compilations", "template_id", True),
    ]
    assert isinstance(calls[0][4], String) and calls[0][4].length == 32
    assert isinstance(calls[1][4], String) and calls[1][4].length == 32
    assert isinstance(calls[2][4], postgresql.UUID)
    assert ("create_index", "ix_compilations_plan_family", "compilations", ["plan_family"]) in calls
    assert ("create_index", "ix_compilations_compiler", "compilations", ["compiler"]) in calls
    assert ("create_index", "ix_compilations_template_id", "compilations", ["template_id"]) in calls
    assert (
        "create_index",
        "idx_compilations_latency_created",
        "compilations",
        ["status", "created_at"],
    ) in calls

    calls.clear()
    migration.downgrade()
    assert calls == [
        ("drop_index", "idx_compilations_latency_created", "compilations"),
        ("drop_index", "ix_compilations_template_id", "compilations"),
        ("drop_index", "ix_compilations_compiler", "compilations"),
        ("drop_index", "ix_compilations_plan_family", "compilations"),
        ("drop_column", "compilations", "template_id"),
        ("drop_column", "compilations", "compiler"),
        ("drop_column", "compilations", "plan_family"),
    ]


def test_compilation_model_declares_nullable_latency_dimensions():
    from app.database.models import Compilation

    columns = Compilation.__table__.c
    for name in ("plan_family", "compiler", "template_id"):
        assert columns[name].nullable is True
    assert isinstance(columns.plan_family.type, String)
    assert columns.plan_family.type.length == 32
    assert isinstance(columns.compiler.type, String)
    assert columns.compiler.type.length == 32
    assert isinstance(columns.template_id.type, postgresql.UUID)
    # Attribution must never carry document content or error text.
    for name in ("error_message", "pdf_path"):
        assert name in columns
    assert isinstance(columns.error_message.type, Text)
    assert isinstance(columns.created_at.type, DateTime)
