"""Team billing seat management routes (Feature 32)."""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.redis import get_redis_cache_client
from ..database.connection import get_db
from ..database.models import TeamSeat, User
from ..middleware.auth_middleware import get_current_user_required
from ..services.email_service import email_service
from ..utils.uuid_guard import ensure_uuid

router = APIRouter(prefix="/team", tags=["team-billing"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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
    email: str = Field(..., min_length=3, max_length=255)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _EMAIL_RE.match(normalized):
            raise ValueError("Invalid email address")
        return normalized


class TeamInviteResponse(TeamSeatResponse):
    invite_preview_url: Optional[str] = None
    message: str


def _same_origin(value: str, request: Request) -> bool:
    """Return whether an Origin/Referer value is an allowed app origin."""
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        return False
    origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    allowed = {
        str(candidate).rstrip("/")
        for candidate in (settings.effective_cors_origins() or [])
        if isinstance(candidate, str)
    }
    frontend_url = getattr(settings, "FRONTEND_URL", "")
    if isinstance(frontend_url, str) and frontend_url:
        frontend = urlsplit(frontend_url)
        if frontend.scheme and frontend.netloc:
            allowed.add(f"{frontend.scheme}://{frontend.netloc}".rstrip("/"))
    # Also permit requests addressed directly to this API host. This is useful
    # for self-hosted deployments where the UI and API share an origin.
    host = request.headers.get("host")
    if host:
        allowed.add(f"{request.url.scheme}://{host}".rstrip("/"))
    return origin in allowed


async def _require_same_origin_accept(request: Request) -> None:
    """Prevent cookie-authenticated cross-site POSTs from accepting a seat.

    Bearer-authenticated requests are not ambient-authority requests and do not
    need an Origin header. Cookie-authenticated browser requests must include a
    same-origin Origin or Referer header; this keeps the state-changing invite
    operation safe even when a browser sends the session cookie automatically.
    """
    if request.headers.get("authorization"):
        return

    origin = request.headers.get("origin")
    referer = request.headers.get("referer")
    if (origin and _same_origin(origin, request)) or (referer and _same_origin(referer, request)):
        return
    raise HTTPException(status_code=403, detail="Cross-site team invitation requests are not allowed")


def _parse_invitation(raw: object) -> tuple[str, str]:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if not isinstance(raw, str):
        raise HTTPException(status_code=404, detail="Invitation not found or expired")
    try:
        seat_id, invited_email = raw.split(":", 1)
        if not invited_email:
            raise ValueError
    except ValueError:
        raise HTTPException(status_code=404, detail="Invitation not found or expired")
    ensure_uuid(seat_id, "Invitation not found")
    return seat_id, invited_email


async def _resolve_team_invitation(
    token: str,
    user_id: str,
    db: AsyncSession,
    *,
    lock: bool,
):
    redis = await get_redis_cache_client()
    raw = await redis.get(f"team_invite:{token}")
    if not raw:
        raise HTTPException(status_code=404, detail="Invitation not found or expired")

    seat_id, invited_email = _parse_invitation(raw)
    seat_query = select(TeamSeat).where(TeamSeat.id == seat_id)
    if lock:
        seat_query = seat_query.with_for_update()
    seat_result = await db.execute(seat_query)
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
    return redis, seat, user


async def _require_team_owner(db: AsyncSession, user_id: str) -> TeamOwnerInfo:
    result = await db.execute(
        select(User.email, User.name, User.subscription_plan)
        .where(User.id == user_id)
        .with_for_update()
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

    email = body.email
    if email == owner.email.lower():
        raise HTTPException(status_code=400, detail="You already occupy the owner seat")

    existing_result = await db.execute(
        select(TeamSeat).where(
            TeamSeat.owner_user_id == user_id,
            TeamSeat.member_email == email,
        )
    )
    seat = existing_result.scalar_one_or_none()

    if seat and seat.status not in {"invited", "removed"}:
        raise HTTPException(status_code=409, detail="That teammate already has an active seat")

    # A resend of the same pending seat consumes no additional capacity and
    # must remain possible even when the plan is at its seat limit. New seats
    # and reactivations of removed seats still enforce the limit.
    if not seat or seat.status == "removed":
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

    if not seat:
        seat = TeamSeat(owner_user_id=user_id, member_email=email, status="invited")
        db.add(seat)
    else:
        seat.status = "invited"
        seat.member_user_id = None
        seat.joined_at = None
        seat.invited_at = datetime.now(timezone.utc)

    token = secrets.token_urlsafe(32)
    token_key = f"team_invite:{token}"
    redis = None
    try:
        # Flush assigns a UUID for new seats without making the invitation
        # durable. If token storage fails, rollback leaves no dead-end pending
        # row and the owner can retry safely.
        await db.flush()
        redis = await get_redis_cache_client()
        await redis.set(token_key, f"{seat.id}:{email}", ex=7 * 24 * 3600)
        await db.commit()
        await db.refresh(seat)
    except Exception as exc:
        await db.rollback()
        if redis is not None:
            try:
                await redis.delete(token_key)
            except Exception:
                pass
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Invitation service is temporarily unavailable. Please retry.",
        ) from exc

    invite_url = f"{settings.FRONTEND_URL}/billing?team_invite={token}"
    email_sent = await email_service.send_email(
        to=email,
        subject="You’ve been invited to a Latexy team workspace",
        html_body=(
            f"<p>{owner.name or owner.email} invited you to join their Latexy team plan.</p>"
            f"<p><a href=\"{invite_url}\">Accept your seat</a></p>"
        ),
        text_body=f"{owner.email} invited you to join their Latexy team plan: {invite_url}",
    )
    if settings.EMAIL_ENABLED and not email_sent:
        # Keep the pending seat resendable, but discard this undelivered token so
        # only links that actually reached the invitee remain usable.
        try:
            await redis.delete(token_key)
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The invitation could not be delivered. Please retry.",
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
async def preview_team_seat(
    token: str,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    await _resolve_team_invitation(token, user_id, db, lock=False)
    return {"success": True, "message": "Team invitation is ready to accept"}


@router.post("/join/{token}")
async def join_team_seat(
    token: str,
    _csrf_safe: None = Depends(_require_same_origin_accept),
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    redis, seat, user = await _resolve_team_invitation(token, user_id, db, lock=True)

    # Token cleanup is best-effort, so replaying a successful request must be
    # harmless. The row lock serializes two concurrent POSTs for the same seat.
    if seat.status == "active":
        if seat.member_user_id != user_id:
            raise HTTPException(status_code=409, detail="Invitation has already been accepted")
        try:
            await redis.delete(f"team_invite:{token}")
        except Exception:
            pass
        return {"success": True, "message": "Team seat is already active"}
    if seat.status != "invited":
        raise HTTPException(status_code=404, detail="Invitation not found")

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
    try:
        await redis.delete(f"team_invite:{token}")
    except Exception:
        # Membership is already durable. A best-effort token cleanup failure
        # must not tell the user activation failed; the token also expires.
        pass

    return {"success": True, "message": "Team seat activated"}


@router.delete("/seats/{seat_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_team_seat(
    seat_id: str,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    ensure_uuid(seat_id, "Seat not found")
    await _require_team_owner(db, user_id)
    result = await db.execute(
        select(TeamSeat).where(
            TeamSeat.id == seat_id,
            TeamSeat.owner_user_id == user_id,
        ).with_for_update()
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
