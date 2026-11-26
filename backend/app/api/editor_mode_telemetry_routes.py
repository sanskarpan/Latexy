"""First-party ingestion for privacy-safe editor usage telemetry (issue #2077).

The browser may send only the allowlisted fields below. Extra keys are ignored,
so LaTeX source, prompts, filenames, raw document ids or free-form metadata can
never reach storage. The authenticated account id and plan are derived on the
server; the route label is re-bucketed by the service.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.logging import get_logger
from ..database.connection import get_db
from ..middleware.auth_middleware import get_current_user_required
from ..middleware.capability_router import CapabilityRouter as APIRouter
from ..services.editor_mode_analytics_service import (
    MAX_EVENTS_PER_REQUEST,
    record_editor_events,
    resolve_editor_plan,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/telemetry", tags=["telemetry"])


class EditorTelemetryEvent(BaseModel):
    """Exactly the client fields this event family accepts.

    ``document_id`` is optional for first-party callers and is hashed before
    storage; it is never persisted. A caller that already holds the SHA-256
    digest may send ``document_hash`` instead.
    """

    model_config = ConfigDict(extra="ignore")

    event_type: str = Field(min_length=1, max_length=64)
    mode: str = Field(min_length=1, max_length=16)
    route: str = Field(default="/other", max_length=128)
    document_hash: str | None = Field(default=None, max_length=64)
    document_id: str | None = Field(default=None, max_length=128)
    enabled: bool | None = None
    direction: str | None = Field(default=None, max_length=32)
    event_id: str | None = Field(default=None, max_length=128)


class EditorTelemetryRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    events: list[EditorTelemetryEvent] = Field(
        min_length=1,
        max_length=MAX_EVENTS_PER_REQUEST,
    )


@router.post("/editor", status_code=status.HTTP_202_ACCEPTED)
async def ingest_editor_telemetry(
    payload: EditorTelemetryRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> dict[str, Any]:
    """Append allowlisted editor events; never accept document content."""

    if not settings.FRONTEND_TELEMETRY_ENABLED:
        raise HTTPException(status_code=404, detail="Frontend telemetry disabled")

    plan = await resolve_editor_plan(db, user_id)
    result = await record_editor_events(
        db,
        [event.model_dump() for event in payload.events],
        user_id=user_id,
        plan=plan,
    )
    logger.info(
        "editor_mode_telemetry_ingested",
        extra={
            "accepted": result["accepted"],
            "rejected": result["rejected"],
            "deduplicated": result["deduplicated"],
        },
    )
    return result
