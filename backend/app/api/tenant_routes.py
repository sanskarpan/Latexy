"""
Tenant admin CRUD API — Feature 85D.

prefix: /tenants

All write endpoints require the caller to be the tenant owner or an admin member.
"""

import logging
import re
from datetime import datetime
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..database.models import Compilation, Resume, Tenant, TenantMember, User
from ..middleware.auth_middleware import get_current_user_required
from ..middleware.tenant_middleware import get_current_tenant

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tenants", tags=["tenants"])

_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_SLUG_RE = re.compile(r"^[a-z0-9-]{3,40}$")

# Allowed white-label plans and their server-side seat caps. The client-supplied
# plan_id is validated against this map and max_members is ALWAYS derived
# server-side — never trusted from the request or left to the DB default.
_TENANT_PLANS: dict[str, int] = {"agency": 50, "university": 200}
# Cap the number of tenants a single user may provision to curb abuse.
_MAX_TENANTS_PER_USER = 10


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class TenantCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    slug: str = Field(..., min_length=3, max_length=40)
    plan_id: str = Field(default="agency", max_length=50)
    logo_url: Optional[str] = Field(None, max_length=500)
    primary_color: Optional[str] = Field(None, max_length=7)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        if not _SLUG_RE.match(v):
            raise ValueError("slug must be 3–40 lowercase alphanumeric characters or hyphens")
        return v

    @field_validator("primary_color")
    @classmethod
    def validate_color(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _HEX_COLOR_RE.match(v):
            raise ValueError("primary_color must be a 6-digit hex color like #6d28d9")
        return v


class TenantUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    logo_url: Optional[str] = Field(None, max_length=500)
    primary_color: Optional[str] = Field(None, max_length=7)
    custom_domain: Optional[str] = Field(None, max_length=253)
    active: Optional[bool] = None

    @field_validator("primary_color")
    @classmethod
    def validate_color(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _HEX_COLOR_RE.match(v):
            raise ValueError("primary_color must be a 6-digit hex color like #6d28d9")
        return v


class TenantResponse(BaseModel):
    id: str
    slug: str
    name: str
    logo_url: Optional[str]
    primary_color: Optional[str]
    custom_domain: Optional[str]
    plan_id: str
    max_members: int
    active: bool
    owner_id: str
    created_at: datetime


class MemberResponse(BaseModel):
    user_id: str
    email: str
    name: Optional[str]
    role: str
    joined_at: datetime


class InviteRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    role: str = Field(default="member", pattern="^(admin|member)$")


class TenantStats(BaseModel):
    member_count: int
    total_resumes: int
    total_compilations: int


class CurrentContextResponse(BaseModel):
    tenant: Optional[dict[str, Any]]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _tenant_response(t: Tenant) -> TenantResponse:
    return TenantResponse(
        id=t.id,
        slug=t.slug,
        name=t.name,
        logo_url=t.logo_url,
        primary_color=t.primary_color,
        custom_domain=t.custom_domain,
        plan_id=t.plan_id,
        max_members=t.max_members,
        active=t.active,
        owner_id=t.owner_id,
        created_at=t.created_at,
    )


async def _require_tenant_owner_or_admin(
    tenant_id: str, user_id: str, db: AsyncSession
) -> Tenant:
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if tenant.owner_id == user_id:
        return tenant
    # Check admin member
    member_result = await db.execute(
        select(TenantMember).where(
            TenantMember.tenant_id == tenant_id,
            TenantMember.user_id == user_id,
            TenantMember.role == "admin",
        )
    )
    if not member_result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Access denied: owner or admin required")
    return tenant


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/current-context", response_model=CurrentContextResponse)
async def current_context(request: Request) -> CurrentContextResponse:
    """Return the resolved tenant branding for the current Host (used by frontend on load)."""
    tenant = get_current_tenant(request)
    return CurrentContextResponse(tenant=tenant)


@router.post("", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    body: TenantCreate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> TenantResponse:
    """Create a new tenant. The caller becomes the owner."""
    # Validate the requested plan against the server-side whitelist and derive
    # the seat cap from it (never trust a client-supplied max_members / plan).
    plan_id = body.plan_id if body.plan_id in _TENANT_PLANS else "agency"
    max_members = _TENANT_PLANS[plan_id]

    # Enforce a per-user tenant creation limit to prevent resource abuse.
    owned_count = await db.execute(
        select(func.count()).select_from(Tenant).where(Tenant.owner_id == user_id)
    )
    if int(owned_count.scalar() or 0) >= _MAX_TENANTS_PER_USER:
        raise HTTPException(
            status_code=403,
            detail=f"Tenant creation limit reached ({_MAX_TENANTS_PER_USER} per user)",
        )

    # Check slug uniqueness
    existing = await db.execute(select(Tenant).where(Tenant.slug == body.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Slug '{body.slug}' is already taken")

    tenant = Tenant(
        slug=body.slug,
        name=body.name,
        logo_url=body.logo_url,
        primary_color=body.primary_color,
        owner_id=user_id,
        plan_id=plan_id,
        max_members=max_members,
    )
    db.add(tenant)
    await db.flush()

    # Owner is automatically added as an admin member
    owner_member = TenantMember(tenant_id=tenant.id, user_id=user_id, role="admin")
    db.add(owner_member)

    await db.commit()
    await db.refresh(tenant)
    return _tenant_response(tenant)


@router.get("/my", response_model=List[TenantResponse])
async def list_my_tenants(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> List[TenantResponse]:
    """Return all tenants where the caller is the owner or a member."""
    owned = await db.execute(select(Tenant).where(Tenant.owner_id == user_id))
    owned_tenants = {t.id: t for t in owned.scalars().all()}

    member_of = await db.execute(
        select(TenantMember).where(TenantMember.user_id == user_id)
    )
    # Collect non-owned membership tenant IDs, then bulk-fetch in one query
    non_owned_ids = [
        m.tenant_id
        for m in member_of.scalars().all()
        if m.tenant_id not in owned_tenants
    ]
    if non_owned_ids:
        member_tenants_result = await db.execute(
            select(Tenant).where(Tenant.id.in_(non_owned_ids))
        )
        for t in member_tenants_result.scalars().all():
            owned_tenants[t.id] = t

    return [_tenant_response(t) for t in owned_tenants.values()]


@router.patch("/{tenant_id}", response_model=TenantResponse)
async def update_tenant(
    tenant_id: str,
    body: TenantUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> TenantResponse:
    """Update tenant branding. Only owner or admin can update."""
    tenant = await _require_tenant_owner_or_admin(tenant_id, user_id, db)

    update_data = body.model_dump(exclude_unset=True)

    # custom_domain is UNIQUE — pre-check to return a clean 409 instead of a 500
    # when another tenant already claims the domain.
    new_domain = update_data.get("custom_domain")
    if new_domain and new_domain != tenant.custom_domain:
        clash = await db.execute(
            select(Tenant).where(
                Tenant.custom_domain == new_domain, Tenant.id != tenant_id
            )
        )
        if clash.scalar_one_or_none():
            raise HTTPException(
                status_code=409, detail=f"Domain '{new_domain}' is already claimed by another tenant"
            )

    for field, value in update_data.items():
        setattr(tenant, field, value)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Domain or slug already in use")
    await db.refresh(tenant)
    return _tenant_response(tenant)


@router.get("/{tenant_id}/members", response_model=List[MemberResponse])
async def list_members(
    tenant_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> List[MemberResponse]:
    """List all members of a tenant. Requires membership."""
    # Verify caller is a member or owner
    tenant_result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = tenant_result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Check membership (includes owner who is also a member)
    membership = await db.execute(
        select(TenantMember).where(
            TenantMember.tenant_id == tenant_id, TenantMember.user_id == user_id
        )
    )
    if not membership.scalar_one_or_none() and tenant.owner_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Single JOIN query — avoids N+1 (one SELECT per member)
    join_result = await db.execute(
        select(TenantMember, User)
        .join(User, User.id == TenantMember.user_id)
        .where(TenantMember.tenant_id == tenant_id)
    )
    responses: List[MemberResponse] = [
        MemberResponse(
            user_id=m.user_id,
            email=u.email,
            name=u.name,
            role=m.role,
            joined_at=m.joined_at,
        )
        for m, u in join_result.all()
    ]
    return responses


@router.post("/{tenant_id}/members/invite", response_model=MemberResponse, status_code=201)
async def invite_member(
    tenant_id: str,
    body: InviteRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> MemberResponse:
    """Invite a user by email to the tenant."""
    tenant = await _require_tenant_owner_or_admin(tenant_id, user_id, db)

    # Find invitee (case-insensitive — emails are normalized to lowercase on signup)
    email = body.email.strip().lower()
    invitee_result = await db.execute(
        select(User).where(func.lower(User.email) == email)
    )
    invitee = invitee_result.scalar_one_or_none()
    if not invitee:
        raise HTTPException(status_code=404, detail=f"No user found with email '{body.email}'")

    # Check member count limit — 409 (capacity), not 429 (rate limiting)
    count_result = await db.execute(
        select(func.count()).where(TenantMember.tenant_id == tenant_id)
    )
    if count_result.scalar() >= tenant.max_members:
        raise HTTPException(
            status_code=409, detail=f"Member limit ({tenant.max_members}) reached"
        )

    # Idempotent — don't add twice
    existing = await db.execute(
        select(TenantMember).where(
            TenantMember.tenant_id == tenant_id, TenantMember.user_id == invitee.id
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="User is already a member")

    member = TenantMember(tenant_id=tenant_id, user_id=invitee.id, role=body.role)
    db.add(member)
    try:
        await db.commit()
    except IntegrityError:
        # Concurrent invite for the same user raced us to the unique PK.
        await db.rollback()
        raise HTTPException(status_code=409, detail="User is already a member")
    await db.refresh(member)

    return MemberResponse(
        user_id=member.user_id,
        email=invitee.email,
        name=invitee.name,
        role=member.role,
        joined_at=member.joined_at,
    )


@router.delete("/{tenant_id}/members/{target_user_id}", status_code=204, response_model=None)
async def remove_member(
    tenant_id: str,
    target_user_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> None:
    """Remove a member from the tenant."""
    tenant = await _require_tenant_owner_or_admin(tenant_id, user_id, db)

    # The owner's membership row must never be removed — it would desync
    # owner_id from the member roster.
    if target_user_id == tenant.owner_id:
        raise HTTPException(status_code=403, detail="The tenant owner cannot be removed")

    member_result = await db.execute(
        select(TenantMember).where(
            TenantMember.tenant_id == tenant_id,
            TenantMember.user_id == target_user_id,
        )
    )
    member = member_result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    # Only the owner may remove an admin (an admin cannot strip co-admins).
    if member.role == "admin" and user_id != tenant.owner_id:
        raise HTTPException(status_code=403, detail="Only the owner can remove an admin")

    await db.delete(member)
    await db.commit()


@router.get("/{tenant_id}/stats", response_model=TenantStats)
async def tenant_stats(
    tenant_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> TenantStats:
    """Aggregate stats for a tenant (member count, resumes, compilations)."""
    await _require_tenant_owner_or_admin(tenant_id, user_id, db)

    # Member count
    member_count_result = await db.execute(
        select(func.count()).where(TenantMember.tenant_id == tenant_id)
    )
    member_count = member_count_result.scalar() or 0

    # Collect all member user_ids
    members_result = await db.execute(
        select(TenantMember.user_id).where(TenantMember.tenant_id == tenant_id)
    )
    user_ids = [row[0] for row in members_result.all()]

    total_resumes = 0
    total_compilations = 0

    if user_ids:
        resume_count_result = await db.execute(
            select(func.count()).where(Resume.user_id.in_(user_ids))
        )
        total_resumes = resume_count_result.scalar() or 0

        compile_count_result = await db.execute(
            select(func.count()).where(Compilation.user_id.in_(user_ids))
        )
        total_compilations = compile_count_result.scalar() or 0

    return TenantStats(
        member_count=member_count,
        total_resumes=total_resumes,
        total_compilations=total_compilations,
    )


@router.post("/{tenant_id}/domain/verify", status_code=200)
async def verify_domain(
    tenant_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> dict:
    """
    Returns DNS TXT verification instructions for the tenant's custom domain.
    (Actual DNS check is out of scope; this endpoint provides the record to add.)
    """
    tenant = await _require_tenant_owner_or_admin(tenant_id, user_id, db)
    if not tenant.custom_domain:
        raise HTTPException(
            status_code=400, detail="No custom_domain set for this tenant"
        )
    txt_record = f"latexy-verify={tenant.id}"
    return {
        "domain": tenant.custom_domain,
        "txt_record_name": f"_latexy.{tenant.custom_domain}",
        "txt_record_value": txt_record,
        "instructions": (
            f"Add a DNS TXT record named '_latexy.{tenant.custom_domain}' "
            f"with value '{txt_record}'. Propagation may take up to 48 hours."
        ),
    }
