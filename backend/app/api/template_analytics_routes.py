"""Privacy-safe template catalog event capture routes."""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import get_current_user_optional
from ..services.template_analytics_service import template_analytics_service

router = APIRouter(prefix="/templates", tags=["templates"])


class TemplateEventRequest(BaseModel):
    event: Literal["view", "select"]
    # Browser-generated retry key. It is optional so a legitimate repeat view is
    # still counted; sending the same id again is an idempotent replay.
    event_id: Optional[str] = Field(
        default=None,
        min_length=8,
        max_length=80,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )


@router.post("/{template_id}/events", status_code=status.HTTP_201_CREATED)
async def track_template_event(
    template_id: str,
    body: TemplateEventRequest,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[str] = Depends(get_current_user_optional),
):
    """Record a template view/select without accepting document content.

    The user, plan and template attribution are all server-resolved. The only
    client-supplied values are the allowlisted event name and an optional retry
    key.
    """
    try:
        result = await template_analytics_service.record_client_event(
            db,
            event=body.event,
            template_id=template_id,
            user_id=user_id,
            event_id=body.event_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Template not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result
