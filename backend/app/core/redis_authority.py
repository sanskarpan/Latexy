"""Durable, primary-only freeze primitive for a future Redis cutover.

The current application does not call this module.  It deliberately has no
promotion, backup-client construction, or failback function: those operations
require migrated quotas, consume-once state, job/outbox reconciliation and
fleet-wide generation fencing.  A failed or ambiguous database transaction must
be read back before retry; callers must not assume it failed or succeeded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import text

_REASONS = frozenset({"quota_exhausted", "connection_unavailable", "manual"})


class AuthorityStateUnavailable(RuntimeError):
    """The durable state cannot be read; admission must stay fail-closed."""


class StaleAuthorityGeneration(RuntimeError):
    """Another coordinator changed or froze the authority first."""


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
