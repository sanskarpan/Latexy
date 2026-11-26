"""First-party ingestion for privacy-safe client linter telemetry (issue #2148)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.logging import get_logger
from ..database.connection import get_db
from ..middleware.auth_middleware import get_current_user_optional
from ..services.linter_telemetry_service import MAX_EVENTS_PER_REQUEST, record_linter_events

logger = get_logger(__name__)

router = APIRouter(prefix="/telemetry", tags=["telemetry"])


class LinterTelemetryEvent(BaseModel):
    """Exactly the client fields this event family accepts.

    Extra keys are ignored, so a caller cannot smuggle LaTeX source, a document
    id, a lint message or per-user context into storage.
    """

    model_config = ConfigDict(extra="ignore")

    rule_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    severity: Literal["error", "warning", "info"]
    route: str = Field(default="/other", max_length=128)
    fixed: bool = False
    issue_count: int = Field(ge=1, le=10_000)


class LinterTelemetryRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    events: list[LinterTelemetryEvent] = Field(
        min_length=1,
        max_length=MAX_EVENTS_PER_REQUEST,
    )


@router.post("/linter", status_code=status.HTTP_202_ACCEPTED)
async def ingest_linter_telemetry(
    payload: LinterTelemetryRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user_id: str | None = Depends(get_current_user_optional),
) -> dict[str, int]:
    """Append allowlisted lint outcomes; never accept document content."""

    if not settings.FRONTEND_TELEMETRY_ENABLED:
        raise HTTPException(status_code=404, detail="Frontend telemetry disabled")

    result = await record_linter_events(
        db,
        [event.model_dump() for event in payload.events],
        user_id=user_id,
    )
    logger.info(
        "linter_telemetry_ingested",
        extra={
            "accepted": result["accepted"],
            "rejected": result["rejected"],
            "deduplicated": result["deduplicated"],
        },
    )
    return result
