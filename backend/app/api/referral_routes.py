"""Authenticated user-referral endpoints (B59)."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import get_current_user_optional
from ..services.referral_service import referral_service

router = APIRouter(prefix="/referral", tags=["referrals"])


class ReferralClaimRequest(BaseModel):
    code: str = Field(min_length=16, max_length=128)


def _require_user(user_id: Optional[str]) -> str:
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


@router.get("/status")
async def referral_status(
    db: AsyncSession = Depends(get_db),
    user_id: Optional[str] = Depends(get_current_user_optional),
):
    return await referral_service.status(db, _require_user(user_id))


@router.post("/claim")
async def claim_referral(
    body: ReferralClaimRequest,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[str] = Depends(get_current_user_optional),
):
    return await referral_service.claim(db, _require_user(user_id), body.code)
