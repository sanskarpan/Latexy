"""Browser exception metadata ingestion for the admin error feed.

The endpoint accepts *only* a bounded error class, a sanitized product route and
a release tag. There is deliberately no field for an exception message, stack,
source snippet, prompt, document content, email or token. The client beacon is
sent from the consent-gated PostHog ``before_send`` hook, so a visitor without
analytics consent never reaches this route.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.log_sanitize import sanitize_for_log
from ..core.logging import get_logger
from ..core.redis import get_redis_client
from ..database.connection import get_db
from ..middleware.auth_middleware import get_current_user_optional
from ..middleware.rate_limiting import client_ip_id
from ..services import error_tracking_service

logger = get_logger(__name__)

router = APIRouter(prefix="/telemetry", tags=["telemetry"])

_ERROR_SIGNAL_LIMIT = 120
_ERROR_SIGNAL_WINDOW_SECONDS = 60

# Atomic fixed-window limiter. Fails open when Redis is unavailable so a cache
# outage never blocks exception reporting.
_LUA_INCR_EXPIRE = """
local n = redis.call('INCR', KEYS[1])
if n == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return n
"""


class FrontendErrorSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error_class: str = Field(min_length=1, max_length=80)
    route: str = Field(min_length=1, max_length=128)
    release: Optional[str] = Field(default=None, max_length=64)


async def _rate_limit_ok(key: str) -> bool:
    try:
        redis = await get_redis_client()
        count = await redis.eval(
            _LUA_INCR_EXPIRE,
            1,
            key,
            _ERROR_SIGNAL_WINDOW_SECONDS,
        )
        return int(count) <= _ERROR_SIGNAL_LIMIT
    except Exception:
        return True


@router.post("/errors", status_code=status.HTTP_202_ACCEPTED)
async def ingest_frontend_error(
    payload: FrontendErrorSignal,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user_id: str | None = Depends(get_current_user_optional),
):
    """Record one sanitized browser exception signal.

    Document, share, portfolio and guest-editor routes are accepted then dropped;
    the response never echoes the submitted values.
    """
    if not settings.FRONTEND_TELEMETRY_ENABLED or not settings.ERROR_TRACKING_ENABLED:
        raise HTTPException(status_code=404, detail="Frontend telemetry disabled")

    bucket = f"user:{user_id}" if user_id else client_ip_id(request)
    if not await _rate_limit_ok(f"ratelimit:telemetry:errors:{bucket}"):
        raise HTTPException(status_code=429, detail="Too many error reports")

    normalized_route = error_tracking_service.normalize_error_route(payload.route, source="frontend")
    if normalized_route is None:
        return {"accepted": False, "reason": "surface_excluded"}

    await error_tracking_service.record_error_group(
        db,
        source="frontend",
        route=normalized_route,
        release=payload.release or "unknown",
        error_class=payload.error_class,
    )
    await db.commit()

    logger.info(
        "frontend_error_signal_ingested",
        extra={
            "error_class": sanitize_for_log(payload.error_class, max_len=80),
            "route_name": sanitize_for_log(normalized_route, max_len=128),
            "request_id": sanitize_for_log(getattr(request.state, "request_id", None)),
        },
    )
    return {"accepted": True}
