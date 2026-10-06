"""Telemetry ingestion routes for browser-side observability."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from ..core.config import settings
from ..core.logging import get_logger
from ..core.observability import record_frontend_event
from ..middleware.auth_middleware import get_current_user_optional

logger = get_logger(__name__)

router = APIRouter(prefix="/telemetry", tags=["telemetry"])

# Prometheus label values must come from a bounded set to avoid a cardinality
# bomb. Unknown (attacker-controlled) names/routes are bucketed to "other".
_OTHER_LABEL = "other"
_WEB_VITAL_NAMES = frozenset({"LCP", "FID", "CLS", "TTFB", "INP", "FCP", "TTI"})
_BUSINESS_EVENT_NAMES = frozenset({"page_view", "job_submit"})
_KNOWN_ROUTES = frozenset({
    "/",
    "/login",
    "/signup",
    "/dashboard",
    "/try",
    "/workspace",
    "/billing",
    "/byok",
    "/platform",
    "/resources",
    "/faq",
    "/updates",
    "/jobs/submit",
    "/unknown",
})
def _bucket_name(kind: str, name: str) -> str:
    allowed = _WEB_VITAL_NAMES if kind == "web_vital" else _BUSINESS_EVENT_NAMES
    return name if name in allowed else _OTHER_LABEL


def _bucket_route(route: str) -> str:
    return route if route in _KNOWN_ROUTES else _OTHER_LABEL


class FrontendTelemetryEvent(BaseModel):
    kind: Literal["web_vital", "business_event"]
    name: str = Field(min_length=1, max_length=64)
    route: str = Field(default="/unknown", max_length=128)
    value: float | None = None
    unit: str | None = Field(default=None, max_length=32)
    metadata: dict[str, Any] | None = None


@router.post("/frontend", status_code=status.HTTP_202_ACCEPTED)
async def ingest_frontend_telemetry(
    payload: FrontendTelemetryEvent,
    request: Request,
    user_id: str | None = Depends(get_current_user_optional),
):
    """Ingest browser-side telemetry events for metrics and logs."""
    if not settings.FRONTEND_TELEMETRY_ENABLED:
        raise HTTPException(status_code=404, detail="Frontend telemetry disabled")

    route = payload.route.strip() or "/unknown"

    # Use bounded values for both metrics and logs.  Client-controlled names and
    # routes may contain PII or log-control characters and are not operationally
    # useful once they are outside the known telemetry vocabulary.
    metric_name = _bucket_name(payload.kind, payload.name)
    metric_route = _bucket_route(route)
    record_frontend_event(
        kind=payload.kind,
        name=metric_name,
        route=metric_route,
        value=payload.value,
    )

    logger.info(
        "frontend_telemetry_ingested",
        extra={
            "event_name": metric_name,
            "metric_name": metric_name if payload.kind == "web_vital" else None,
            "route_name": metric_route,
            "user_id": user_id,
            "request_id": getattr(request.state, "request_id", None),
        },
    )
    return {"accepted": True}
