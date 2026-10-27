"""Primary-only freeze control and fail-closed admission checks.

Admission callers read the singleton control row before starting work. This is
not an atomic reservation and does not prevent a coordinator from freezing just
after a successful read. The module deliberately has no promotion,
backup-client construction, or failback function; those operations require
migrated quotas, consume-once state, job/outbox reconciliation and fleet-wide
generation fencing. A failed or ambiguous freeze transaction must be read back
before retry; callers must not assume it failed or succeeded.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

from sqlalchemy import text

_REASONS = frozenset({"quota_exhausted", "connection_unavailable", "manual"})
_ADMISSION_BLOCKED_MESSAGE = "Primary resource authority is frozen or unavailable."
_AUTHORITY_READ_TIMEOUT_SECONDS = 5.0
_DATABASE_SCHEMES = frozenset({
    "postgres", "postgresql", "postgresql+asyncpg", "postgresql+psycopg2",
})
_ISOLATED_TEST_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "postgres"})
_LOOPBACK_DATABASE_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "postgres"})


class AuthorityStateUnavailable(RuntimeError):
    """The durable state cannot be read; admission must stay fail-closed."""


class StaleAuthorityGeneration(RuntimeError):
    """Another coordinator changed or froze the authority first."""


class AuthorityAdmissionBlocked(RuntimeError):
    """Primary work admission is frozen or authority state cannot be read."""

    def __init__(self) -> None:
        super().__init__(_ADMISSION_BLOCKED_MESSAGE)


@dataclass(frozen=True)
class RedisAuthorityState:
    generation: int
    phase: str
    active_backend: str
    freeze_reason: str | None
    freeze_id: str | None


class _Session(Protocol):
    async def execute(self, statement: object, parameters: dict | None = None): ...


def _state(row: object) -> RedisAuthorityState:
    if row is None:
        raise AuthorityStateUnavailable("Redis authority row is missing")
    mapping = row._mapping
    state = RedisAuthorityState(
        generation=int(mapping["generation"]),
        phase=str(mapping["phase"]),
        active_backend=str(mapping["active_backend"]),
        freeze_reason=mapping["freeze_reason"],
        freeze_id=mapping["freeze_id"],
    )
    if (
        state.generation < 0
        or state.phase not in {"legacy", "frozen"}
        or state.active_backend != "primary"
        or (state.phase == "legacy" and (state.freeze_reason is not None or state.freeze_id is not None))
        or (state.phase == "frozen" and (state.freeze_reason is None or state.freeze_id is None))
    ):
        raise AuthorityStateUnavailable("Redis authority row is incompatible")
    return state


async def read_redis_authority(session: _Session) -> RedisAuthorityState:
    """Read the durable record; never synthesize a healthy default on failure."""
    result = await session.execute(text(
        "SELECT generation, phase, active_backend, freeze_reason, freeze_id "
        "FROM redis_authority_control WHERE id = 1"
    ))
    return _state(result.first())


def _database_parts(database_url: str) -> tuple[str, str, str]:
    """Return safe scheme/host/database components or reject the URL shape."""
    if not isinstance(database_url, str) or not database_url or len(database_url) > 8192:
        raise ValueError("database URL rejected")
    try:
        parsed = urlsplit(database_url)
        scheme = parsed.scheme.lower()
        host = (parsed.hostname or "").lower()
        database = parsed.path.removeprefix("/")
        if (
            scheme not in _DATABASE_SCHEMES
            or not host
            or not database
            or "/" in database
            or parsed.fragment
        ):
            raise ValueError
        _ = parsed.port
    except Exception:
        raise ValueError("database URL rejected") from None
    return scheme, host, database


def authority_admission_guard_required(environment: str | None, database_url: str | None) -> bool:
    """Skip the guard only for explicitly isolated local test databases.

    This policy is pure so callers can decide whether an async database session
    needs a guard without importing settings in this module.
    """
    if not isinstance(environment, str) or environment.strip().lower() != "test":
        return True
    if not isinstance(database_url, str):
        return True
    try:
        _scheme, host, database = _database_parts(database_url)
    except ValueError:
        return True
    database_lower = database.lower()
    isolated_name = database_lower in {"test", "testing"} or database_lower.endswith("_test")
    return not (host in _ISOLATED_TEST_HOSTS and isolated_name)


async def require_primary_authority_active(session: _Session) -> RedisAuthorityState:
    """Require a fresh legacy-primary state; missing, frozen, or unreadable blocks."""
    try:
        async with asyncio.timeout(_AUTHORITY_READ_TIMEOUT_SECONDS):
            state = await read_redis_authority(session)
        if state.phase != "legacy" or state.active_backend != "primary":
            raise AuthorityAdmissionBlocked()
        return state
    except AuthorityAdmissionBlocked:
        raise
    except Exception:
        raise AuthorityAdmissionBlocked() from None


def _sync_postgres_url(database_url: str) -> str:
    _scheme, host, _database = _database_parts(database_url)
    parsed = urlsplit(database_url)
    try:
        query_items = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        raise ValueError("database URL query rejected") from None
    query: dict[str, str] = {}
    for key, value in query_items:
        if key not in {"ssl", "sslmode", "channel_binding"} or key in query or not value:
            raise ValueError("database URL query rejected")
        query[key] = value.lower()

    channel_binding = query.get("channel_binding")
    if channel_binding is not None and channel_binding != "require":
        raise ValueError("database URL channel binding mode rejected")

    ssl = query.pop("ssl", None)
    sslmode = query.get("sslmode")
    if ssl is not None and sslmode is not None and ssl != sslmode:
        raise ValueError("database URL SSL options conflict")
    mode = sslmode or ssl or "require"
    if mode not in {"require", "verify-ca", "verify-full"}:
        raise ValueError("database URL SSL mode rejected")
    if sslmode is not None or ssl is not None or host not in _LOOPBACK_DATABASE_HOSTS:
        query["sslmode"] = mode
    # SQLAlchemy async URLs may spell this `ssl=require`; native libpq uses
    # `sslmode`. For remote hosts, enforce TLS when absent. For the explicitly
    # loopback/internal PostgreSQL hosts used by local DBs, preserve libpq's
    # existing default when no TLS parameter was configured; this does not skip
    # the authority read. Weak explicit modes remain rejected everywhere.
    return urlunsplit(("postgresql", parsed.netloc, parsed.path, urlencode(query), ""))


def require_primary_authority_active_sync() -> RedisAuthorityState | None:
    """Synchronously require fresh primary state for worker/producers.

    Only an isolated local test database may skip the check. Settings and
    psycopg2 are imported lazily, and every database failure is sanitized.
    """
    try:
        from .config import settings

        environment = settings.ENVIRONMENT
        database_url = settings.DATABASE_URL
        if not authority_admission_guard_required(environment, database_url):
            return None
        native_url = _sync_postgres_url(database_url)
        import psycopg2

        connection = psycopg2.connect(native_url, connect_timeout=5)
        cursor = None
        try:
            connection.set_session(readonly=True, autocommit=False)
            cursor = connection.cursor()
            cursor.execute("SET LOCAL statement_timeout = '5s'")
            cursor.execute("SET LOCAL lock_timeout = '2s'")
            cursor.execute("SHOW transaction_read_only")
            read_only_value = cursor.fetchone()
            if not read_only_value or str(read_only_value[0]).lower() != "on":
                raise AuthorityAdmissionBlocked()
            cursor.execute(
                "SELECT generation, phase, active_backend, freeze_reason, freeze_id "
                "FROM redis_authority_control WHERE id = 1"
            )
            values = cursor.fetchone()
            if values is None:
                raise AuthorityAdmissionBlocked()
            row = type("AuthorityRow", (), {
                "_mapping": dict(zip(
                    ("generation", "phase", "active_backend", "freeze_reason", "freeze_id"),
                    values,
                ))
            })()
            state = _state(row)
            if state.phase != "legacy" or state.active_backend != "primary":
                raise AuthorityAdmissionBlocked()
            return state
        finally:
            try:
                connection.rollback()
            except Exception:
                pass
            if cursor is not None:
                try:
                    cursor.close()
                except Exception:
                    pass
            try:
                connection.close()
            except Exception:
                pass
    except AuthorityAdmissionBlocked:
        raise
    except Exception:
        raise AuthorityAdmissionBlocked() from None


async def freeze_primary_authority(
    session: _Session, *, expected_generation: int, reason: str, freeze_id: UUID,
) -> RedisAuthorityState:
    """Atomically reserve one new generation without selecting a backup.

    The caller owns the database transaction and must commit it before using
    the returned generation.  The conditional UPDATE serializes simultaneous
    coordinators; a stale attempt never increments or changes routing.
    """
    if isinstance(expected_generation, bool) or not isinstance(expected_generation, int) or expected_generation < 0:
        raise ValueError("expected_generation must be a nonnegative integer")
    if reason not in _REASONS:
        raise ValueError("unsupported freeze reason")
    if not isinstance(freeze_id, UUID):
        raise ValueError("freeze_id must be a UUID")
    result = await session.execute(text(
        "UPDATE redis_authority_control "
        "SET generation = generation + 1, phase = 'frozen', "
        "freeze_reason = :reason, freeze_id = :freeze_id, updated_at = CURRENT_TIMESTAMP "
        "WHERE id = 1 AND generation = :expected AND phase = 'legacy' "
        "RETURNING generation, phase, active_backend, freeze_reason, freeze_id"
    ), {"expected": expected_generation, "reason": reason, "freeze_id": str(freeze_id)})
    row = result.first()
    if row is None:
        raise StaleAuthorityGeneration("Redis authority is already frozen or changed")
    return _state(row)
