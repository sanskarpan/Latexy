"""Pure URL normalization and database-engine lifecycle regressions."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.engine import make_url

from app.database import connection
from app.database.urls import normalize_sync_database_url


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+asyncpg", "postgresql+psycopg2"])
def test_sync_engine_retains_installed_psycopg2_without_connecting(scheme):
    from sqlalchemy import create_engine

    raw = f"{scheme}://qa:p%40ss%2Basyncpg@localhost/latexy_test?sslmode=verify-full&application_name=unit"
    normalized = normalize_sync_database_url(raw)
    parsed = make_url(normalized)
    assert parsed.password == "p@ss+asyncpg"
    assert parsed.database == "latexy_test"
    assert parsed.query == {"sslmode": "verify-full", "application_name": "unit"}
    engine = create_engine(normalized)
    try:
        assert engine.dialect.driver == "psycopg2"
    finally:
        engine.dispose()


def test_sync_url_survives_alembic_config_interpolation():
    from alembic.config import Config

    normalized = normalize_sync_database_url("postgresql+asyncpg://qa:p%40ss%25word@localhost/latexy_test")
    config = Config()
    config.set_main_option("sqlalchemy.url", normalized.replace("%", "%%"))
    assert make_url(config.get_main_option("sqlalchemy.url")).password == "p@ss%word"


@pytest.mark.parametrize("raw", ["not-a-url-private-sentinel", "mysql://private-user:private-password@localhost/db"])
def test_sync_url_errors_do_not_expose_input(raw):
    with pytest.raises(ValueError) as error:
        normalize_sync_database_url(raw)
    assert "private" not in str(error.value)


@pytest.mark.parametrize(
    "raw_url",
    [
        "postgresql://qa:secret@db.example/latexy?channel_binding=require&sslmode=require",
        "postgresql://qa:secret@db.example/latexy?sslmode=require&channel_binding=require",
    ],
)
def test_normalize_async_database_url_handles_both_psycopg_query_orders(raw_url):
    normalized = make_url(connection.normalize_async_database_url(raw_url))

    assert normalized.drivername == "postgresql+asyncpg"
    assert normalized.query == {"ssl": "require"}


@pytest.mark.parametrize(
    ("scheme", "sslmode", "expected_ssl"),
    [
        ("postgres://", "require", "require"),
        ("postgresql://", "verify-full", "verify-full"),
        ("postgresql+psycopg2://", "verify-ca", "verify-ca"),
        ("postgresql+psycopg://", "require", "require"),
        ("postgresql+pg8000://", "verify-full", "verify-full"),
        ("postgresql+psycopg2cffi://", "verify-ca", "verify-ca"),
        ("postgresql+asyncpg://", "require", "require"),
    ],
)
def test_normalize_async_database_url_preserves_ssl_mode_across_postgres_drivers(
    scheme, sslmode, expected_ssl
):
    normalized = make_url(
        connection.normalize_async_database_url(
            f"{scheme}user:password@db.example/latexy?sslmode={sslmode}"
        )
    )

    assert normalized.drivername == "postgresql+asyncpg"
    assert normalized.query["ssl"] == expected_ssl


def test_normalize_async_database_url_preserves_existing_matching_ssl_and_other_params():
    normalized = make_url(
        connection.normalize_async_database_url(
            "postgresql://user:password@db.example/latexy"
            "?channel_binding=require&sslmode=require&ssl=require&options=-c%20search_path%3Dpublic"
            "&application_name=acceptance"
        )
    )

    assert normalized.query == {
        "ssl": "require",
        "options": "-c search_path=public",
        "application_name": "acceptance",
    }


@pytest.mark.parametrize(
    "query",
    [
        "sslmode=require&ssl=disable",
        "ssl=verify-full&sslmode=require",
        "sslmode=require&sslmode=disable",
        "ssl=require&ssl=disable",
    ],
)
def test_normalize_async_database_url_rejects_conflicting_ssl_options(query):
    with pytest.raises(ValueError, match="(?i)ssl") as error:
        connection.normalize_async_database_url(
            f"postgresql://user:password@db.example/latexy?{query}"
        )
    assert "password" not in str(error.value)


def test_normalize_async_database_url_collapses_repeated_matching_ssl_values():
    normalized = make_url(
        connection.normalize_async_database_url(
            "postgresql://user:password@db.example/latexy?ssl=require&ssl=require"
        )
    )

    assert normalized.query == {"ssl": "require"}


@pytest.mark.parametrize(
    "query",
    [
        "sslmode=",
        "ssl=",
        "sslmode=&sslmode=require",
        "ssl=&ssl=require",
    ],
)
def test_normalize_async_database_url_rejects_explicit_blank_ssl_options(query):
    with pytest.raises(ValueError, match="blank SSL") as error:
        connection.normalize_async_database_url(
            f"postgresql://user:password@db.example/latexy?{query}"
        )

    assert "password" not in str(error.value)


def test_normalize_async_database_url_never_rewrites_password_or_other_query_values():
    raw_url = (
        "postgresql://user:pwsslmode%3Drequire%26channel_binding%3Ddisable@db.example/latexy"
        "?application_name=sslmode%3Drequire%26channel_binding%3Dprefer"
        "&channel_binding=require&sslmode=verify-full"
    )
    normalized = make_url(connection.normalize_async_database_url(raw_url))

    assert normalized.password == "pwsslmode=require&channel_binding=disable"
    assert normalized.database == "latexy"
    assert normalized.query == {
        "ssl": "verify-full",
        "application_name": "sslmode=require&channel_binding=prefer",
    }


def test_normalize_async_database_url_round_trips_escaped_password_and_database_name():
    raw_url = "postgresql://user:p%40ss%3Fmode%3Drequire@db.example/latexy%2Fpreview?sslmode=require"
    normalized = make_url(connection.normalize_async_database_url(raw_url))

    assert normalized.password == "p@ss?mode=require"
    # SQLAlchemy 2.1 decodes the database component when parsing. Driver
    # conversion must retain that actual database name through a URL round trip.
    assert normalized.database == "latexy/preview"
    assert normalized.query["ssl"] == "require"


def test_normalize_async_database_url_does_not_leak_input_in_validation_errors():
    sensitive_url = "mysql://private-user:private-password@db.example/latexy"

    with pytest.raises(ValueError, match="supported PostgreSQL driver") as error:
        connection.normalize_async_database_url(sensitive_url)

    assert "private-user" not in str(error.value)
    assert "private-password" not in str(error.value)


def test_normalize_async_database_url_redacts_parser_errors(monkeypatch):
    monkeypatch.setattr(
        connection,
        "make_url",
        lambda _url: (_ for _ in ()).throw(
            ValueError("private-user:private-password malformed URL")
        ),
    )

    with pytest.raises(ValueError, match="valid SQLAlchemy URL") as error:
        connection.normalize_async_database_url(
            "postgresql://private-user:private-password@db.example/latexy"
        )

    assert "private-user" not in str(error.value)
    assert "private-password" not in str(error.value)


@pytest.mark.asyncio
async def test_init_and_close_can_reconnect_with_structurally_normalized_url(monkeypatch):
    raw_url = (
        "postgresql://qa:secret@db.example/latexy"
        "?channel_binding=require&sslmode=verify-full&application_name=acceptance"
    )
    first_engine = MagicMock()
    first_engine.dispose = AsyncMock()
    first_engine.sync_engine = MagicMock()
    second_engine = MagicMock()
    second_engine.dispose = AsyncMock()
    second_engine.sync_engine = MagicMock()
    engine_factory = MagicMock(side_effect=[first_engine, second_engine])
    session_factory = MagicMock()

    monkeypatch.setattr(connection.settings, "DATABASE_URL", raw_url)
    monkeypatch.setattr(connection.settings, "SQL_ECHO", False)
    monkeypatch.setattr(connection, "create_async_engine", engine_factory)
    monkeypatch.setattr(connection, "async_sessionmaker", session_factory)
    monkeypatch.setattr(connection, "instrument_sqlalchemy", MagicMock())
    monkeypatch.setattr(connection, "engine", None)
    monkeypatch.setattr(connection, "SessionLocal", None)

    await connection.init_db()
    first_url = engine_factory.call_args_list[0].args[0]
    assert isinstance(first_url, str)
    assert make_url(first_url).query == {
        "ssl": "verify-full",
        "application_name": "acceptance",
    }
    assert connection.engine is first_engine

    await connection.close_db()
    first_engine.dispose.assert_awaited_once_with()
    assert connection.engine is None
    assert connection.SessionLocal is None

    await connection.init_db()
    second_url = engine_factory.call_args_list[1].args[0]
    assert isinstance(second_url, str)
    assert make_url(second_url).query == {
        "ssl": "verify-full",
        "application_name": "acceptance",
    }
    assert connection.engine is second_engine

    await connection.close_db()
    second_engine.dispose.assert_awaited_once_with()
    assert connection.engine is None
    assert connection.SessionLocal is None
