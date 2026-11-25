"""Stable compile-error taxonomy: representative failures and fallback."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import String

from app.services.compile_error_taxonomy import (
    ALLOWED_COMPILE_ERROR_CLASSES,
    COMPILE_ERROR_CLASSES,
    classify_compile_error,
    normalize_compile_error_class,
)


@pytest.mark.parametrize(
    ("message", "failure_code", "expected"),
    [
        ("! Undefined control sequence.\nl.14 \\undefinedcommand", None, "syntax"),
        ("! Missing $ inserted.", "latex_error", "syntax"),
        ("! LaTeX Error: File `does-not-exist.sty' not found.", None, "missing_package"),
        ("! Font \\SomeFont not loadable: Metric (TFM) file not found.", None, "missing_package"),
        ('! Package fontspec Error: The font "Latin Modern" cannot be found.', None, "missing_package"),
        ("compile_timeout", "compile_timeout", "timeout"),
        ("Compilation timed out after 240s", None, "timeout"),
        ("engine_read_escape", "engine_read_escape", "engine"),
        ("render_pass_failed", "render_pass_failed", "engine"),
        ("pdflatex exited with code 1", None, "engine"),
        ("Compiled PDF storage failed", "pdf_storage_failure", "storage"),
        ("Compiled PDF could not be durably stored", None, "storage"),
        ("pdf_too_large", "pdf_too_large", "pdf_limit"),
        ("Compiled PDF exceeds the 20971520 byte limit", None, "pdf_limit"),
        ("Model provider returned an unexpected response", None, "unknown"),
        (None, None, "unknown"),
    ],
)
def test_classify_representative_failures(message, failure_code, expected):
    assert classify_compile_error(message, failure_code=failure_code) == expected


def test_finalization_code_wins_over_generic_message():
    assert (
        classify_compile_error(
            "! Undefined control sequence.",
            failure_code="pdf_storage_failure",
        )
        == "storage"
    )


def test_terminal_result_signals_are_bounded_and_classified():
    assert (
        classify_compile_error(
            None,
            terminal_result={
                "error": "LaTeX compilation failed",
                "error_message": "! LaTeX Error: File `missing.cls' not found.",
            },
        )
        == "missing_package"
    )
    assert (
        classify_compile_error(
            None,
            terminal_result={"error_code": "compile_timeout"},
        )
        == "timeout"
    )


def test_unknown_fallback_is_allowlisted():
    assert normalize_compile_error_class("not-a-class") == "unknown"
    assert normalize_compile_error_class(None) == "unknown"
    assert normalize_compile_error_class(" pdf_limit ") == "pdf_limit"
    assert classify_compile_error("totally unrecognized failure") in ALLOWED_COMPILE_ERROR_CLASSES
    assert set(COMPILE_ERROR_CLASSES) == ALLOWED_COMPILE_ERROR_CLASSES


def _migration():
    path = Path(__file__).parents[1] / "alembic" / "versions" / "0083_compile_error_taxonomy.py"
    spec = importlib.util.spec_from_file_location("compile_error_taxonomy_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_is_additive_and_chains_from_0082():
    migration = _migration()
    calls: list[tuple] = []

    class FakeOp:
        def add_column(self, table: str, column) -> None:
            calls.append(("add_column", table, column))

        def drop_column(self, table: str, column: str) -> None:
            calls.append(("drop_column", table, column))

        def create_check_constraint(self, name: str, table: str, condition: str) -> None:
            calls.append(("create_check_constraint", name, table, condition))

        def drop_constraint(self, name: str, table: str, type_: str) -> None:
            calls.append(("drop_constraint", name, table, type_))

        def create_index(self, name: str, table: str, columns: list[str], **kwargs) -> None:
            calls.append(("create_index", name, table, columns, kwargs))

        def drop_index(self, name: str, table_name: str) -> None:
            calls.append(("drop_index", name, table_name))

    migration.op = FakeOp()
    migration.upgrade()

    assert migration.revision == "0083_compile_error_taxonomy"
    assert migration.down_revision == "0082_signup_funnel_providers"
    added = [call for call in calls if call[0] == "add_column"]
    assert len(added) == 1
    assert added[0][1] == "compilations"
    column = added[0][2]
    assert column.name == "error_class"
    assert column.nullable is False
    assert column.server_default is not None
    assert isinstance(column.type, String) and column.type.length == 32
    assert any(call[0] == "create_check_constraint" for call in calls)
    assert any(
        call[0] == "create_index"
        and call[1] == "idx_compilations_error_class_created"
        and call[3] == ["error_class", "created_at"]
        for call in calls
    )

    calls.clear()
    migration.downgrade()
    assert [call[0] for call in calls] == [
        "drop_index",
        "drop_constraint",
        "drop_column",
    ]


def test_compilation_model_persists_only_allowlisted_classes():
    from app.database.models import Compilation

    column = Compilation.__table__.c.error_class
    assert column.nullable is False
    assert isinstance(column.type, String)
    assert column.type.length == 32
    constraints = {constraint.name for constraint in Compilation.__table__.constraints if constraint.name}
    assert "ck_compilations_error_class" in constraints


def _session_factory(rowcounts: list[int]):
    session = MagicMock()
    lookup = MagicMock()
    lookup.scalar_one_or_none.return_value = SimpleNamespace(status="processing", pdf_path=None)
    session.execute = AsyncMock(side_effect=[lookup, *[MagicMock(rowcount=rowcount) for rowcount in rowcounts]])
    session.scalar = AsyncMock(return_value=None)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    class _Factory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return session

        async def __aexit__(self, *exc):
            return False

    return _Factory(), session


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("! Undefined control sequence.", "syntax"),
        ("! LaTeX Error: File `missing.sty' not found.", "missing_package"),
        ("compile_timeout", "timeout"),
        ("engine_read_escape", "engine"),
        ("Compiled PDF storage failed", "storage"),
        ("pdf_too_large", "pdf_limit"),
        ("unrecognized compiler output", "unknown"),
    ],
)
async def test_worker_persists_allowlisted_class_at_write_time(message, expected):
    from app.workers.latex_worker import _update_compilation_record

    factory, session = _session_factory([1])
    outcome = await _update_compilation_record(
        job_id="taxonomy-write",
        status="failed",
        compilation_time=1.0,
        pdf_bytes=None,
        error_message=message,
        session_factory=factory,
    )

    assert outcome.value == "success"
    statement = session.execute.await_args_list[1].args[0]
    assert statement.compile().params["error_class"] == expected
