"""Feature flag service — runtime control of platform restrictions.

Two access modes:
- Async get_flag(key, db): DB-backed with 60s in-memory TTL cache. Used by FastAPI routes.
- Sync sync_get_flag(key): reads Redis key latexy:feature_flags:{key} ("1"/"0").
  Used by Celery workers. Falls back to True if Redis unavailable or key absent.

On update: write DB → set Redis key → clear in-memory cache.
"""

from __future__ import annotations

import logging
import time
from typing import Dict, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import FeatureFlag

logger = logging.getLogger(__name__)

# In-memory cache: key → (enabled: bool, expires_at: float)
_cache: Dict[str, Tuple[bool, float]] = {}
_CACHE_TTL = 60  # seconds

REDIS_KEY_PREFIX = "latexy:feature_flags:"


class FeatureFlagService:
    # ---------------------------------------------------------------- #
    #  Async access (FastAPI routes)                                    #
    # ---------------------------------------------------------------- #

    async def get_flag(self, key: str, db: AsyncSession) -> bool:
        """Return whether the flag is enabled. Uses in-memory TTL cache."""
        now = time.monotonic()
        cached = _cache.get(key)
        if cached and cached[1] > now:
            return cached[0]

        try:
            result = await db.execute(
                select(FeatureFlag.enabled).where(FeatureFlag.key == key)
            )
            row = result.scalar_one_or_none()
            enabled = row if row is not None else True  # default safe
            _cache[key] = (enabled, now + _CACHE_TTL)
            return enabled
        except Exception as exc:
            logger.warning("feature_flag_service.get_flag DB error", extra={"error_type": type(exc).__name__})
            try:
                await db.rollback()
            except Exception:
                pass
            return True  # fail open

    async def get_all_flags(self, db: AsyncSession):
        """Return all FeatureFlag rows."""
        result = await db.execute(select(FeatureFlag))
        return result.scalars().all()

    async def update_flag(self, key: str, enabled: bool, db: AsyncSession) -> FeatureFlag:
        """Update a flag in DB, push to Redis, and clear in-memory cache."""
        result = await db.execute(
            select(FeatureFlag).where(FeatureFlag.key == key)
        )
        flag = result.scalar_one_or_none()
        if flag is None:
            raise KeyError(f"Unknown feature flag: {key!r}")

        flag.enabled = enabled
        await db.commit()
        await db.refresh(flag)

        # Clear local cache immediately
        _cache.pop(key, None)

        # Push to Redis so Celery workers pick it up without waiting
        await self._push_to_redis(key, enabled)

        return flag

    # ---------------------------------------------------------------- #
    #  Sync access (Celery workers)                                     #
    # ---------------------------------------------------------------- #

    def sync_get_flag(self, key: str) -> bool:
        """Read flag from Redis (sync). Falls back to True if unavailable.

        Tries the worker-local Redis client first (Celery context), then falls
        back to a fresh sync connection using settings.REDIS_URL so callers
        outside Celery workers (e.g. FastAPI route helpers) also get live values.
        """
        redis_key = f"{REDIS_KEY_PREFIX}{key}"

        # 1. Worker-local client (Celery context)
        try:
            from ..workers.event_publisher import get_worker_redis
            r = get_worker_redis()
            val = r.get(redis_key)
            if val is None:
                return True
            return val == "1"
        except Exception:
            pass

        # 2. Direct sync connection (FastAPI / non-worker context)
        r = None
        try:
            import redis as _redis

            from ..core.config import settings
            r = _redis.from_url(settings.REDIS_URL, decode_responses=True,
                                socket_connect_timeout=1, socket_timeout=1)
            val = r.get(redis_key)
            if val is None:
                return True
            return val == "1"
        except Exception as exc:
            logger.debug("sync_get_flag Redis error", extra={"error_type": type(exc).__name__})
            return True  # fail open
        finally:
            if r is not None:
                try:
                    r.close()
                except Exception as exc:
                    logger.debug("sync_get_flag Redis close error", extra={"error_type": type(exc).__name__})

    async def _push_to_redis(self, key: str, enabled: bool) -> None:
        """Write flag value to Redis (async, best-effort)."""
        r = None
        try:
            import redis.asyncio as aioredis

            from ..core.config import settings
            r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            await r.set(f"{REDIS_KEY_PREFIX}{key}", "1" if enabled else "0")
        except Exception as exc:
            logger.debug("_push_to_redis error", extra={"error_type": type(exc).__name__})
        finally:
            if r is not None:
                try:
                    await r.aclose()
                except Exception as exc:
                    logger.debug("_push_to_redis Redis close error", extra={"error_type": type(exc).__name__})


# Module-level singleton
feature_flag_service = FeatureFlagService()
