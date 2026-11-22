"""Admin alert strip: list, acknowledge and snooze durable incidents."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..services import admin_alert_service
from ..services.admin_audit_service import AdminActor

router = APIRouter()

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)]


class AlertActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: Literal["acknowledged", "snoozed"]
    reason: Reason
    snooze_minutes: int | None = Field(default=None, ge=5, le=1440)


@router.get("/admin/alerts")
async def list_admin_alerts(
    state: str | None = Query(default=None, max_length=16),
    severity: str | None = Query(default=None, max_length=16),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    items, total = await admin_alert_service.list_alerts(
        db,
        state=state,
        severity=severity,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.patch("/admin/alerts/{alert_id}")
async def update_admin_alert(
    alert_id: UUID,
    body: AlertActionRequest,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    target_id = str(alert_id)
    try:
        if body.state == "acknowledged":
            return await admin_alert_service.acknowledge_alert(
                db, alert_id=target_id, actor=actor, reason=body.reason
            )
        if body.snooze_minutes is None:
            raise ValueError("snooze_minutes is required when snoozing an alert")
        return await admin_alert_service.snooze_alert(
            db,
            alert_id=target_id,
            actor=actor,
            reason=body.reason,
            minutes=body.snooze_minutes,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0]) if exc.args else "Alert not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
