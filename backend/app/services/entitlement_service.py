"""Entitlement service — feature access resolution for the Admin Control Plane.

Source of truth = DB (feature_flags kill-switches + plan_features matrix).
Fast propagation = a single Redis JSON blob ``latexy:entitlements``:

    {"kill": {key: bool}, "matrix": {family: {key: bool}}}

Access modes (mirroring feature_flag_service):
- Async ``has_feature`` / ``get_state`` / mutations: DB-backed with a 60s
  in-process TTL cache on the Redis blob. Used by FastAPI routes.
- Sync ``sync_has_feature``: reads the Redis blob (workers, no user context).

Fail-OPEN on any infra error (return True / allow) — consistent with the
existing feature flag service.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import resolve_plan_family
from ..core.feature_registry import (
    FEATURE_REGISTRY,
    PLAN_FAMILIES,
    is_gateable,
)
from ..database.models import FeatureFlag, PlanFeature, User

logger = logging.getLogger(__name__)

REDIS_BLOB_KEY = "latexy:entitlements"
_CACHE_TTL = 60  # seconds

# In-process cache of the parsed blob: (blob: dict, expires_at: float)
_cache: Optional[tuple[dict, float]] = None

_ADMIN_ROLES = ("admin", "support")


class EntitlementService:
    # ---------------------------------------------------------------- #
    #  Blob (re)build + cache                                          #
    # ---------------------------------------------------------------- #

    def _empty_blob(self) -> dict:
        return {"kill": {}, "matrix": {f: {} for f in PLAN_FAMILIES}}

    async def _rebuild_redis_blob(self) -> dict:
        """Read DB state, build the entitlements blob, and push it to Redis.

        Uses a DEDICATED session (never the caller's request session) so
        entitlement reads can never touch or corrupt an in-flight request
        transaction.
        """
        from ..database.connection import get_async_db_session

        blob = self._empty_blob()
        async with get_async_db_session() as db:
            # Kill-switches (feature_flags rows whose key is a gateable feature).
            result = await db.execute(select(FeatureFlag.key, FeatureFlag.enabled))
            for key, enabled in result.all():
                if is_gateable(key):
                    blob["kill"][key] = bool(enabled)

            # Per-plan matrix.
            result = await db.execute(
                select(PlanFeature.plan_family, PlanFeature.feature_key, PlanFeature.enabled)
            )
            for family, key, enabled in result.all():
                if family in blob["matrix"] and is_gateable(key):
                    blob["matrix"][family][key] = bool(enabled)

        await self._push_to_redis(blob)
        _set_cache(blob)
        return blob

    async def _get_blob(self) -> dict:
        """Return the entitlements blob, using cache → Redis → DB rebuild."""
        now = time.monotonic()
        cached = _cache
        if cached and cached[1] > now:
            return cached[0]

        # Try Redis first (cheap, shared across processes).
        blob = await self._read_from_redis()
        if blob is not None:
            _set_cache(blob)
            return blob

        # Fall back to rebuilding from DB (dedicated session).
        return await self._rebuild_redis_blob()

    # ---------------------------------------------------------------- #
    #  Async access (FastAPI routes)                                   #
    # ---------------------------------------------------------------- #

    async def has_feature(self, key: str, *, user: Any, db: AsyncSession | None = None) -> bool:
        """Resolve whether ``user`` may access feature ``key``.

        ``user`` may be a ``User`` ORM object, a user_id string (as returned by
        ``get_current_user_required``), or None (anonymous).

        Resolution order:
          1. Unknown / non-gateable key            → True
          2. role in (admin, support)              → True (bypass)
          3. Global kill-switch off                → False
          4. matrix[resolve_plan_family(plan)][key] (default True)
        Fail-OPEN on infra error.

        NOTE: ``db`` is accepted for backwards compatibility but is NOT used for
        reads — all entitlement lookups run on a dedicated session so the
        caller's request transaction is never touched or rolled back.
        """
        # 1. Unknown or non-gateable → always allowed.
        if not is_gateable(key):
            return True

        try:
            role, plan = await self._resolve_user_role_plan(user)

            # 2. Admin / support bypass.
            if role in _ADMIN_ROLES:
                return True

            blob = await self._get_blob()
            return self._decide(blob, key, plan)
        except Exception as exc:
            logger.warning(f"entitlement_service.has_feature({key}) error: {exc}")
            return True  # fail open (never touches the caller's session)

    def _decide(self, blob: dict, key: str, plan: Optional[str]) -> bool:
        """Pure blob→bool decision (no I/O). Defaults to allowed when absent."""
        # Global kill-switch. Default enabled (True) when absent.
        if blob["kill"].get(key, True) is False:
            return False
        # Per-plan matrix. Default True when absent.
        family = resolve_plan_family(plan or "free")
        return bool(blob["matrix"].get(family, {}).get(key, True))

    async def _resolve_user_role_plan(
        self, user: Any
    ) -> tuple[Optional[str], Optional[str]]:
        """Return (role, subscription_plan) for a User object, id string, or None.

        For a user_id string, loads the row on a DEDICATED session so the
        caller's request transaction is untouched.
        """
        if user is None:
            return None, None

        # ORM object (or anything exposing the attributes).
        role = getattr(user, "role", None)
        plan = getattr(user, "subscription_plan", None)
        if role is not None or plan is not None:
            return role, plan

        # user is a user_id string → load the row on a dedicated session.
        if isinstance(user, str):
            from ..database.connection import get_async_db_session

            async with get_async_db_session() as db:
                result = await db.execute(
                    select(User.role, User.subscription_plan).where(User.id == user)
                )
                row = result.first()
            if row:
                return row[0], row[1]

        return None, None

    async def get_state(self, db: AsyncSession | None = None) -> dict:
        """Return full entitlement state for the admin API.

        Shape: {registry, kill_switches, matrix, plan_families}. Registry and
        matrix are filled with defaults (True) for anything absent in the DB.
        ``db`` is accepted for signature compatibility but unused (reads run on
        a dedicated session).
        """
        blob = await self._rebuild_redis_blob()

        registry = [
            {"key": f.key, "label": f.label, "category": f.category, "gateable": f.gateable}
            for f in FEATURE_REGISTRY
        ]

        gateable = [f.key for f in FEATURE_REGISTRY if f.gateable]
        kill_switches = {k: bool(blob["kill"].get(k, True)) for k in gateable}
        matrix = {
            family: {k: bool(blob["matrix"].get(family, {}).get(k, True)) for k in gateable}
            for family in PLAN_FAMILIES
        }

        return {
            "registry": registry,
            "kill_switches": kill_switches,
            "matrix": matrix,
            "plan_families": list(PLAN_FAMILIES),
        }

    async def set_kill_switch(self, key: str, enabled: bool, db: AsyncSession) -> None:
        """Upsert a kill-switch row, rebuild the Redis blob, and clear cache."""
        if not is_gateable(key):
            raise KeyError(f"Unknown or non-gateable feature: {key!r}")

        result = await db.execute(select(FeatureFlag).where(FeatureFlag.key == key))
        flag = result.scalar_one_or_none()
        if flag is None:
            from ..core.feature_registry import get_feature

            feature = get_feature(key)
            flag = FeatureFlag(
                key=key,
                enabled=enabled,
                label=feature.label if feature else key,
                description=feature.description if feature else None,
            )
            db.add(flag)
        else:
            flag.enabled = enabled
        await db.commit()

        _clear_cache()
        await self._rebuild_redis_blob()

    async def set_matrix_cell(
        self, family: str, key: str, enabled: bool, db: AsyncSession
    ) -> None:
        """Upsert a matrix cell, rebuild the Redis blob, and clear cache."""
        if family not in PLAN_FAMILIES:
            raise KeyError(f"Unknown plan family: {family!r}")
        if not is_gateable(key):
            raise KeyError(f"Unknown or non-gateable feature: {key!r}")

        result = await db.execute(
            select(PlanFeature).where(
                PlanFeature.plan_family == family,
                PlanFeature.feature_key == key,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = PlanFeature(plan_family=family, feature_key=key, enabled=enabled)
            db.add(row)
        else:
            row.enabled = enabled
        await db.commit()

        _clear_cache()
        await self._rebuild_redis_blob()

    async def effective_features(self, user: Any, db: AsyncSession | None = None) -> dict[str, bool]:
        """Return the per-feature allow map for a user (drives frontend gating).

        Resolves role/plan and the blob ONCE, then decides purely — avoids a
        per-feature query. ``db`` is unused (reads run on a dedicated session).
        """
        try:
            role, plan = await self._resolve_user_role_plan(user)
            bypass = role in _ADMIN_ROLES
            blob = None if bypass else await self._get_blob()
        except Exception as exc:
            logger.warning(f"entitlement_service.effective_features error: {exc}")
            bypass, blob = True, None  # fail open

        result: dict[str, bool] = {}
        for feature in FEATURE_REGISTRY:
            if not feature.gateable or bypass or blob is None:
                result[feature.key] = True
            else:
                result[feature.key] = self._decide(blob, feature.key, plan)
        return result

    # ---------------------------------------------------------------- #
    #  Sync access (Celery workers)                                    #
    # ---------------------------------------------------------------- #

    def sync_has_feature(self, key: str, plan_family: str) -> bool:
        """Worker path: resolve a feature for a plan family via the Redis blob.

        No user/admin context — workers act on a job's plan family. Fail-open.
        """
        if not is_gateable(key):
            return True

        blob = self._sync_read_from_redis()
        if blob is None:
            return True  # fail open

        try:
            if blob.get("kill", {}).get(key, True) is False:
                return False
            family = resolve_plan_family(plan_family or "free")
            return bool(blob.get("matrix", {}).get(family, {}).get(key, True))
        except Exception as exc:
            logger.debug(f"sync_has_feature({key}) blob error: {exc}")
            return True  # fail open

    # ---------------------------------------------------------------- #
    #  Redis I/O                                                       #
    # ---------------------------------------------------------------- #

    async def _read_from_redis(self) -> Optional[dict]:
        """Read + parse the entitlements blob from Redis (async). None on miss/error."""
        try:
            import redis.asyncio as aioredis

            from ..core.config import settings
            r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            raw = await r.get(REDIS_BLOB_KEY)
            await r.aclose()
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as exc:
            logger.debug(f"entitlement_service._read_from_redis error: {exc}")
            return None

    async def _push_to_redis(self, blob: dict) -> None:
        """Write the entitlements blob to Redis (async, best-effort)."""
        try:
            import redis.asyncio as aioredis

            from ..core.config import settings
            r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            await r.set(REDIS_BLOB_KEY, json.dumps(blob))
            await r.aclose()
        except Exception as exc:
            logger.debug(f"entitlement_service._push_to_redis error: {exc}")

    def _sync_read_from_redis(self) -> Optional[dict]:
        """Read + parse the entitlements blob from Redis (sync). None on miss/error."""
        # 1. Worker-local client (Celery context).
        try:
            from ..workers.event_publisher import get_worker_redis

            r = get_worker_redis()
            raw = r.get(REDIS_BLOB_KEY)
            if raw is not None:
                return json.loads(raw)
        except Exception:
            pass

        # 2. Direct sync connection (non-worker context).
        try:
            import redis as _redis

            from ..core.config import settings
            r = _redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
            raw = r.get(REDIS_BLOB_KEY)
            r.close()
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as exc:
            logger.debug(f"entitlement_service._sync_read_from_redis error: {exc}")
            return None


# ---------------------------------------------------------------------- #
#  Module-level cache helpers                                            #
# ---------------------------------------------------------------------- #

def _set_cache(blob: dict) -> None:
    global _cache
    _cache = (blob, time.monotonic() + _CACHE_TTL)


def _clear_cache() -> None:
    global _cache
    _cache = None


# Module-level singleton
entitlement_service = EntitlementService()
