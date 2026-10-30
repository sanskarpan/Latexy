"""Operator-only, primary-frozen containment for Redis recovery.

This helper never selects a replacement backend. It validates a held Modal
deployment identity before opening the database, then freezes the durable
authority row at one expected generation. It does not contact Redis or a
provider API.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Callable
from uuid import UUID

from app.core.deployment_hold import (
    DEFAULT_MODAL_REDIS_SECRET_NAME,
    modal_redis_secret_name,
)
from app.core.redis_authority import (
    RedisAuthorityState,
    freeze_primary_authority,
    read_redis_authority,
)
from app.core.serve_identity import redis_binding_fingerprint

_SHA = re.compile(r"^[0-9a-f]{40}$")
_SAFE_ERROR = "Primary recovery quarantine could not be confirmed."


class RedisRecoveryQuarantineError(RuntimeError):
    """A fixed-message, safe-to-report quarantine failure."""

    def __init__(self) -> None:
        super().__init__(_SAFE_ERROR)


def _validated_identity(
    environ: Mapping[str, str], source_revision: str, freeze_id: str,
    expected_generation: int,
) -> tuple[UUID, str]:
    """Validate all operator selectors before the first database call."""
    if environ.get("MODAL_ENVIRONMENT") != "main":
        raise RedisRecoveryQuarantineError()
    if environ.get("MODAL_DEPLOYMENT_TRAFFIC_HOLD") != "true":
        raise RedisRecoveryQuarantineError()
    try:
        label = modal_redis_secret_name(environ.get("MODAL_REDIS_SECRET_NAME"))
    except (TypeError, ValueError):
        raise RedisRecoveryQuarantineError() from None
    if label == DEFAULT_MODAL_REDIS_SECRET_NAME:
        raise RedisRecoveryQuarantineError()
    baked_revision = environ.get("DEPLOY_SHA")
    if (
        not isinstance(source_revision, str)
        or not _SHA.fullmatch(source_revision)
        or baked_revision != source_revision
    ):
        raise RedisRecoveryQuarantineError()
    if isinstance(expected_generation, bool) or not isinstance(expected_generation, int) or expected_generation < 0:
        raise RedisRecoveryQuarantineError()
    try:
        operation_id = UUID(freeze_id)
    except (TypeError, ValueError, AttributeError):
        raise RedisRecoveryQuarantineError() from None
    if str(operation_id) != freeze_id:
        raise RedisRecoveryQuarantineError()
    return operation_id, label


def _matches_quarantine(
    state: RedisAuthorityState,
    *,
    freeze_id: UUID,
    expected_generation: int,
) -> bool:
    return (
        state.phase == "frozen"
        and state.active_backend == "primary"
        and state.generation == expected_generation + 1
        and state.freeze_reason == "quota_exhausted"
        and state.freeze_id == str(freeze_id)
    )


def _proof(state: RedisAuthorityState, *, source_revision: str, freeze_id: UUID, environ: Mapping[str, str]) -> dict[str, Any]:
    fingerprint = redis_binding_fingerprint(environ)
    if fingerprint is None:
        raise RedisRecoveryQuarantineError()
    return {
        "source_sha": source_revision,
        "phase": "frozen",
        "active_backend": "primary",
        "generation": state.generation,
        "freeze_id": str(freeze_id),
        "secret_label_fingerprint": fingerprint,
        "jobs_allowed": False,
        "newauthority_enabled": False,
        "limits_unknown": True,
    }


async def freeze_primary_for_recovery(
    session_factory: Callable[[], Any],
    *,
    environ: Mapping[str, str],
    source_revision: str,
    freeze_id: str,
    expected_generation: int = 0,
) -> dict[str, Any]:
    """Freeze primary authority and verify uncertain results using a fresh session.

    The caller supplies an async SQLAlchemy session factory. This function does
    not perform DDL, Redis operations, or any provider operation. Existing
    matching freezes are idempotent; every other state is denied.
    """
    operation_id, _label = _validated_identity(
        environ, source_revision, freeze_id, expected_generation,
    )
    try:
        async with session_factory() as session:
            state = await read_redis_authority(session)
            if _matches_quarantine(
                state, freeze_id=operation_id, expected_generation=expected_generation,
            ):
                return _proof(
                    state, source_revision=source_revision, freeze_id=operation_id, environ=environ,
                )
            if state.phase != "legacy" or state.generation != expected_generation:
                raise RedisRecoveryQuarantineError()
            frozen = await freeze_primary_authority(
                session,
                expected_generation=expected_generation,
                reason="quota_exhausted",
                freeze_id=operation_id,
            )
            await session.commit()
            return _proof(
                frozen, source_revision=source_revision, freeze_id=operation_id, environ=environ,
            )
    except RedisRecoveryQuarantineError:
        raise
    except Exception:
        # The write may have committed even if the client lost its response.
        # Read in a new session and accept only the complete operation identity.
        try:
            async with session_factory() as readback_session:
                readback = await read_redis_authority(readback_session)
        except Exception:
            raise RedisRecoveryQuarantineError() from None
        if not _matches_quarantine(
            readback, freeze_id=operation_id, expected_generation=expected_generation,
        ):
            raise RedisRecoveryQuarantineError() from None
        return _proof(
            readback, source_revision=source_revision, freeze_id=operation_id, environ=environ,
        )
