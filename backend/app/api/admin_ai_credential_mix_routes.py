"""Admin-only BYOK vs platform-key usage mix.

The route is aggregate-only and reads the two first-party AI ledgers plus
key-ownership counts.  It never returns key material, ciphertext, key names,
key IDs or credential fingerprints.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..services.admin_ai_credential_mix_service import credential_mix_snapshot
from ..services.admin_audit_service import AdminActor

router = APIRouter()


@router.get("/admin/analytics/credential-mix")
async def get_admin_credential_mix(
    days: int = Query(30, ge=1, le=365),
    plan: Optional[str] = Query(None, max_length=50),
    feature: Optional[str] = Query(None, max_length=120),
    provider: Optional[str] = Query(None, max_length=80),
    model: Optional[str] = Query(None, max_length=160),
    persona: Optional[str] = Query(None, max_length=64),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """BYOK vs platform calls, tokens and estimated cost by feature/plan/time."""
    try:
        return await credential_mix_snapshot(
            db,
            days=days,
            plan=plan,
            feature=feature,
            provider=provider,
            model=model,
            persona=persona,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
