"""Admin-only linter rule frequency and fix-rate report (issue #2148).

Read-only and aggregate-only: the payload contains bounded rule ids, route
labels and counts. It never returns LaTeX source, line text, lint messages,
document ids or a per-user lint history.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..services.admin_audit_service import AdminActor
from ..services.linter_telemetry_service import admin_linter_rules_service

router = APIRouter(tags=["admin-quality"])


@router.get("/admin/linter/rules")
async def get_admin_linter_rules(
    days: int = Query(30, ge=1, le=366),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Return rule frequency, fix rate, daily trend and top noisy rules."""

    return await admin_linter_rules_service.snapshot(db, days=days)
