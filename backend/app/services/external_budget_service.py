"""Distributed, weighted budgets for outbound and CPU-heavy integrations."""

from __future__ import annotations

from fastapi import HTTPException, status

from ..core.logging import get_logger
from ..core.redis import get_redis_cache_client

logger = get_logger(__name__)

_CONSUME_BUDGET = """
local client_count = redis.call('INCRBY', KEYS[1], ARGV[1])
if client_count == tonumber(ARGV[1]) then
  redis.call('EXPIRE', KEYS[1], ARGV[4])
end
local global_count = redis.call('INCRBY', KEYS[2], ARGV[1])
if global_count == tonumber(ARGV[1]) then
  redis.call('EXPIRE', KEYS[2], ARGV[4])
end
if client_count > tonumber(ARGV[2]) or global_count > tonumber(ARGV[3]) then
  redis.call('DECRBY', KEYS[1], ARGV[1])
  redis.call('DECRBY', KEYS[2], ARGV[1])
  return {0, client_count, global_count}
end
return {1, client_count, global_count}
"""


async def enforce_external_budget(
    scope: str,
    *,
    client_id: str,
    cost: int,
    client_limit: int,
    global_limit: int,
    window_seconds: int,
) -> None:
    """Consume a weighted client/global budget or raise a stable 429/503.

    Both counters and the over-limit rollback happen in one Redis script, so
    horizontally scaled API containers share one authoritative allowance.
    These paths consume third-party or CPU/LLM resources and therefore fail
    closed when Redis cannot account for the request.
    """
    if cost < 1 or client_limit < cost or global_limit < cost or window_seconds < 1:
        raise ValueError("Invalid external budget configuration")

    client_key = f"latexy:external-budget:{scope}:client:{client_id}"
    global_key = f"latexy:external-budget:{scope}:global"
    try:
        redis = await get_redis_cache_client()
        allowed, client_count, global_count = await redis.eval(
            _CONSUME_BUDGET,
            2,
            client_key,
            global_key,
            cost,
            client_limit,
            global_limit,
            window_seconds,
        )
    except Exception as exc:
        logger.error("External budget store unavailable for %s: %s", scope, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Resource budget temporarily unavailable. Please retry shortly.",
            headers={"Retry-After": "30"},
        ) from exc

    if not int(allowed):
        logger.warning(
            "External budget exceeded for %s/%s (client=%s, global=%s)",
            scope,
            client_id,
            client_count,
            global_count,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many resource-intensive requests. Please try again later.",
            headers={"Retry-After": str(window_seconds)},
        )
