"""
Tenant admin CRUD API — Feature 85D.

prefix: /tenants

All write endpoints require the caller to be the tenant owner or an admin member.
"""

import ipaddress
import json
import logging
import re
import secrets
from datetime import datetime, timezone
from html import escape
from typing import Any, List, Literal, Optional
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, HttpUrl, TypeAdapter, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.redis import get_redis_cache_client
from ..database.connection import get_db
from ..database.models import (
    Resume,
    Tenant,
    TenantMember,
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceResume,
)
from ..middleware.auth_middleware import get_current_user_required
from ..middleware.tenant_middleware import (
    get_current_tenant,
    invalidate_tenant_cache,
    resolve_tenant_origin_hostname,
)
from ..services.email_service import email_service
from ..utils.uuid_guard import ensure_uuid

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tenants", tags=["tenants"])

_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_SLUG_RE = re.compile(r"^[a-z0-9-]{3,40}$")
_HTTP_URL = TypeAdapter(HttpUrl)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Allowed white-label plans and their server-side seat caps. The client-supplied
# plan_id is validated against this map and max_members is ALWAYS derived
# server-side — never trusted from the request or left to the DB default.
_TENANT_PLANS: dict[str, int] = {"agency": 50, "university": 200}
# Cap the number of tenants a single user may provision to curb abuse.
_MAX_TENANTS_PER_USER = 10


def _validate_logo_url(value: Optional[str]) -> Optional[str]:
    """Allow remote HTTPS assets without obvious local-network targets."""
    if value is None:
        return None
    normalized = str(_HTTP_URL.validate_python(value))
    parsed = urlsplit(normalized)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or hostname == "localhost" or hostname.endswith(
        (".localhost", ".local", ".internal")
    ):
        raise ValueError("logo_url must be a public HTTPS URL")
    try:
        address = ipaddress.ip_address(hostname.strip("[]"))
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ValueError("logo_url must be a public HTTPS URL")
    return normalized


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

    @field_validator("logo_url")
    @classmethod
    def validate_logo_url(cls, v: Optional[str]) -> Optional[str]:
        return _validate_logo_url(v)


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

    @field_validator("logo_url")
    @classmethod
    def validate_logo_url(cls, v: Optional[str]) -> Optional[str]:
        return _validate_logo_url(v)

    @field_validator("custom_domain")
    @classmethod
    def validate_domain(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        domain = value.strip().lower().rstrip(".")
        if not domain:
            return None
        parsed = urlsplit(f"https://{domain}")
        if (
            parsed.hostname != domain
            or parsed.port is not None
            or "/" in domain
            or "@" in domain
            or len(domain) > 253
            or "." not in domain
            or domain in {"latexy.xyz", "www.latexy.xyz"}
            or domain.endswith((".vercel.app", ".modal.run", ".latexy.io"))
        ):
            raise ValueError("custom_domain must be a valid external hostname")
        labels = domain.split(".")
        if any(
            not label
            or len(label) > 63
            or label.startswith("-")
            or label.endswith("-")
            or not re.fullmatch(r"[a-z0-9-]+", label)
            for label in labels
        ):
            raise ValueError("custom_domain must be a valid external hostname")
        return domain


class TenantResponse(BaseModel):
    id: str
    slug: str
    name: str
    logo_url: Optional[str]
    primary_color: Optional[str]
    custom_domain: Optional[str]
    domain_verified: bool
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
    cohort_id: Optional[str] = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _EMAIL_RE.match(normalized):
            raise ValueError("Invalid email address")
        return normalized


class InvitationResponse(BaseModel):
    email: str
    role: str
    expires_in_seconds: int
    cohort_id: Optional[str] = None
    invite_preview_url: Optional[str] = None
    message: str


class TenantStats(BaseModel):
    member_count: int


class CurrentContextResponse(BaseModel):
    tenant: Optional[dict[str, Any]]


class CohortCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)


class CohortResponse(BaseModel):
    id: str
    name: str
    member_count: int
    resume_count: int
    created_at: datetime


