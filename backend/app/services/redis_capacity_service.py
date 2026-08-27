"""Provider-level Redis request-capacity monitoring.

Database REST credentials can execute commands but cannot read account quota
usage. Upstash exposes the authoritative monthly request count and limit through
its Developer API, which uses separate read-only management credentials. This
service keeps those concerns separate and never returns credential material.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from ..core.config import settings
from ..core.logging import get_logger
from ..core.observability import set_redis_capacity_metrics

logger = get_logger(__name__)

_UPSTASH_API_BASE = "https://api.upstash.com/v2"


@dataclass(frozen=True)
class RedisCapacitySnapshot:
    provider: str
    status: str
    configured: bool
    checked_at: str | None = None
    monthly_requests: int | None = None
    request_limit: int | None = None
    utilization_ratio: float | None = None

    def public_dict(self) -> dict:
        """Return only operational data safe for the public health endpoint."""
        return {key: value for key, value in asdict(self).items() if value is not None}


def _upstash_host_slugs() -> set[str]:
    slugs: set[str] = set()
    for raw_url in (settings.REDIS_URL, settings.REDIS_CACHE_URL):
        hostname = (urlparse(raw_url).hostname or "").lower()
        if hostname.endswith(".upstash.io"):
            slugs.add(hostname.split(".", 1)[0])
    return slugs


def _endpoint_slug(endpoint: object) -> str:
    raw = str(endpoint or "").strip().lower()
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"https://{raw}"
    hostname = urlparse(raw).hostname or ""
    return hostname.split(".", 1)[0]


class RedisCapacityService:
    """Fetch and cache the authoritative Upstash monthly request utilization."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._cached: RedisCapacitySnapshot | None = None
        self._cache_until = 0.0

    @staticmethod
    def _configured() -> bool:
        return all((
            settings.UPSTASH_MANAGEMENT_EMAIL,
            settings.UPSTASH_MANAGEMENT_API_KEY,
            settings.UPSTASH_REDIS_DATABASE_ID,
        ))

    async def snapshot(self, *, force: bool = False) -> RedisCapacitySnapshot:
        now = time.monotonic()
        if not force and self._cached is not None and now < self._cache_until:
            return self._cached

        async with self._lock:
            now = time.monotonic()
            if not force and self._cached is not None and now < self._cache_until:
                return self._cached
            result = await self._fetch()
            self._cached = result
            self._cache_until = now + settings.REDIS_CAPACITY_CACHE_SECONDS
            return result

    async def _fetch(self) -> RedisCapacitySnapshot:
        host_slugs = _upstash_host_slugs()
        if not host_slugs:
            return RedisCapacitySnapshot(
                provider="redis",
                status="not_applicable",
                configured=self._configured(),
            )
        if not self._configured():
            return RedisCapacitySnapshot(
                provider="upstash",
                status="unconfigured",
                configured=False,
            )
        if len(host_slugs) != 1:
            logger.error("Redis capacity monitor covers one database but queue/cache use different Upstash hosts")
            return RedisCapacitySnapshot(
                provider="upstash",
                status="misconfigured",
                configured=True,
            )

        database_id = settings.UPSTASH_REDIS_DATABASE_ID
        try:
            async with httpx.AsyncClient(
                base_url=_UPSTASH_API_BASE,
                auth=(settings.UPSTASH_MANAGEMENT_EMAIL, settings.UPSTASH_MANAGEMENT_API_KEY),
                headers={"User-Agent": "latexy-redis-capacity-monitor"},
                timeout=8.0,
            ) as client:
                database_response, stats_response = await asyncio.gather(
                    client.get(f"/redis/database/{database_id}"),
                    client.get(f"/redis/stats/{database_id}"),
                )
                database_response.raise_for_status()
                stats_response.raise_for_status()
                database = database_response.json()
                stats = stats_response.json()
        except Exception as exc:
            logger.warning(
                "Upstash capacity metadata unavailable (%s)",
                type(exc).__name__,
            )
            return RedisCapacitySnapshot(
                provider="upstash",
                status="unavailable",
                configured=True,
            )

        if _endpoint_slug(database.get("endpoint")) not in host_slugs:
            logger.error("Upstash capacity database ID does not match the configured Redis host")
            return RedisCapacitySnapshot(
                provider="upstash",
                status="misconfigured",
                configured=True,
            )

        if str(database.get("state", "")).lower() != "active":
            return RedisCapacitySnapshot(
                provider="upstash",
                status="unavailable",
                configured=True,
            )

        try:
            monthly_requests = max(0, int(stats["total_monthly_requests"]))
            request_limit = max(0, int(database["db_request_limit"]))
        except (KeyError, TypeError, ValueError):
            logger.warning("Upstash capacity metadata omitted required numeric fields")
            return RedisCapacitySnapshot(
                provider="upstash",
                status="unavailable",
                configured=True,
            )

        ratio = monthly_requests / request_limit if request_limit else 0.0
        if request_limit and monthly_requests >= request_limit:
            status = "exhausted"
        elif ratio >= settings.REDIS_CAPACITY_CRITICAL_RATIO:
            status = "critical"
        elif ratio >= settings.REDIS_CAPACITY_WARNING_RATIO:
            status = "warning"
        else:
            status = "ok"

        set_redis_capacity_metrics(monthly_requests, request_limit)
        return RedisCapacitySnapshot(
            provider="upstash",
            status=status,
            configured=True,
            checked_at=datetime.now(timezone.utc).isoformat(),
            monthly_requests=monthly_requests,
            request_limit=request_limit,
            utilization_ratio=round(ratio, 6),
        )


redis_capacity_service = RedisCapacityService()
