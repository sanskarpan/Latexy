"""Team billing seat management routes (Feature 32)."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.redis import get_redis_cache_client
from ..database.connection import get_db
from ..database.models import TeamSeat, User
from ..middleware.auth_middleware import get_current_user_required
from ..services.email_service import email_service

router = APIRouter(prefix="/team", tags=["team-billing"])


@dataclass(slots=True)
class TeamOwnerInfo:
    email: str
    name: Optional[str]
    subscription_plan: str


class TeamSeatResponse(BaseModel):
    id: str
    member_email: str
    member_user_id: Optional[str] = None
    status: str
    invited_at: str
    joined_at: Optional[str] = None


class TeamInviteRequest(BaseModel):
    email: str


class TeamInviteResponse(TeamSeatResponse):
    invite_preview_url: Optional[str] = None
    message: str


async def _require_team_owner(db: AsyncSession, user_id: str) -> TeamOwnerInfo:
    result = await db.execute(
        select(User.email, User.name, User.subscription_plan).where(User.id == user_id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    if row.subscription_plan != "team":
        raise HTTPException(status_code=403, detail="Team plan required")
    return TeamOwnerInfo(
        email=row.email,
        name=row.name,
        subscription_plan=row.subscription_plan,
    )


def _seat_to_response(seat: TeamSeat) -> TeamSeatResponse:
    return TeamSeatResponse(
        id=seat.id,
        member_email=seat.member_email,
        member_user_id=seat.member_user_id,
        status=seat.status,
        invited_at=seat.invited_at.isoformat(),
        joined_at=seat.joined_at.isoformat() if seat.joined_at else None,
    )


@router.get("/seats", response_model=List[TeamSeatResponse])
async def list_team_seats(
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    await _require_team_owner(db, user_id)
    result = await db.execute(
        select(TeamSeat)
        .where(TeamSeat.owner_user_id == user_id)
        .order_by(TeamSeat.invited_at.asc())
    )
    return [_seat_to_response(seat) for seat in result.scalars().all()]


@router.post("/invite", response_model=TeamInviteResponse, status_code=201)
async def invite_team_member(
    body: TeamInviteRequest,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    owner = await _require_team_owner(db, user_id)

    active_count_result = await db.execute(
        select(TeamSeat).where(
            TeamSeat.owner_user_id == user_id,
            TeamSeat.status != "removed",
        )
    )
    if len(active_count_result.scalars().all()) >= settings.TEAM_PLAN_MAX_SEATS:
        raise HTTPException(
            status_code=400,
            detail=f"Team seat limit reached ({settings.TEAM_PLAN_MAX_SEATS})",
        )

    email = body.email.lower().strip()
    if email == owner.email.lower():
        raise HTTPException(status_code=400, detail="You already occupy the owner seat")

    existing_result = await db.execute(
        select(TeamSeat).where(
            TeamSeat.owner_user_id == user_id,
            TeamSeat.member_email == email,
        )
    )
    seat = existing_result.scalar_one_or_none()

    if seat and seat.status != "removed":
        raise HTTPException(status_code=409, detail="That teammate already has an active or pending seat")

    if not seat:
        seat = TeamSeat(owner_user_id=user_id, member_email=email, status="invited")
        db.add(seat)
    else:
        seat.status = "invited"
        seat.member_user_id = None
        seat.joined_at = None
        seat.invited_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(seat)

    token = secrets.token_urlsafe(32)
    redis = await get_redis_cache_client()
    await redis.setex(
        f"team_invite:{token}",
        7 * 24 * 3600,
        f"{seat.id}:{email}",
    )

    invite_url = f"{settings.FRONTEND_URL}/billing?team_invite={token}"
    await email_service.send_email(
        to=email,
        subject="You’ve been invited to a Latexy team workspace",
        html_body=(
            f"<p>{owner.name or owner.email} invited you to join their Latexy team plan.</p>"
            f"<p><a href=\"{invite_url}\">Accept your seat</a></p>"
        ),
        text_body=f"{owner.email} invited you to join their Latexy team plan: {invite_url}",
    )

    payload = _seat_to_response(seat).model_dump()
    # Only ever surface the raw token URL outside production. In production the
    # token must reach the invitee via email only, never in the API response.
    preview_url = (
        invite_url
        if (not settings.EMAIL_ENABLED and not settings.is_production_like())
        else None
    )
    return TeamInviteResponse(
        **payload,
        invite_preview_url=preview_url,
        message="Team invitation created",
    )


@router.get("/join/{token}")
async def join_team_seat(
    token: str,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    redis = await get_redis_cache_client()
    raw = await redis.get(f"team_invite:{token}")
    if not raw:
        raise HTTPException(status_code=404, detail="Invitation not found or expired")

    seat_id, invited_email = raw.split(":", 1)
    seat_result = await db.execute(select(TeamSeat).where(TeamSeat.id == seat_id))
    seat = seat_result.scalar_one_or_none()
    if not seat or seat.status == "removed":
        raise HTTPException(status_code=404, detail="Invitation not found")

    user_result = await db.execute(
        select(User.email, User.subscription_plan).where(User.id == user_id)
    )
    user = user_result.one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.email.lower() != invited_email.lower():
        raise HTTPException(status_code=403, detail="Invitation email does not match this account")

    seat.member_user_id = user_id
    seat.status = "active"
    seat.joined_at = datetime.now(timezone.utc)
    if user.subscription_plan in {"free", "basic"}:
        await db.execute(
            update(User)
            .where(User.id == user_id)
            .values(subscription_plan="team_member", subscription_status="active")
        )
    await db.commit()
    await redis.delete(f"team_invite:{token}")

    return {"success": True, "message": "Team seat activated"}


@router.delete("/seats/{seat_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_team_seat(
    seat_id: str,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    await _require_team_owner(db, user_id)
    result = await db.execute(
        select(TeamSeat).where(
            TeamSeat.id == seat_id,
            TeamSeat.owner_user_id == user_id,
        )
    )
    seat = result.scalar_one_or_none()
    if not seat:
        raise HTTPException(status_code=404, detail="Seat not found")

    if seat.member_user_id:
        member_result = await db.execute(
            select(User.subscription_plan).where(User.id == seat.member_user_id)
        )
        member_plan = member_result.scalar_one_or_none()
        if member_plan == "team_member":
            await db.execute(
                update(User)
                .where(User.id == seat.member_user_id)
                .values(subscription_plan="free", subscription_status="inactive")
            )

    seat.status = "removed"
    await db.commit()
    return None
