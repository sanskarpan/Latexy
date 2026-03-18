"""Admin feature flag endpoints.

GET  /config/feature-flags       — public, no auth — {key: bool, ...}
GET  /admin/feature-flags        — admin only — full objects
PATCH /admin/feature-flags/{key} — admin only — {enabled: bool}
"""

from datetime import datetime
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin
from ..services.feature_flag_service import feature_flag_service

router = APIRouter()


class FlagDetail(BaseModel):
    key: str
    enabled: bool
    label: str
    description: Optional[str]
    updated_at: Optional[datetime]


class FlagUpdateRequest(BaseModel):
    enabled: bool


# ------------------------------------------------------------------ #
#  Public — no auth                                                   #
# ------------------------------------------------------------------ #

@router.get("/config/feature-flags", response_model=Dict[str, bool])
async def get_public_feature_flags(db: AsyncSession = Depends(get_db)):
    """Return a flat {key: bool} map of all feature flags. No auth required."""
    flags = await feature_flag_service.get_all_flags(db)
    return {f.key: f.enabled for f in flags}


# ------------------------------------------------------------------ #
#  Admin — require_admin dependency                                   #
# ------------------------------------------------------------------ #

@router.get("/admin/feature-flags", response_model=list[FlagDetail])
async def get_admin_feature_flags(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    """Return full flag objects (label, description, updated_at). Admin only."""
    flags = await feature_flag_service.get_all_flags(db)
    return [
        FlagDetail(
            key=f.key,
            enabled=f.enabled,
            label=f.label,
            description=f.description,
            updated_at=f.updated_at,
        )
        for f in flags
    ]


@router.patch("/admin/feature-flags/{key}", response_model=FlagDetail)
async def update_feature_flag(
    key: str,
    body: FlagUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    """Toggle a feature flag. Admin only."""
    try:
        flag = await feature_flag_service.update_flag(key, body.enabled, db)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Feature flag {key!r} not found")
    return FlagDetail(
        key=flag.key,
        enabled=flag.enabled,
        label=flag.label,
        description=flag.description,
        updated_at=flag.updated_at,
    )
