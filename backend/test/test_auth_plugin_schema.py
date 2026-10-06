"""Runtime assertions for the Better Auth 1.6.25 plugin tables.

These tables are outside SQLAlchemy's application models, so migration tests
must inspect the live PostgreSQL catalog rather than only importing metadata.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


async def test_better_auth_two_factor_schema_and_sensitive_indexes(test_engine):
    async with test_engine.connect() as connection:
        columns = (
            await connection.execute(
                text(
                    """
                    SELECT column_name, data_type
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'twoFactor'
                      AND column_name IN ('secret', 'backupCodes')
                    """
                )
            )
        ).all()
        assert dict(columns) == {'secret': 'text', 'backupCodes': 'text'}

        indexes = set(
            (
                await connection.execute(
                    text(
                        """
                        SELECT indexname
                        FROM pg_indexes
                        WHERE schemaname = 'public'
                          AND tablename = 'twoFactor'
                          AND indexname IN ('idx_two_factor_secret', 'idx_two_factor_user_id')
                        """
                    )
                )
            ).scalars()
        )
        assert indexes == {'idx_two_factor_secret', 'idx_two_factor_user_id'}

        # Schema-only assertions are not enough: the previous test passed when
        # no setup rows existed, so it never demonstrated that plaintext could
        # not be persisted. The migration now enforces the Better Auth
        # encrypted representation at the database boundary. Exercise the
        # live constraint with a savepoint so this test leaves no row behind.
        constraints = set(
            (
                await connection.execute(
                    text(
                        """
                        SELECT c.conname
                        FROM pg_constraint c
                        JOIN pg_class t ON t.oid = c.conrelid
                        WHERE t.relname = 'twoFactor'
                          AND c.conname IN (
                            'ck_two_factor_backup_codes_encrypted',
                            'ck_two_factor_secret_encrypted'
                          )
                        """
                    )
                )
            ).scalars()
        )
        assert constraints == {
            'ck_two_factor_backup_codes_encrypted',
            'ck_two_factor_secret_encrypted',
        }
        savepoint = await connection.begin_nested()
        try:
            with pytest.raises(IntegrityError):
                await connection.execute(
                    text(
                        """
                        INSERT INTO "twoFactor"
                          (id, "userId", secret, "backupCodes")
                        VALUES
                          ('test_plaintext_two_factor', 'test_plaintext_user', 'ciphertext', '[\"plain-code\"]')
                        """
                    )
                )
        finally:
            await savepoint.rollback()

        savepoint = await connection.begin_nested()
        try:
            with pytest.raises(IntegrityError):
                await connection.execute(
                    text(
                        """
                        INSERT INTO "twoFactor"
                          (id, "userId", secret, "backupCodes")
                        VALUES
                          (
                            'test_plaintext_totp_secret',
                            'test_plaintext_user',
                            'PLAINTEXT-TOTP-SEED',
                            repeat('aa', 32)
                          )
                        """
                    )
                )
        finally:
            await savepoint.rollback()

        # A short hexadecimal lookalike is not a valid XChaCha ciphertext.
        # This prevents values such as a hex-only plaintext seed from passing
        # the format check merely because they use a restricted alphabet.
        savepoint = await connection.begin_nested()
        try:
            with pytest.raises(IntegrityError):
                await connection.execute(
                    text(
                        """
                        INSERT INTO "twoFactor"
                          (id, "userId", secret, "backupCodes")
                        VALUES
                          ('test_short_hex_secret', 'test_plaintext_user', 'deadbeef', repeat('aa', 32))
                        """
                    )
                )
        finally:
            await savepoint.rollback()

        savepoint = await connection.begin_nested()
        try:
            with pytest.raises(IntegrityError):
                await connection.execute(
                    text(
                        """
                        INSERT INTO "twoFactor"
                          (id, "userId", secret, "backupCodes")
                        VALUES
                          ('test_short_hex_backup', 'test_plaintext_user', repeat('aa', 32), 'deadbeef')
                        """
                    )
                )
        finally:
            await savepoint.rollback()

        # A real setup row is produced by the Better Auth endpoint. If this
        # isolated database has one, ensure its backup-code payload is not the
        # plaintext JSON array that older plugin configuration stored.
        payloads = (
            await connection.execute(
                text('SELECT "backupCodes" FROM "twoFactor" WHERE "backupCodes" IS NOT NULL')
            )
        ).scalars()
        for payload in payloads:
            assert not payload.startswith('[')
