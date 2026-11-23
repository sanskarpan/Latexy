"""Admin billing control room, User 360, and audit read surface."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logging import get_logger
from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor, require_admin_or_support
from ..services import admin_user_service
from ..services.admin_audit_service import AdminActor, audit_row_summary, list_admin_audit
from ..services.admin_billing_service import admin_billing_service
from ..services.admin_growth_service import admin_growth_service

router = APIRouter()
logger = get_logger(__name__)

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)]
ShortNote = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)]


class AcknowledgeWebhookRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: Reason


class ReconcileWebhookRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: Optional[ShortNote] = None


class RefundCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payment_id: str = Field(min_length=8, max_length=64)
    amount: Optional[int] = Field(default=None, gt=0, le=100_000_000)
    provider_item_id: Optional[str] = Field(default=None, max_length=255)
    tax_inclusive: bool = True
    reason: Reason


class RefundDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: ShortNote


class RefundExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: Optional[ShortNote] = None


class PiiRevealRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: Literal["email", "name"]
    reason: Reason


class CredentialRevokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Reason


class UserPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan: str = Field(min_length=1, max_length=50)
    status: Literal["active", "inactive", "trialing", "past_due", "cancelled", "comped"] = "active"
    reason: Reason


class UserActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Reason


class UserQuotaResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Reason
    dimension: Optional[Literal["compilations", "optimizations", "ai_assists"]] = None


class UserApiKeyRevokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Reason
    scope: Literal["byok", "developer", "all"] = "all"


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        message = str(exc.args[0]) if exc.args else "Not found"
        return HTTPException(status_code=404, detail=message)
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    logger.error("Admin control room action failed", extra={"error_type": type(exc).__name__})
    return HTTPException(status_code=503, detail="The admin action could not be completed")


# ------------------------------------------------------------------ #
#  Billing summary and webhook desktop                                  #
# ------------------------------------------------------------------ #

@router.get("/admin/billing/summary")
async def get_admin_billing_summary(
    days: int = Query(30, ge=1, le=365),
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    try:
        return await admin_billing_service.summary(
            db,
            days=days,
            start=start or start_date,
            end=end or end_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/admin/billing/webhooks")
async def list_admin_billing_webhooks(
    status: Optional[str] = Query(None, max_length=24),
    event_type: Optional[str] = Query(None, max_length=120),
    acknowledged: Optional[bool] = Query(None),
    received_after: Optional[datetime] = Query(None),
    received_before: Optional[datetime] = Query(None),
    dead_letter: Optional[bool] = Query(None),
    q: Optional[str] = Query(None, max_length=200),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    try:
        items, total = await admin_billing_service.list_webhooks(
            db,
            status=status,
            event_type=event_type,
            acknowledged=acknowledged,
            received_after=received_after,
            received_before=received_before,
            dead_letter=dead_letter,
            q=q,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.post("/admin/billing/webhooks/{event_id}/acknowledge")
async def acknowledge_admin_billing_webhook(
    event_id: str,
    body: AcknowledgeWebhookRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    try:
        return await admin_billing_service.acknowledge_webhook(
            db, event_id=event_id, actor=actor, note=body.note, request=request
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/admin/billing/webhooks/{event_id}/reconcile")
async def reconcile_admin_billing_webhook(
    event_id: str,
    body: ReconcileWebhookRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    try:
        return await admin_billing_service.reconcile_webhook(
            db, event_id=event_id, actor=actor, note=body.note, request=request
        )
    except Exception as exc:
        raise _http_error(exc) from exc


# ------------------------------------------------------------------ #
#  Refund approval queue                                                #
# ------------------------------------------------------------------ #

@router.get("/admin/billing/refunds")
async def list_admin_refund_requests(
    status: Optional[str] = Query(None, max_length=24),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    items, total = await admin_billing_service.list_refund_requests(
        db, status=status, limit=limit, offset=offset
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.post("/admin/billing/refunds")
async def create_admin_refund_request(
    body: RefundCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    try:
        return await admin_billing_service.create_refund_request(
            db,
            payment_id=body.payment_id,
            amount=body.amount,
            provider_item_id=body.provider_item_id,
            tax_inclusive=body.tax_inclusive,
            reason=body.reason,
            actor=actor,
            request=request,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/admin/billing/refunds/{request_id}/approve")
async def approve_admin_refund_request(
    request_id: str,
    body: RefundDecisionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    try:
        return await admin_billing_service.decide_refund_request(
            db, request_id=request_id, decision="approve", note=body.note, actor=actor, request=request
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/admin/billing/refunds/{request_id}/reject")
async def reject_admin_refund_request(
    request_id: str,
    body: RefundDecisionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    try:
        return await admin_billing_service.decide_refund_request(
            db, request_id=request_id, decision="reject", note=body.note, actor=actor, request=request
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/admin/billing/refunds/{request_id}/execute")
async def execute_admin_refund_request(
    request_id: str,
    body: RefundExecuteRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    try:
        return await admin_billing_service.execute_refund_request(
            db, request_id=request_id, actor=actor, note=body.note or "", request=request
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/admin/billing/refunds/{request_id}/reconcile")
async def reconcile_admin_refund_request(
    request_id: str,
    body: RefundExecuteRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    try:
        return await admin_billing_service.reconcile_refund_request(
            db, request_id=request_id, actor=actor, note=body.note or "", request=request
        )
    except Exception as exc:
        raise _http_error(exc) from exc


# ------------------------------------------------------------------ #
#  User 360 + audited support actions                                  #
# ------------------------------------------------------------------ #

@router.get("/admin/users/{user_id}/360")
async def get_admin_user_360(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_or_support),
) -> dict[str, Any]:
    try:
        return await admin_user_service.build_user_360(
            db, user_id=user_id, actor_role=actor.role
        )
    except Exception as exc:
        raise _http_error(exc) from exc


async def _reveal_admin_user_pii(
    user_id: str,
    body: PiiRevealRequest,
    request: Request,
    db: AsyncSession,
    actor: AdminActor,
) -> dict[str, Any]:
    try:
        return await admin_user_service.reveal_user_pii(
            db,
            user_id=user_id,
            field=body.field,
            actor=actor,
            reason=body.reason,
            request=request,
        )
    except admin_user_service.RevealRateLimited as exc:
        raise HTTPException(
            status_code=429,
            detail="PII reveal rate limit exceeded; try again later",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/admin/users/{user_id}/reveal-pii")
async def reveal_admin_user_pii(
    user_id: str,
    body: PiiRevealRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    return await _reveal_admin_user_pii(user_id, body, request, db, actor)


@router.post("/admin/users/{user_id}/pii/reveal", deprecated=True)
async def reveal_admin_user_pii_legacy(
    user_id: str,
    body: PiiRevealRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Deprecated alias; same single-field contract as /reveal-pii."""
    return await _reveal_admin_user_pii(user_id, body, request, db, actor)