class CohortSubmissionResponse(BaseModel):
    resume_id: str
    title: str
    student_user_id: str
    student_email: str
    student_name: Optional[str]
    started_at: datetime
    # These legacy timestamps are candidate self-activity milestones. They do
    # not indicate that an employer/reviewer opened or downloaded a resume.
    opened_at: Optional[datetime]
    opened_actor: Optional[Literal["candidate"]]
    opened_source: Optional[Literal["candidate_self"]]
    downloaded_at: Optional[datetime]
    downloaded_actor: Optional[Literal["candidate"]]
    downloaded_source: Optional[Literal["candidate_self"]]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _tenant_response(t: Tenant) -> TenantResponse:
    return TenantResponse(
        id=t.id,
        slug=t.slug,
        name=t.name,
        logo_url=t.logo_url,
        primary_color=t.primary_color,
        custom_domain=t.custom_domain,
        domain_verified=t.domain_verified_at is not None,
        plan_id=t.plan_id,
        max_members=t.max_members,
        active=t.active,
        owner_id=t.owner_id,
        created_at=t.created_at,
    )


async def _require_tenant_owner_or_admin(
    tenant_id: str, user_id: str, db: AsyncSession, *, lock: bool = True
) -> Tenant:
    ensure_uuid(tenant_id, "Tenant not found")
    tenant_query = select(Tenant).where(Tenant.id == tenant_id)
    if lock:
        tenant_query = tenant_query.with_for_update()
    result = await db.execute(tenant_query)
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


@router.get("/resolve-host", response_model=CurrentContextResponse)
async def resolve_tenant_host(
    host: str = Query(..., min_length=1, max_length=253),
) -> CurrentContextResponse:
    """Resolve public branding from a frontend hostname without exposing owner data."""
    hostname = host.strip().lower().rstrip(".")
    if not re.fullmatch(r"[a-z0-9.-]+", hostname):
        raise HTTPException(status_code=400, detail="Invalid hostname")
    tenant = await resolve_tenant_origin_hostname(hostname)
    return CurrentContextResponse(tenant=tenant)


