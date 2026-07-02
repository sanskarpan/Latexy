"""Developer API key management and public API rate limiting."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_developer_api_daily_limit
from ..core.logging import get_logger
from ..core.redis import get_redis_cache_client
from ..database.models import DeveloperAPIKey

logger = get_logger(__name__)


class DeveloperKeyService:
    """Helpers for generating, verifying, and metering developer API keys."""

    DEFAULT_SCOPES = ["compile", "optimize", "ats", "export"]
    MAX_KEYS_PER_USER = 5

    def generate_api_key(self) -> tuple[str, str, str]:
        """Return (full_key, key_hash, key_prefix)."""
        random_part = secrets.token_urlsafe(32)
        full_key = f"lx_sk_{random_part}"
        key_hash = hashlib.sha256(full_key.encode("utf-8")).hexdigest()
        key_prefix = full_key[:16]
        return full_key, key_hash, key_prefix

    async def verify_api_key(
        self,
        key: str,
        db: AsyncSession,
    ) -> Optional[DeveloperAPIKey]:
        """Return the matching active key record if valid."""
        if not key or not key.startswith("lx_sk_"):
            return None

        key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
        result = await db.execute(
            select(DeveloperAPIKey).where(
                DeveloperAPIKey.key_hash == key_hash,
                DeveloperAPIKey.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def touch_usage(self, api_key: DeveloperAPIKey, db: AsyncSession) -> None:
        """Update key last-used timestamps and aggregate request count."""
        api_key.last_used_at = datetime.now(timezone.utc)
        api_key.request_count = int(api_key.request_count or 0) + 1
        await db.commit()

    async def consume_rate_limit(self, user_id: str, plan_id: str) -> Dict[str, Any]:
        """Atomically consume one daily request and report whether it is allowed."""
        limit = get_developer_api_daily_limit(plan_id)

        try:
            redis = await get_redis_cache_client()
            today = datetime.now(timezone.utc).strftime("%Y%m%d")
            key = f"developer_api:usage:{user_id}:{today}"
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, 86400)
            return {"allowed": count <= limit, "count": int(count), "limit": limit}
        except Exception as exc:
            # Fail CLOSED: if we cannot account for usage (Redis down), deny the
            # request rather than granting unmetered access to metered endpoints.
            logger.error(f"Developer API rate-limit unavailable (Redis error), failing closed: {exc}")
            return {"allowed": False, "count": limit, "limit": limit, "unavailable": True}

    async def get_usage_history(self, user_id: str, days: int = 7) -> list[Dict[str, Any]]:
        """Return daily public API request counts for the most recent N days."""
        history: list[Dict[str, Any]] = []

        try:
            redis = await get_redis_cache_client()
        except Exception as exc:
            logger.warning(f"Developer API usage history unavailable: {exc}")
            redis = None

        today = datetime.now(timezone.utc).date()
        for offset in range(days - 1, -1, -1):
            day = today - timedelta(days=offset)
            count = 0
            if redis is not None:
                key = f"developer_api:usage:{user_id}:{day.strftime('%Y%m%d')}"
                raw = await redis.get(key)
                count = int(raw or 0)
            history.append({"date": day.isoformat(), "count": count})

        return history


developer_key_service = DeveloperKeyService()