@router.post("/admin/users/{user_id}/plan")
async def change_admin_user_plan(
    user_id: str,
    body: UserPlanRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    try:
        return await admin_user_service.set_user_plan(
            db,
            user_id=user_id,
            plan=body.plan,
            status=body.status,
            actor=actor,
            reason=body.reason,
            request=request,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/admin/users/{user_id}/trial/reset")
async def reset_admin_user_trial(
    user_id: str,
    body: UserActionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    try:
        return await admin_user_service.reset_user_trial(
            db, user_id=user_id, actor=actor, reason=body.reason, request=request
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/admin/users/{user_id}/quota/reset")
async def reset_admin_user_quota(
    user_id: str,
    body: UserQuotaResetRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    try:
        return await admin_user_service.reset_user_quota(
            db,
            user_id=user_id,
            dimension=body.dimension,
            actor=actor,
            reason=body.reason,
            request=request,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/admin/users/{user_id}/sessions/revoke")
async def revoke_admin_user_sessions(
    user_id: str,
    body: UserActionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    try:
        return await admin_user_service.revoke_user_sessions(
            db, user_id=user_id, actor=actor, reason=body.reason, request=request
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/admin/users/{user_id}/passkeys/revoke")
async def revoke_admin_user_passkeys(
    user_id: str,
    body: UserActionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    try:
        return await admin_user_service.revoke_user_passkeys(
            db, user_id=user_id, actor=actor, reason=body.reason, request=request
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/admin/users/{user_id}/api-keys/revoke")
async def revoke_admin_user_api_keys(
    user_id: str,
    body: UserApiKeyRevokeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    try:
        return await admin_user_service.revoke_user_api_keys(
            db, user_id=user_id, scope=body.scope, actor=actor, reason=body.reason, request=request
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/admin/users/{user_id}/sessions/{session_id}/revoke")
async def revoke_admin_user_session(
    user_id: str,
    session_id: str,
    body: CredentialRevokeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    try:
        return await admin_user_service.revoke_user_session(
            db,
            user_id=user_id,
            session_id=session_id,
            actor=actor,
            reason=body.reason,
            request=request,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/admin/users/{user_id}/passkeys/{passkey_id}/revoke")
async def revoke_admin_user_passkey(
    user_id: str,
    passkey_id: str,
    body: CredentialRevokeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    try:
        return await admin_user_service.revoke_user_passkey(
            db,
            user_id=user_id,
            passkey_id=passkey_id,
            actor=actor,
            reason=body.reason,
            request=request,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/admin/users/{user_id}/byok-keys/{key_id}/revoke")
async def revoke_admin_user_byok_key(
    user_id: str,
    key_id: str,
    body: CredentialRevokeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    try:
        return await admin_user_service.revoke_user_byok_key(
            db,
            user_id=user_id,
            key_id=key_id,
            actor=actor,
            reason=body.reason,
            request=request,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/admin/users/{user_id}/developer-keys/{key_id}/revoke")
async def revoke_admin_user_developer_key(
    user_id: str,
    key_id: str,
    body: CredentialRevokeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    try:
        return await admin_user_service.revoke_user_developer_key(
            db,
            user_id=user_id,
            key_id=key_id,
            actor=actor,
            reason=body.reason,
            request=request,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


# ------------------------------------------------------------------ #
#  Activation, retention, AI cost, and dimension-filtered series       #
# ------------------------------------------------------------------ #

@router.get("/admin/analytics/activation")
async def get_admin_activation(
    days: int = Query(30, ge=1, le=365),
    plan: Optional[str] = Query(None, max_length=50),
    provider: Optional[str] = Query(None, max_length=64),
    activation_window_days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    try:
        return await admin_growth_service.activation(
            db,
            days=days,
            plan=plan,
            provider=provider,
            activation_window_days=activation_window_days,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/admin/analytics/retention")
async def get_admin_retention(
    weeks: int = Query(8, ge=1, le=26),
    signup_month: Optional[str] = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    try:
        return await admin_growth_service.retention(db, weeks=weeks, signup_month=signup_month)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/admin/analytics/ai-cost")
async def get_admin_ai_cost(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    return await admin_growth_service.ai_cost(db, days=days)


@router.get("/admin/analytics/timeseries")
async def get_admin_analytics_timeseries(
    days: int = Query(30, ge=1, le=365),
    metric: Literal[
        "events",
        "compilations",
        "optimizations",
        "revenue",
        "new_users",
        "active_users",
    ] = Query("events"),
    dimension: Optional[Literal["plan", "provider", "feature", "signup_cohort"]] = Query(None),
    value: Optional[str] = Query(None, max_length=120),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    try:
        return await admin_growth_service.timeseries(
            db, days=days, metric=metric, dimension=dimension, value=value
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# ------------------------------------------------------------------ #
#  Audit read surface                                                  #
# ------------------------------------------------------------------ #

@router.get("/admin/audit")
async def get_admin_audit_log(
    actor_user_id: Optional[str] = Query(None, max_length=36),
    action: Optional[str] = Query(None, max_length=120),
    target_type: Optional[str] = Query(None, max_length=50),
    target_id: Optional[str] = Query(None, max_length=255),
    created_after: Optional[datetime] = Query(None),
    created_before: Optional[datetime] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    rows, total = await list_admin_audit(
        db,
        actor_user_id=actor_user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        created_after=created_after,
        created_before=created_before,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [audit_row_summary(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }
