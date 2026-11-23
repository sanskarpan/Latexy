"""Admin feature flag endpoints.

GET  /config/feature-flags       — public, no auth — {key: bool, ...}
GET  /admin/feature-flags        — admin only — full objects
PATCH /admin/feature-flags/{key} — admin only — {enabled: bool}
"""

from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.errors import error_body
from ..core.log_sanitize import sanitize_for_log
from ..core.logging import get_logger
from ..database.connection import get_db
from ..database.models import User
from ..middleware.auth_middleware import require_admin, require_admin_actor, require_support_actor
from ..services.admin_audit_service import AdminActor, record_admin_audit
from ..services.admin_user_service import mask_email, mask_name
from ..services.entitlement_service import entitlement_service
from ..services.feature_flag_service import feature_flag_service
from ..services.posthog_service import posthog_service

router = APIRouter()
logger = get_logger(__name__)

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
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
):
    """Toggle a feature flag. Admin only."""
    try:
        before_enabled = await feature_flag_service.get_flag(key, db)
        flag = await feature_flag_service.update_flag(key, body.enabled, db, commit=False)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Feature flag {key!r} not found")
    try:
        await record_admin_audit(
            db,
            actor=actor,
            action="feature_flag.update",
            target_type="feature_flag",
            target_id=key,
            before={"enabled": before_enabled},
            after={"enabled": flag.enabled},
            request=request,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="The change could not be audited, so it was not applied")
    if key in PUBLIC_FLAG_KEYS:
        await feature_flag_service.sync_flag_cache(key, flag.enabled)
    # Keep every request-derived value out of the log sink. The immutable admin
    # audit row above is the authoritative actor/target/state record.
    logger.info("admin_feature_flag_updated")
    posthog_service.capture(
        actor.user_id,
        "backend_admin_flag_changed",
        {"feature_key": key, "enabled": body.enabled, "surface": "admin"},
    )
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
    expected_enabled: bool | None = None


class MatrixUpdateRequest(BaseModel):
    plan_family: str
    feature_key: str
    enabled: bool
    expected_enabled: bool | None = None


class RoleMatrixUpdateRequest(BaseModel):
    role: str
    feature_key: str
    enabled: bool
    expected_enabled: bool | None = None


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
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict:
    """Toggle a global feature kill-switch. Admin only. 404 if the key is not gateable."""
    before_state = await entitlement_service.get_state(db)
    try:
        await entitlement_service.set_kill_switch(
            key, body.enabled, db, expected_enabled=body.expected_enabled, commit=False
        )
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=error_body(
                "feature_not_found",
                f"Unknown or non-gateable feature: {key!r}",
                None,
            ),
        )
    try:
        await record_admin_audit(
            db,
            actor=actor,
            action="entitlement.kill_switch.update",
            target_type="feature_key",
            target_id=key,
            before={"enabled": before_state["kill_switches"].get(key)},
            after={"enabled": body.enabled},
            request=request,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="The change could not be audited, so it was not applied")
    logger.info("admin_kill_switch_updated")
    posthog_service.capture(
        actor.user_id,
        "backend_admin_kill_switch_changed",
        {"feature_key": key, "enabled": body.enabled, "surface": "admin"},
    )
    return await entitlement_service.get_state(db)


@router.patch("/admin/entitlements/matrix")
async def update_matrix_cell(
    body: MatrixUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict:
    """Set a per-plan-family feature cell. Admin only.

    400 on an unknown plan family, 404 on an unknown/non-gateable feature key.
    """
    from ..core.feature_registry import PLAN_MATRIX_KEYS, is_gateable

    if body.plan_family not in PLAN_MATRIX_KEYS:
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
    before_state = await entitlement_service.get_state(db)
    await entitlement_service.set_matrix_cell(
        body.plan_family, body.feature_key, body.enabled, db,
        expected_enabled=body.expected_enabled, commit=False,
    )
    try:
        await record_admin_audit(
            db,
            actor=actor,
            action="entitlement.matrix.update",
            target_type="plan_feature",
            target_id=f"{body.plan_family}:{body.feature_key}",
            before={"enabled": before_state["matrix"].get(body.plan_family, {}).get(body.feature_key)},
            after={"enabled": body.enabled},
            request=request,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="The change could not be audited, so it was not applied")
    logger.info(
        "admin_entitlement_matrix_updated",
        extra={
            "admin_user_id": sanitize_for_log(actor.user_id),
            "plan_family": sanitize_for_log(body.plan_family),
            "feature_key": sanitize_for_log(body.feature_key),
        },
    )
    posthog_service.capture(
        actor.user_id,
        "backend_admin_entitlement_changed",
        {"plan_key": body.plan_family, "feature_key": body.feature_key,
         "enabled": body.enabled, "surface": "admin"},
    )
    return await entitlement_service.get_state(db)


def _log_role_toggle(admin_user_id: str, role: str, feature_key: str, enabled: bool) -> None:
    """Keep the audit useful with JSON or plain-text handlers and one record per change."""
    # Inputs are canonical registry values/server-owned identity. Escape line
    # breaks again at the sink so a future caller cannot forge audit records.
    def one_line(value: str) -> str:
        return (value.replace("\r", "\\r").replace("\n", "\\n")
                .replace("\x85", "\\x85").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))

    # JsonFormatter intentionally allowlists extra fields and excludes these.
    # Include bounded identifiers in the message so the audit is not empty.
    logger.info(
        "admin_entitlement_role_updated admin_user_id=%s role=%s feature_key=%s enabled=%s",
        one_line(admin_user_id), one_line(role), one_line(feature_key),
        one_line(str(bool(enabled))),
    )


