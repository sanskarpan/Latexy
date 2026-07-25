"""Admin feature flag endpoints.

GET  /config/feature-flags       — public, no auth — {key: bool, ...}
GET  /admin/feature-flags        — admin only — full objects
PATCH /admin/feature-flags/{key} — admin only — {enabled: bool}
"""

from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.errors import error_body
from ..database.connection import get_db
from ..database.models import User
from ..middleware.auth_middleware import require_admin
from ..services.entitlement_service import entitlement_service
from ..services.feature_flag_service import feature_flag_service

router = APIRouter()

# RBAC roles assignable via the admin API.
_ASSIGNABLE_ROLES = frozenset({"user", "support", "admin"})

# Flags that are safe to expose to unauthenticated clients. Everything else is
# admin-only, so unreleased/internal flag names are not disclosed publicly.
PUBLIC_FLAG_KEYS = frozenset({
    "trial_limits",
    "deep_analysis_trial",
    "compile_timeouts",
    "task_priority",
    "billing",
    "upgrade_ctas",
})


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
    """Return a flat {key: bool} map of client-facing feature flags. No auth required.

    Only flags in PUBLIC_FLAG_KEYS are exposed; internal/unreleased flags stay
    admin-only to avoid leaking their names and rollout state.
    """
    flags = await feature_flag_service.get_all_flags(db)
    return {f.key: f.enabled for f in flags if f.key in PUBLIC_FLAG_KEYS}


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


# ------------------------------------------------------------------ #
#  Admin — entitlements (kill-switches + per-plan matrix)             #
# ------------------------------------------------------------------ #

class KillSwitchUpdateRequest(BaseModel):
    enabled: bool


class MatrixUpdateRequest(BaseModel):
    plan_family: str
    feature_key: str
    enabled: bool


@router.get("/admin/entitlements")
async def get_entitlements(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin),
) -> dict:
    """Return full entitlement state (registry + kill_switches + matrix + plan_families). Admin only."""
    return await entitlement_service.get_state(db)


@router.patch("/admin/entitlements/kill-switch/{key}")
async def update_kill_switch(
    key: str,
    body: KillSwitchUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin),
) -> dict:
    """Toggle a global feature kill-switch. Admin only. 404 if the key is not gateable."""
    try:
        await entitlement_service.set_kill_switch(key, body.enabled, db)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=error_body(
                "feature_not_found",
                f"Unknown or non-gateable feature: {key!r}",
                None,
            ),
        )
    return await entitlement_service.get_state(db)


@router.patch("/admin/entitlements/matrix")
async def update_matrix_cell(
    body: MatrixUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin),
) -> dict:
    """Set a per-plan-family feature cell. Admin only.

    400 on an unknown plan family, 404 on an unknown/non-gateable feature key.
    """
    from ..core.feature_registry import PLAN_FAMILIES, is_gateable

    if body.plan_family not in PLAN_FAMILIES:
        raise HTTPException(
            status_code=400,
            detail=error_body(
                "invalid_plan_family",
                f"Unknown plan family: {body.plan_family!r}",
                None,
            ),
        )
    if not is_gateable(body.feature_key):
        raise HTTPException(
            status_code=404,
            detail=error_body(
                "feature_not_found",
                f"Unknown or non-gateable feature: {body.feature_key!r}",
                None,
            ),
        )
    await entitlement_service.set_matrix_cell(
        body.plan_family, body.feature_key, body.enabled, db
    )
    return await entitlement_service.get_state(db)


# ------------------------------------------------------------------ #
#  Admin — user management                                            #
# ------------------------------------------------------------------ #

class UserSummary(BaseModel):
    id: str
    email: str
    name: Optional[str]
    role: str
    subscription_plan: str
    email_verified: bool
    created_at: Optional[datetime]


class UserListResponse(BaseModel):
    users: List[UserSummary]
    total: int


class RoleUpdateRequest(BaseModel):
    role: str


def _user_summary(user: User) -> UserSummary:
    return UserSummary(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role,
        subscription_plan=user.subscription_plan,
        email_verified=bool(user.email_verified),
        created_at=user.created_at,
    )


@router.get("/admin/users", response_model=UserListResponse)
async def list_users(
    q: Optional[str] = Query(None, description="Email (or name) search substring"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    """List users with optional email search + pagination. Admin only."""
    filters = []
    if q:
        pattern = f"%{q.strip()}%"
        filters.append(or_(User.email.ilike(pattern), User.name.ilike(pattern)))

    count_stmt = select(func.count()).select_from(User)
    list_stmt = select(User).order_by(User.created_at.desc()).limit(limit).offset(offset)
    for f in filters:
        count_stmt = count_stmt.where(f)
        list_stmt = list_stmt.where(f)

    total = (await db.execute(count_stmt)).scalar_one()
    rows = (await db.execute(list_stmt)).scalars().all()
    return UserListResponse(
        users=[_user_summary(u) for u in rows],
        total=int(total),
    )


@router.patch("/admin/users/{user_id}/role", response_model=UserSummary)
async def update_user_role(
    user_id: str,
    body: RoleUpdateRequest,
    db: AsyncSession = Depends(get_db),
    admin_user_id: str = Depends(require_admin),
):
    """Change a user's RBAC role. Admin only.

    Guards:
      - 400 on an invalid role.
      - 409 when the change would remove the last remaining admin (including an
        admin demoting themselves as the last admin).
    """
    new_role = body.role.strip().lower()
    if new_role not in _ASSIGNABLE_ROLES:
        raise HTTPException(
            status_code=400,
            detail=error_body(
                "invalid_role",
                f"Role must be one of {sorted(_ASSIGNABLE_ROLES)}",
                None,
            ),
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=404,
            detail=error_body("user_not_found", f"User {user_id!r} not found", None),
        )

    # Last-admin guard: block demoting the only remaining admin (covers an admin
    # demoting themselves). No-op if the role is unchanged.
    if user.role == "admin" and new_role != "admin":
        admin_count = (
            await db.execute(
                select(func.count()).select_from(User).where(User.role == "admin")
            )
        ).scalar_one()
        if int(admin_count) <= 1:
            raise HTTPException(
                status_code=409,
                detail=error_body(
                    "last_admin",
                    "Cannot remove the last remaining admin.",
                    None,
                ),
            )

    user.role = new_role
    await db.commit()
    await db.refresh(user)
    return _user_summary(user)
