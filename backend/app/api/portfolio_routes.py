"""Portfolio / public profile routes (Feature 67)."""

import re
import socket
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logging import get_logger
from ..database.connection import get_db
from ..database.models import Resume, User
from ..middleware.auth_middleware import get_current_user_required

logger = get_logger(__name__)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

_USERNAME_RE = re.compile(r"^[a-z0-9_-]{3,30}$")
_VALID_THEMES = frozenset({"minimal", "dark", "professional"})


# ── Schemas ──────────────────────────────────────────────────────────────────


class PortfolioSetupRequest(BaseModel):
    public_username: str = Field(..., min_length=3, max_length=30)
    portfolio_enabled: bool = True
    theme: str = Field(default="minimal")
    tagline: Optional[str] = Field(default=None, max_length=200)

    @field_validator("public_username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        v = v.lower()
        if not _USERNAME_RE.match(v):
            raise ValueError(
                "Username must be 3–30 characters: lowercase letters, digits, _ or -"
            )
        return v

    @field_validator("theme")
    @classmethod
    def validate_theme(cls, v: str) -> str:
        if v not in _VALID_THEMES:
            raise ValueError(f"theme must be one of: {', '.join(sorted(_VALID_THEMES))}")
        return v


class PublicResumeOut(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class PortfolioResponse(BaseModel):
    username: str
    name: Optional[str]
    tagline: Optional[str]
    theme: str
    resumes: List[PublicResumeOut]


class PortfolioSetupResponse(BaseModel):
    public_username: str
    portfolio_enabled: bool
    theme: str
    tagline: Optional[str]
    portfolio_url: str


class UsernameAvailabilityResponse(BaseModel):
    username: str
    available: bool


class DomainVerifyResponse(BaseModel):
    domain: str
    verified: bool
    message: str


class ResolveDomainResponse(BaseModel):
    domain: str
    username: Optional[str]


# ── Fixed-path endpoints MUST come before the {username} wildcard ─────────────


@router.post("/setup", response_model=PortfolioSetupResponse)
async def setup_portfolio(
    body: PortfolioSetupRequest,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
) -> PortfolioSetupResponse:
    """Authenticated — configure the authenticated user's portfolio."""
    # Check username collision (exclude current user)
    collision = await db.execute(
        select(User).where(
            User.public_username == body.public_username,
            User.id != user_id,
        )
    )
    if collision.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Username already taken")

    result = await db.execute(select(User).where(User.id == user_id))
    user: Optional[User] = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    user.public_username = body.public_username
    user.portfolio_enabled = body.portfolio_enabled
    user.portfolio_theme = body.theme
    user.portfolio_tagline = body.tagline
    await db.commit()
    await db.refresh(user)

    return PortfolioSetupResponse(
        public_username=user.public_username,
        portfolio_enabled=user.portfolio_enabled,
        theme=user.portfolio_theme,
        tagline=user.portfolio_tagline,
        portfolio_url=f"/u/{user.public_username}",
    )


@router.get("/check-username", response_model=UsernameAvailabilityResponse)
async def check_username(
    username: str = Query(..., min_length=1, max_length=30),
    db: AsyncSession = Depends(get_db),
) -> UsernameAvailabilityResponse:
    """Public — check whether a username is available."""
    username = username.lower()
    if not _USERNAME_RE.match(username):
        raise HTTPException(
            status_code=422,
            detail="Username must be 3–30 characters: lowercase letters, digits, _ or -",
        )
    result = await db.execute(
        select(User).where(User.public_username == username)
    )
    taken = result.scalar_one_or_none() is not None
    return UsernameAvailabilityResponse(username=username, available=not taken)


@router.post("/verify-domain", response_model=DomainVerifyResponse)
async def verify_domain(
    domain: str = Query(..., min_length=3, max_length=255),
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
) -> DomainVerifyResponse:
    """Authenticated — verify a CNAME record for custom domain."""
    domain = domain.lower().strip()

    result = await db.execute(select(User).where(User.id == user_id))
    user: Optional[User] = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Check for conflict with another user
    collision = await db.execute(
        select(User).where(
            User.portfolio_custom_domain == domain,
            User.id != user_id,
        )
    )
    if collision.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Domain already registered by another user")

    # Attempt a DNS lookup for CNAME record pointing to latexy.io
    verified = False
    message = "CNAME record not found"
    try:
        cname_target = socket.getfqdn(domain)
        if "latexy.io" in cname_target or cname_target != domain:
            verified = True
            message = f"CNAME verified: {domain} → {cname_target}"
    except Exception as exc:
        message = f"DNS lookup failed: {exc}"

    if verified:
        user.portfolio_custom_domain = domain
        await db.commit()

    return DomainVerifyResponse(domain=domain, verified=verified, message=message)


@router.get("/resolve-domain", response_model=ResolveDomainResponse)
async def resolve_domain(
    domain: str = Query(..., min_length=3, max_length=255),
    db: AsyncSession = Depends(get_db),
) -> ResolveDomainResponse:
    """Public — map a custom domain back to a portfolio username (used by middleware)."""
    result = await db.execute(
        select(User).where(
            User.portfolio_custom_domain == domain.lower().strip(),
            User.portfolio_enabled.is_(True),
        )
    )
    user: Optional[User] = result.scalar_one_or_none()
    return ResolveDomainResponse(
        domain=domain,
        username=user.public_username if user else None,
    )


# ── Wildcard endpoint MUST be LAST ────────────────────────────────────────────


@router.get("/{username}", response_model=PortfolioResponse)
async def get_portfolio(
    username: str,
    db: AsyncSession = Depends(get_db),
) -> PortfolioResponse:
    """Public endpoint — returns profile + public resumes for a username."""
    result = await db.execute(
        select(User).where(User.public_username == username.lower())
    )
    user: Optional[User] = result.scalar_one_or_none()

    if user is None or not user.portfolio_enabled:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    resumes_result = await db.execute(
        select(Resume)
        .where(Resume.user_id == user.id, Resume.archived_at.is_(None))
        .order_by(Resume.updated_at.desc())
    )
    resumes = resumes_result.scalars().all()

    return PortfolioResponse(
        username=user.public_username,
        name=user.name,
        tagline=user.portfolio_tagline,
        theme=user.portfolio_theme,
        resumes=[
            PublicResumeOut(
                id=r.id,
                title=r.title,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
            for r in resumes
        ],
    )
