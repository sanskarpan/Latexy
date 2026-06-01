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
    record_frontend_event(
        kind=payload.kind,
        name=payload.name,
        route=route,
        value=payload.value,
    )
    logger.info(
        "frontend_telemetry_ingested",
        extra={
            "event_name": payload.name,
            "metric_name": payload.name if payload.kind == "web_vital" else None,
            "route_name": route,
            "user_id": user_id,
            "request_id": getattr(request.state, "request_id", None),
        },
    )
    return {"accepted": True}