@router.patch("/admin/entitlements/roles")
async def update_role_matrix_cell(
    body: RoleMatrixUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict:
    """Restrict one account role/context; document and tenant ACLs are unchanged."""
    from ..core.feature_registry import CAPABILITY_ROLES, get_feature

    # Resolve to the registry's canonical objects before persisting or logging.
    # Never send raw request strings to the security audit event.
    role = next((known for known in CAPABILITY_ROLES if known == body.role), None)
    if role is None:
        raise HTTPException(status_code=400, detail=error_body(
            "invalid_capability_role", f"Unknown account role/context: {body.role!r}", None,
        ))
    feature = get_feature(body.feature_key)
    if feature is None or not feature.gateable:
        raise HTTPException(status_code=404, detail=error_body(
            "feature_not_found", f"Unknown or non-gateable feature: {body.feature_key!r}", None,
        ))
    before_state = await entitlement_service.get_state(db)
    await entitlement_service.set_role_cell(
        role, feature.key, body.enabled, db,
        expected_enabled=body.expected_enabled, commit=False,
    )
    try:
        await record_admin_audit(
            db,
            actor=actor,
            action="entitlement.role.update",
            target_type="role_feature",
            target_id=f"{role}:{feature.key}",
            before={"enabled": (before_state.get("role_matrix") or {}).get(role, {}).get(feature.key)},
            after={"enabled": body.enabled},
            request=request,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="The change could not be audited, so it was not applied")
    _log_role_toggle(actor.user_id, role, feature.key, body.enabled)
    posthog_service.capture(
        actor.user_id,
        "backend_admin_role_matrix_changed",
        {"role": role, "feature_key": feature.key, "enabled": body.enabled, "surface": "admin"},
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


def _user_summary(user: User, *, masked: bool = False) -> UserSummary:
    return UserSummary(
        id=user.id,
        email=(mask_email(user.email) or "***") if masked else user.email,
        name=mask_name(user.name) if masked else user.name,
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
    actor: AdminActor = Depends(require_support_actor),
):
    """List users with optional email search + pagination.

    Support sees masked addresses and can open the masked User 360. Admin sees
    the account address and can reveal it through the audited PII endpoint.
    """
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
        users=[_user_summary(u, masked=actor.role != "admin") for u in rows],
        total=int(total),
    )


@router.patch("/admin/users/{user_id}/role", response_model=UserSummary)
async def update_user_role(
    user_id: str,
    body: RoleUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
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

    # Serialize role mutations around one transaction-scoped advisory lock so
    # concurrent demotions cannot both observe the same last-admin count.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:lock_id)"),
        {"lock_id": 4_752_861_103},
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

    previous_role = user.role
    user.role = new_role
    await record_admin_audit(
        db,
        actor=actor,
        action="user.role.change",
        target_type="user",
        target_id=user_id,
        reason="Role change from the admin control plane",
        before={"role": previous_role},
        after={"role": new_role},
        request=request,
    )
    await db.commit()
    await db.refresh(user)
    logger.info(
        "admin_user_role_updated",
        extra={
            "admin_user_id": sanitize_for_log(actor.user_id),
            "target_user_id": sanitize_for_log(user_id),
            "previous_role": sanitize_for_log(previous_role),
            "new_role": sanitize_for_log(new_role),
        },
    )
    posthog_service.capture(
        actor.user_id,
        "backend_admin_user_role_changed",
        {"target_user_id": user_id, "previous_role": previous_role,
         "new_role": new_role, "surface": "admin"},
    )
    return _user_summary(user)
