"""Developer API key management routes (Feature 21)."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_developer_api_daily_limit
from ..database.connection import get_db
from ..database.models import DeveloperAPIKey, User
from ..middleware.auth_middleware import get_current_user_required
from ..services.developer_key_service import developer_key_service

router = APIRouter(prefix="/developer", tags=["developer"])

VALID_SCOPES = {"compile", "optimize", "ats", "export"}


class DeveloperKeyResponse(BaseModel):
    id: str
    name: str
    key_prefix: str
    last_used_at: Optional[str] = None
    request_count: int
    is_active: bool
    scopes: List[str]
    created_at: str


class DeveloperKeyCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    scopes: Optional[List[str]] = None


class DeveloperKeyCreateResponse(DeveloperKeyResponse):
    full_key: str


class DeveloperKeyRenameRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class DeveloperUsagePoint(BaseModel):
    date: str
    count: int


class DeveloperUsageResponse(BaseModel):
    plan_id: str
    daily_limit: int
    history: List[DeveloperUsagePoint]


def _key_to_response(key: DeveloperAPIKey) -> DeveloperKeyResponse:
    return DeveloperKeyResponse(
        id=key.id,
        name=key.name,
        key_prefix=key.key_prefix,
        last_used_at=key.last_used_at.isoformat() if key.last_used_at else None,
        request_count=int(key.request_count or 0),
        is_active=bool(key.is_active),
        scopes=list(key.scopes or []),
        created_at=key.created_at.isoformat(),
    )


async def _get_user_plan(db: AsyncSession, user_id: str) -> str:
    result = await db.execute(select(User.subscription_plan).where(User.id == user_id))
    return result.scalar_one_or_none() or "free"


@router.get("/keys", response_model=List[DeveloperKeyResponse])
async def list_developer_keys(
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DeveloperAPIKey)
        .where(DeveloperAPIKey.user_id == user_id)
        .order_by(DeveloperAPIKey.created_at.desc())
    )
    return [_key_to_response(key) for key in result.scalars().all()]


@router.get("/usage", response_model=DeveloperUsageResponse)
async def get_developer_usage(
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    plan_id = await _get_user_plan(db, user_id)
    history = await developer_key_service.get_usage_history(user_id)
    return DeveloperUsageResponse(
        plan_id=plan_id,
        daily_limit=get_developer_api_daily_limit(plan_id),
        history=[DeveloperUsagePoint(**point) for point in history],
    )


@router.post("/keys", response_model=DeveloperKeyCreateResponse, status_code=201)
async def create_developer_key(
    body: DeveloperKeyCreateRequest,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    count_result = await db.execute(
        select(func.count())
        .select_from(DeveloperAPIKey)
        .where(
            DeveloperAPIKey.user_id == user_id,
            DeveloperAPIKey.is_active.is_(True),
        )
    )
    if int(count_result.scalar_one() or 0) >= developer_key_service.MAX_KEYS_PER_USER:
        raise HTTPException(status_code=400, detail="Maximum of 5 active developer API keys reached")

    scopes = list(dict.fromkeys(body.scopes or developer_key_service.DEFAULT_SCOPES))
    if not scopes or any(scope not in VALID_SCOPES for scope in scopes):
        raise HTTPException(status_code=422, detail=f"Scopes must be drawn from {sorted(VALID_SCOPES)}")

    full_key, key_hash, key_prefix = developer_key_service.generate_api_key()
    key = DeveloperAPIKey(
        user_id=user_id,
        key_hash=key_hash,
        key_prefix=key_prefix,
        name=body.name.strip(),
        scopes=scopes,
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)

    payload = _key_to_response(key).model_dump()
    return DeveloperKeyCreateResponse(**payload, full_key=full_key)


@router.patch("/keys/{key_id}", response_model=DeveloperKeyResponse)
async def rename_developer_key(
    key_id: str,
    body: DeveloperKeyRenameRequest,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DeveloperAPIKey).where(
            DeveloperAPIKey.id == key_id,
            DeveloperAPIKey.user_id == user_id,
        )
    )
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=404, detail="Developer API key not found")

    key.name = body.name.strip()
    await db.commit()
    await db.refresh(key)
    return _key_to_response(key)


@router.delete("/keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_developer_key(
    key_id: str,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DeveloperAPIKey).where(
            DeveloperAPIKey.id == key_id,
            DeveloperAPIKey.user_id == user_id,
        )
    )
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=404, detail="Developer API key not found")

    key.is_active = False
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
