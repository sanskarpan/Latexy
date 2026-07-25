"""Shared entitlement test-isolation helpers.

The Admin Control Plane has GLOBAL mutable state that leaks across tests:

  * ``plan_features`` rows (per-plan matrix) in the shared test DB,
  * ``feature_flags`` kill-switch rows for gateable features in the test DB,
  * the module-level ``entitlement_service._cache`` (60s TTL blob cache),
  * the Redis JSON blob ``latexy:entitlements``.

Any test that disables a feature MUST rely on the reset performed here so the
rest of the suite always starts from a clean, all-enabled baseline. Mutations
in the service go through a DEDICATED session (``get_async_db_session`` on the
app's real SessionLocal — NOT the overridden ``db_session`` fixture), so the
reset must likewise commit through a real session and delete the Redis key on
the same Redis the app uses (``settings.REDIS_URL``).
"""

from __future__ import annotations

from sqlalchemy import text

from app.core.feature_registry import gateable_keys


async def reset_entitlements_baseline() -> None:
    """Restore the all-enabled baseline for every entitlement axis.

    * ``plan_features.enabled = true`` for all rows.
    * gateable ``feature_flags.enabled = true`` (kill-switches re-enabled).
    * clears the in-process ``entitlement_service`` cache.
    * deletes the Redis ``latexy:entitlements`` blob.

    Uses a real committed session (the app SessionLocal via
    ``get_async_db_session``) so reads across the suite see committed data.
    """
    from app.database.connection import get_async_db_session
    from app.services.entitlement_service import (
        REDIS_BLOB_KEY,
        _clear_cache,
        entitlement_service,  # noqa: F401  (imported for clarity / future use)
    )

    gateable = list(gateable_keys())

    # 1. DB: reset the matrix + gateable kill-switches to enabled, committed.
    async with get_async_db_session() as db:
        await db.execute(text("UPDATE plan_features SET enabled = true WHERE enabled = false"))
        if gateable:
            await db.execute(
                text(
                    "UPDATE feature_flags SET enabled = true "
                    "WHERE enabled = false AND key = ANY(:keys)"
                ),
                {"keys": gateable},
            )
        await db.commit()

    # 2. In-process cache: drop the stale blob so the next read rebuilds.
    _clear_cache()

    # 3. Redis blob: delete so sync/async readers rebuild from the clean DB.
    try:
        import redis as _redis

        from app.core.config import settings

        r = _redis.from_url(settings.REDIS_URL, decode_responses=True)
        r.delete(REDIS_BLOB_KEY)
        r.close()
    except Exception:
        # Best-effort — the cache clear + DB reset already restore baseline.
        pass