@router.post("", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    body: TenantCreate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> TenantResponse:
    """Provision a tenant. This is an admin-controlled enterprise operation."""
    # Serialize provisioning for one owner so the per-user tenant cap cannot be
    # exceeded by concurrent requests that both observe the same count.
    provisioner = await db.execute(
        select(User.role, User.subscription_plan)
        .where(User.id == user_id)
        .with_for_update()
    )
    provisioner_row = provisioner.one_or_none()
    if not provisioner_row or (
        provisioner_row.role != "admin" and provisioner_row.subscription_plan != "team"
    ):
        raise HTTPException(status_code=403, detail="Team plan or platform administrator access required")
    # Validate the requested plan against the server-side whitelist and derive
    # the seat cap from it (never trust a client-supplied max_members / plan).
    plan_id = body.plan_id if body.plan_id in _TENANT_PLANS else "agency"
    if plan_id == "university" and provisioner_row.role != "admin":
        raise HTTPException(status_code=403, detail="University tenants require administrator provisioning")
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
    try:
        await db.flush()

        # Owner is automatically added as an admin member
        owner_member = TenantMember(tenant_id=tenant.id, user_id=user_id, role="admin")
        db.add(owner_member)
        await db.commit()
    except IntegrityError as exc:
        # The pre-check is only advisory under concurrency; let the database's
        # unique constraint decide and return the same stable API error.
        await db.rollback()
        raise HTTPException(status_code=409, detail="Slug or domain already in use") from exc
    await db.refresh(tenant)
    await invalidate_tenant_cache(slug=tenant.slug)
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


@router.post("/{tenant_id}/cohorts", response_model=CohortResponse, status_code=201)
async def create_cohort(
    tenant_id: str,
    body: CohortCreate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> CohortResponse:
    """Create an institution-owned cohort backed by a private workspace."""
    tenant = await _require_tenant_owner_or_admin(tenant_id, user_id, db)
    cohort = Workspace(
        name=body.name,
        owner_id=user_id,
        tenant_id=tenant.id,
        plan_id=tenant.plan_id,
        max_members=tenant.max_members,
    )
    db.add(cohort)
    await db.flush()
    admin_result = await db.execute(
        select(TenantMember.user_id).where(
            TenantMember.tenant_id == tenant.id,
            TenantMember.role == "admin",
        )
    )
    admin_ids = {row[0] for row in admin_result.all()}
    admin_ids.update({tenant.owner_id, user_id})
    joined_at = datetime.now(timezone.utc)
    for admin_id in admin_ids:
        db.add(
            WorkspaceMember(
                workspace_id=cohort.id,
                user_id=admin_id,
                role="owner" if admin_id == user_id else "editor",
                invited_by=user_id if admin_id != user_id else None,
                joined_at=joined_at,
            )
        )
    await db.commit()
    await db.refresh(cohort)
    return CohortResponse(
        id=cohort.id,
        name=cohort.name,
        member_count=len(admin_ids),
        resume_count=0,
        created_at=cohort.created_at,
    )


@router.get("/{tenant_id}/cohorts", response_model=List[CohortResponse])
async def list_cohorts(
    tenant_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> List[CohortResponse]:
    """List cohorts and their roster/submission counts for tenant admins."""
    await _require_tenant_owner_or_admin(tenant_id, user_id, db)
    cohorts_result = await db.execute(
        select(Workspace).where(Workspace.tenant_id == tenant_id).order_by(Workspace.created_at)
    )
    cohorts = cohorts_result.scalars().all()
    if not cohorts:
        return []
    ids = [cohort.id for cohort in cohorts]
    member_rows = await db.execute(
        select(WorkspaceMember.workspace_id, func.count())
        .where(WorkspaceMember.workspace_id.in_(ids))
        .group_by(WorkspaceMember.workspace_id)
    )
    resume_rows = await db.execute(
        select(WorkspaceResume.workspace_id, func.count())
        .where(WorkspaceResume.workspace_id.in_(ids))
        .group_by(WorkspaceResume.workspace_id)
    )
    member_counts = dict(member_rows.all())
    resume_counts = dict(resume_rows.all())
    return [
        CohortResponse(
            id=cohort.id,
            name=cohort.name,
            member_count=int(member_counts.get(cohort.id, 0)),
            resume_count=int(resume_counts.get(cohort.id, 0)),
            created_at=cohort.created_at,
        )
        for cohort in cohorts
    ]


@router.get(
    "/{tenant_id}/cohorts/{cohort_id}/submissions",
    response_model=List[CohortSubmissionResponse],
)
async def list_cohort_submissions(
    tenant_id: str,
    cohort_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> List[CohortSubmissionResponse]:
    """Show explicitly submitted student resumes and lifecycle milestones."""
    ensure_uuid(cohort_id, "Cohort not found")
    await _require_tenant_owner_or_admin(tenant_id, user_id, db)
    cohort_result = await db.execute(
        select(Workspace).where(
            Workspace.id == cohort_id, Workspace.tenant_id == tenant_id
        )
    )
    if not cohort_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Cohort not found")
    submissions = await db.execute(
        select(WorkspaceResume, Resume, User)
        .join(Resume, Resume.id == WorkspaceResume.resume_id)
        .join(User, User.id == Resume.user_id)
        .where(WorkspaceResume.workspace_id == cohort_id)
        .order_by(WorkspaceResume.shared_at.desc())
    )
    return [
        CohortSubmissionResponse(
            resume_id=resume.id,
            title=resume.title,
            student_user_id=resume.user_id,
            student_email=student.email,
            student_name=student.name,
            started_at=workspace_resume.shared_at,
            opened_at=workspace_resume.opened_at,
            opened_actor="candidate" if workspace_resume.opened_at else None,
            opened_source="candidate_self" if workspace_resume.opened_at else None,
            downloaded_at=workspace_resume.downloaded_at,
            downloaded_actor="candidate" if workspace_resume.downloaded_at else None,
            downloaded_source="candidate_self" if workspace_resume.downloaded_at else None,
        )
        for workspace_resume, resume, student in submissions.all()
    ]


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
    previous_domain = tenant.custom_domain
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

    if "custom_domain" in update_data and new_domain != previous_domain:
        # DNS proof is bound to the exact hostname and cannot carry over.
        tenant.domain_verified_at = None

    for field, value in update_data.items():
        setattr(tenant, field, value)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Domain or slug already in use")
    await db.refresh(tenant)
    await invalidate_tenant_cache(
        slug=tenant.slug,
        current_domain=tenant.custom_domain,
        previous_domain=previous_domain,
    )
    return _tenant_response(tenant)


@router.get("/{tenant_id}/members", response_model=List[MemberResponse])
async def list_members(
    tenant_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> List[MemberResponse]:
    """List all members of a tenant. Requires membership."""
    ensure_uuid(tenant_id, "Tenant not found")
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


@router.post("/{tenant_id}/members/invite", response_model=InvitationResponse, status_code=201)
async def invite_member(
    tenant_id: str,
    body: InviteRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> InvitationResponse:
    """Create an email-bound, expiring invitation without granting access."""
    tenant = await _require_tenant_owner_or_admin(tenant_id, user_id, db)
    if body.role == "admin" and user_id != tenant.owner_id:
        raise HTTPException(status_code=403, detail="Only the owner can invite an admin")

    if body.cohort_id:
        ensure_uuid(body.cohort_id, "Cohort not found")
        cohort_result = await db.execute(
            select(Workspace).where(
                Workspace.id == body.cohort_id, Workspace.tenant_id == tenant_id
            )
        )
        if not cohort_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Cohort not found")

    email = body.email
    invitee_result = await db.execute(
        select(User).where(func.lower(User.email) == email)
    )
    invitee = invitee_result.scalar_one_or_none()

    count_result = await db.execute(
        select(func.count()).where(TenantMember.tenant_id == tenant_id)
    )
    if int(count_result.scalar() or 0) >= tenant.max_members:
        raise HTTPException(
            status_code=409, detail=f"Member limit ({tenant.max_members}) reached"
        )

    if invitee:
        existing = await db.execute(
            select(TenantMember).where(
                TenantMember.tenant_id == tenant_id, TenantMember.user_id == invitee.id
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="User is already a member")

    token = secrets.token_urlsafe(32)
    try:
        redis = await get_redis_cache_client()
        await redis.set(
            f"tenant_invite:{token}",
            json.dumps(
                {
                    "tenant_id": tenant_id,
                    "role": body.role,
                    "email": email,
                    "cohort_id": body.cohort_id,
                },
                separators=(",", ":"),
            ),
            ex=7 * 24 * 3600,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Invitation service is temporarily unavailable. Please retry.",
        ) from exc

    invite_url = f"{settings.FRONTEND_URL}/tenant-invite?token={token}"
    sent = await email_service.send_email(
        to=email,
        subject=f"You’ve been invited to {tenant.name} on Latexy",
        html_body=(
            f"<p>You’ve been invited to join <strong>{escape(tenant.name)}</strong> on Latexy.</p>"
            f"<p><a href=\"{escape(invite_url)}\">Accept invitation</a></p>"
        ),
        text_body=f"You’ve been invited to join {tenant.name}: {invite_url}",
    )
    if settings.EMAIL_ENABLED and not sent:
        try:
            await redis.delete(f"tenant_invite:{token}")
        except Exception:
            pass
        raise HTTPException(status_code=503, detail="The invitation could not be delivered. Please retry.")

    return InvitationResponse(
        email=email,
        role=body.role,
        expires_in_seconds=7 * 24 * 3600,
        cohort_id=body.cohort_id,
        invite_preview_url=(
            invite_url if not settings.EMAIL_ENABLED and not settings.is_production_like() else None
        ),
        message="Tenant invitation created",
    )


@router.post("/invitations/{token}/accept", response_model=MemberResponse)
async def accept_invitation(
    token: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> MemberResponse:
    """Accept a single-use invitation bound to the signed-in account email."""
    redis = await get_redis_cache_client()
    raw = await redis.get(f"tenant_invite:{token}")
    if not raw:
        raise HTTPException(status_code=404, detail="Invitation not found or expired")
    try:
        payload = json.loads(raw)
        tenant_id = payload["tenant_id"]
        role = payload["role"]
        invited_email = payload["email"]
        cohort_id = payload.get("cohort_id")
    except (AttributeError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise HTTPException(status_code=404, detail="Invitation not found or expired")
    ensure_uuid(tenant_id, "Invitation not found")
    if role not in {"admin", "member"}:
        raise HTTPException(status_code=404, detail="Invitation not found or expired")

    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.email.lower() != invited_email.lower():
        raise HTTPException(status_code=403, detail="Invitation email does not match this account")

    tenant_result = await db.execute(
        select(Tenant)
        .where(Tenant.id == tenant_id, Tenant.active.is_(True))
        .with_for_update()
    )
    tenant = tenant_result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    cohort: Workspace | None = None
    if cohort_id:
        ensure_uuid(cohort_id, "Invitation not found")
        cohort_result = await db.execute(
            select(Workspace).where(
                Workspace.id == cohort_id, Workspace.tenant_id == tenant_id
            )
        )
        cohort = cohort_result.scalar_one_or_none()
        if not cohort:
            raise HTTPException(status_code=404, detail="Cohort not found")
    count_result = await db.execute(
        select(func.count()).where(TenantMember.tenant_id == tenant_id)
    )
    if int(count_result.scalar() or 0) >= tenant.max_members:
        raise HTTPException(status_code=409, detail=f"Member limit ({tenant.max_members}) reached")

    existing = await db.execute(
        select(TenantMember).where(
            TenantMember.tenant_id == tenant_id, TenantMember.user_id == user_id
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="User is already a member")
    member = TenantMember(tenant_id=tenant_id, user_id=user_id, role=role)
    db.add(member)
    if role == "admin":
        cohorts_result = await db.execute(
            select(Workspace).where(Workspace.tenant_id == tenant_id)
        )
        for tenant_cohort in cohorts_result.scalars().all():
            cohort_membership = await db.execute(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == tenant_cohort.id,
                    WorkspaceMember.user_id == user_id,
                )
            )
            if not cohort_membership.scalar_one_or_none():
                db.add(
                    WorkspaceMember(
                        workspace_id=tenant_cohort.id,
                        user_id=user_id,
                        role="editor",
                        invited_by=tenant.owner_id,
                        joined_at=datetime.now(timezone.utc),
                    )
                )
    elif cohort:
        cohort_membership = await db.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == cohort.id,
                WorkspaceMember.user_id == user_id,
            )
        )
        if not cohort_membership.scalar_one_or_none():
            db.add(
                WorkspaceMember(
                    workspace_id=cohort.id,
                    user_id=user_id,
                    role="viewer",
                    invited_by=tenant.owner_id,
                    joined_at=datetime.now(timezone.utc),
                )
            )
    try:
        await db.commit()
        await db.refresh(member)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="User is already a member")
    try:
        await redis.delete(f"tenant_invite:{token}")
    except Exception:
        pass
    return MemberResponse(
        user_id=user.id,
        email=user.email,
        name=user.name,
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
    ensure_uuid(target_user_id, "Member not found")
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

    cohort_memberships_result = await db.execute(
        select(WorkspaceMember)
        .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
        .where(
            Workspace.tenant_id == tenant_id,
            WorkspaceMember.user_id == target_user_id,
        )
    )
    for cohort_membership in cohort_memberships_result.scalars().all():
        await db.delete(cohort_membership)
    await db.delete(member)
    await db.commit()


@router.delete("/{tenant_id}/membership", status_code=204, response_model=None)
async def leave_tenant(
    tenant_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> None:
    """Let a non-owner member remove their own tenant membership."""
    ensure_uuid(tenant_id, "Tenant not found")
    tenant_result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = tenant_result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if tenant.owner_id == user_id:
        raise HTTPException(status_code=403, detail="The tenant owner cannot leave")
    member_result = await db.execute(
        select(TenantMember).where(
            TenantMember.tenant_id == tenant_id, TenantMember.user_id == user_id
        )
    )
    member = member_result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Membership not found")
    cohort_memberships_result = await db.execute(
        select(WorkspaceMember)
        .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
        .where(
            Workspace.tenant_id == tenant_id,
            WorkspaceMember.user_id == user_id,
        )
    )
    for cohort_membership in cohort_memberships_result.scalars().all():
        await db.delete(cohort_membership)
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

    # Personal documents do not become institution-owned when their author
    # joins a tenant. Never aggregate private resume activity by membership.
    return TenantStats(member_count=member_count)


@router.post("/{tenant_id}/domain/verify", status_code=200)
async def verify_domain(
    tenant_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> dict:
    """
    Verify DNS ownership. Until the expected TXT value resolves publicly, the
    custom hostname remains inactive in tenant middleware.
    """
    tenant = await _require_tenant_owner_or_admin(tenant_id, user_id, db, lock=False)
    if not tenant.custom_domain:
        raise HTTPException(
            status_code=400, detail="No custom_domain set for this tenant"
        )
    txt_record = f"latexy-verify={tenant.id}"
    record_name = f"_latexy.{tenant.custom_domain}"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(
                "https://cloudflare-dns.com/dns-query",
                params={"name": record_name, "type": "TXT"},
                headers={"accept": "application/dns-json"},
            )
            response.raise_for_status()
            answers = response.json().get("Answer") or []
            values = {
                str(answer.get("data", "")).strip().strip('"')
                for answer in answers
                if int(answer.get("type", 0)) == 16
            }
            verified = txt_record in values
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=503,
            detail="DNS verification is temporarily unavailable. Please retry.",
        ) from exc

    verification_changed = (verified and tenant.domain_verified_at is None) or (
        not verified and tenant.domain_verified_at is not None
    )
    if verification_changed:
        tenant.domain_verified_at = datetime.now(timezone.utc) if verified else None
        await db.commit()
        await db.refresh(tenant)
        await invalidate_tenant_cache(
            slug=tenant.slug, current_domain=tenant.custom_domain
        )

    return {
        "domain": tenant.custom_domain,
        "verified": tenant.domain_verified_at is not None,
        "txt_record_name": record_name,
        "txt_record_value": txt_record,
        "instructions": (
            f"Add a DNS TXT record named '{record_name}' "
            f"with value '{txt_record}'. Propagation may take up to 48 hours."
        ),
    }
