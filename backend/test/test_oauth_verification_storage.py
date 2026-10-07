"""Regression coverage for Better Auth OAuth-state storage width."""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine


def _load_migration():
    path = Path(__file__).parents[1] / "alembic" / "versions" / "0059_verification_value_text.py"
    spec = importlib.util.spec_from_file_location("latexy_oauth_state_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _run_migration(sync_connection, migration, operation):
    migration.op = Operations(MigrationContext.configure(sync_connection))
    operation()


async def _set_search_path(connection, schema: str) -> None:
    await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))


def _uncached_engine(test_engine):
    # DDL/search-path tests must not poison the suite's public-table statement
    # cache with queries against a temporary table which is later dropped.
    return create_async_engine(test_engine.url.update_query_dict({"prepared_statement_cache_size": "0"}))


@pytest.mark.asyncio
async def test_0059_upgrade_and_downgrade_preserve_oauth_state_data(test_engine):
    """Exercise the real Alembic operations in an isolated PostgreSQL schema."""
    schema = f"test_oauth_state_{uuid4().hex[:12]}"
    migration = _load_migration()
    state_payload = json.dumps(
        {
            "callbackURL": "/workspace",
            "codeVerifier": "v" * 128,
            "errorURL": "/login",
            "newUserURL": "/workspace",
            "expiresAt": 1_800_000_000,
            "oauthState": "s" * 32,
        },
        separators=(",", ":"),
    )
    assert len(state_payload) > 255
    engine = _uncached_engine(test_engine)

    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.execute(
                text(
                    f'''
                    CREATE TABLE "{schema}".verification (
                        id VARCHAR(255) PRIMARY KEY,
                        identifier VARCHAR(255) NOT NULL,
                        value VARCHAR(255) NOT NULL,
                        "expiresAt" TIMESTAMPTZ NOT NULL,
                        "createdAt" TIMESTAMPTZ DEFAULT NOW(),
                        "updatedAt" TIMESTAMPTZ DEFAULT NOW()
                    )
                    '''
                )
            )

        async with engine.begin() as connection:
            await _set_search_path(connection, schema)
            await connection.execute(
                text(
                    'INSERT INTO verification (id, identifier, value, "expiresAt") '
                    "VALUES ('short-before', 'short-before', 'preserved-state', NOW())"
                )
            )
            with pytest.raises(DBAPIError, match="value too long") as failure:
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            'INSERT INTO verification (id, identifier, value, "expiresAt") '
                            "VALUES ('long-before', 'long-before', :value, NOW())"
                        ),
                        {"value": state_payload},
                    )
            assert failure.value.orig.sqlstate == "22001"
            await connection.run_sync(
                lambda sync_connection: _run_migration(sync_connection, migration, migration.upgrade)
            )

        async with engine.begin() as connection:
            await _set_search_path(connection, schema)
            assert (
                await connection.execute(text("SELECT value FROM verification WHERE id = 'short-before'"))
            ).scalar_one() == "preserved-state"
            column = (
                await connection.execute(
                    text(
                        """
                        SELECT data_type, character_maximum_length, is_nullable
                        FROM information_schema.columns
                        WHERE table_schema = :schema
                          AND table_name = 'verification'
                          AND column_name = 'value'
                        """
                    ),
                    {"schema": schema},
                )
            ).one()
            assert column == ("text", None, "NO")
            await connection.execute(
                text(
                    'INSERT INTO verification (id, identifier, value, "expiresAt") '
                    "VALUES (:id, :identifier, :value, :expires_at)"
                ),
                {
                    "id": "test_oauth_state_long",
                    "identifier": "test_oauth_state_identifier",
                    "value": state_payload,
                    "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
                },
            )

        # A downgrade must refuse rather than truncate a still-live state.
        with pytest.raises(DBAPIError, match="cannot downgrade 0059"):
            async with engine.begin() as connection:
                await _set_search_path(connection, schema)
                await connection.run_sync(
                    lambda sync_connection: _run_migration(sync_connection, migration, migration.downgrade)
                )

        async with engine.begin() as connection:
            await _set_search_path(connection, schema)
            assert (
                await connection.execute(
                    text("SELECT value FROM verification WHERE id = :id"),
                    {"id": "test_oauth_state_long"},
                )
            ).scalar_one() == state_payload
            await connection.execute(
                text("DELETE FROM verification WHERE id = :id"),
                {"id": "test_oauth_state_long"},
            )

        # Once no oversized values remain, the downgrade is safe and retains
        # the non-null contract for ordinary short verification values.
        async with engine.begin() as connection:
            await _set_search_path(connection, schema)
            await connection.execute(
                text(
                    'INSERT INTO verification (id, identifier, value, "expiresAt") '
                    "VALUES (:id, :identifier, :value, :expires_at)"
                ),
                {
                    "id": "test_oauth_state_short",
                    "identifier": "test_oauth_state_identifier",
                    "value": "short-state",
                    "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
                },
            )
            await connection.run_sync(
                lambda sync_connection: _run_migration(sync_connection, migration, migration.downgrade)
            )
            column = (
                await connection.execute(
                    text(
                        """
                        SELECT data_type, character_maximum_length, is_nullable
                        FROM information_schema.columns
                        WHERE table_schema = :schema
                          AND table_name = 'verification'
                          AND column_name = 'value'
                        """
                    ),
                    {"schema": schema},
                )
            ).one()
            assert column == ("character varying", 255, "NO")
            assert (
                await connection.execute(
                    text("SELECT value FROM verification WHERE id = :id"),
                    {"id": "test_oauth_state_short"},
                )
            ).scalar_one() == "short-state"
    finally:
        try:
            async with engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        finally:
            await engine.dispose()


@pytest.mark.parametrize(
    "destination", ["/workspace", "/workspace?next=" + "a" * 4096, "/workspace?name=" + "résumé文" * 256]
)
async def test_verification_value_accepts_serialized_oauth_state_over_255(test_engine, destination):
    """The default Better Auth database strategy must store the full state JSON."""
    row_id = f"test_oauth_state_{uuid4().hex}"
    # Failed assertions roll back the whole insert; successful runs delete the
    # unique row before committing. No persistent test verification remains.
    async with test_engine.begin() as connection:
        column = (
            await connection.execute(
                text(
                    """
                    SELECT data_type, character_maximum_length
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'verification'
                      AND column_name = 'value'
                    """
                )
            )
        ).one()
        assert column.data_type == "text"
        assert column.character_maximum_length is None

        # Keep the payload synthetic and non-sensitive while exercising the
        # same oversized JSON-string boundary that Better Auth hits in OAuth.
        state_payload = json.dumps(
            {
                "callbackURL": destination,
                "codeVerifier": "v" * 128,
                "errorURL": "/login",
                "newUserURL": "/workspace",
                "expiresAt": 1_800_000_000,
                "oauthState": "s" * 32,
            },
            separators=(",", ":"),
        )
        assert len(state_payload) > 255
        await connection.execute(
            text(
                """
                INSERT INTO verification
                  (id, identifier, value, "expiresAt")
                VALUES
                  (:id, :identifier, :value, :expires_at)
                """
            ),
            {
                "id": row_id,
                "identifier": "test_oauth_state_identifier",
                "value": state_payload,
                "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
            },
        )
        stored = await connection.execute(
            text("SELECT value FROM verification WHERE id = :id"),
            {"id": row_id},
        )
        assert stored.scalar_one() == state_payload
        await connection.execute(
            text("DELETE FROM verification WHERE id = :id"),
            {"id": row_id},
        )
