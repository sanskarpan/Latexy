"""User 360 composition and audited support actions.

This module deliberately composes existing tables. It never reads or returns
resume LaTeX, structured document content, prompts, job descriptions, or API-key
values. Support can see a masked account view; only an admin can reveal PII.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import QUOTA_DIMENSIONS, get_plan_quota_window, settings
from ..core.redis import cache_manager
from ..database import models
from .admin_audit_service import AdminActor, audit_row_summary, record_admin_audit

USER_360_CACHE_TTL = 60
USER_360_CACHE_PREFIX = "admin:user360:v1"

User = models.User
Resume = models.Resume
Compilation = models.Compilation
Optimization = models.Optimization
UsageAnalytics = models.UsageAnalytics
Subscription = models.Subscription
Payment = models.Payment
PaymentRefund = models.PaymentRefund
AdminRefundRequest = models.AdminRefundRequest
UserAPIKey = models.UserAPIKey
DeveloperAPIKey = models.DeveloperAPIKey
TenantMember = models.TenantMember
ReferralAttribution = models.ReferralAttribution


def mask_email(value: str | None) -> str | None:
    if not value or "@" not in value:
        return None
    local, domain = value.split("@", 1)
    if not local:
        return f"***@{domain}"
    visible = local[0] if len(local) <= 2 else local[:2]
    return f"{visible}{'*' * max(3, len(local) - len(visible))}@{domain}"


def mask_name(value: str | None) -> str | None:
    if not value:
        return None
    letters = [part for part in value.split() if part]
    return " ".join(f"{part[0]}{'*' * max(2, len(part) - 1)}" for part in letters[:4]) or "***"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _provider_presence(user: User) -> dict[str, bool]:
    meta = user.user_metadata if isinstance(user.user_metadata, dict) else {}
    return {
        "github": bool(user.github_access_token or user.github_username),
        "dropbox": bool(user.dropbox_access_token or user.dropbox_account_id),
        "zotero": bool(meta.get("zotero_token")),
        "mendeley": bool(meta.get("mendeley_token")),
    }


def _user_360_cache_key(user_id: str, actor_role: str) -> str:
    return f"{USER_360_CACHE_PREFIX}:{user_id}:{actor_role}"


async def _read_user_360_cache(user_id: str, actor_role: str) -> dict[str, Any] | None:
    try:
        cached = await cache_manager.get(_user_360_cache_key(user_id, actor_role))
    except Exception:
        return None
    return cached if isinstance(cached, dict) else None


async def _write_user_360_cache(user_id: str, actor_role: str, payload: dict[str, Any]) -> None:
    # The cached document is always masked; revealed PII is overlaid live and
    # never enters Redis. A cache outage must not make the support view fail.
    try:
        await cache_manager.set(
            _user_360_cache_key(user_id, actor_role),
            payload,
            ttl=USER_360_CACHE_TTL,
        )
    except Exception:
        return


async def invalidate_user_360_cache(user_id: str) -> None:
    """Drop both role variants after a support action changes the account."""
    for role in ("admin", "support"):
        try:
            await cache_manager.delete(_user_360_cache_key(user_id, role))
        except Exception:
            continue


async def build_user_360(
    db: AsyncSession,
    *,
    user_id: str,
    actor_role: str,
    reveal: bool = False,
) -> dict[str, Any]:
    if not reveal:
        cached = await _read_user_360_cache(user_id, actor_role)
        if cached is not None:
            return cached

    user = await db.get(User, user_id)
    if user is None:
        raise KeyError("User not found")
    payload = await _compose_user_360(db, user=user, actor_role=actor_role)
    if reveal and actor_role == "admin":
        payload["user"]["email"] = user.email
        payload["user"]["name"] = user.name
        payload["user"]["pii_masked"] = False
    else:
        await _write_user_360_cache(user_id, actor_role, payload)
    return payload


async def _compose_user_360(
    db: AsyncSession,
    *,
    user: User,
    actor_role: str,
) -> dict[str, Any]:
    user_id = user.id
    now = datetime.now(timezone.utc)
    since_30d = now - timedelta(days=30)

    aggregate = (
        await db.execute(
            text(
                "SELECT "
                "(SELECT count(*) FROM resumes WHERE user_id = CAST(:uid AS uuid)), "
                "(SELECT count(*) FROM compilations WHERE user_id = CAST(:uid AS uuid)), "
                "(SELECT count(*) FROM compilations WHERE user_id = CAST(:uid AS uuid) AND status = 'completed'), "
                "(SELECT count(*) FROM compilations WHERE user_id = CAST(:uid AS uuid) AND status = 'failed'), "
                "(SELECT max(created_at) FROM compilations WHERE user_id = CAST(:uid AS uuid)), "
                "(SELECT count(*) FROM optimizations WHERE user_id = CAST(:uid AS uuid)), "
                "(SELECT max(created_at) FROM optimizations WHERE user_id = CAST(:uid AS uuid)), "
                "(SELECT count(*) FROM usage_analytics WHERE user_id = CAST(:uid AS uuid) AND created_at >= :since), "
                "(SELECT max(created_at) FROM usage_analytics WHERE user_id = CAST(:uid AS uuid)), "
                "EXISTS(SELECT 1 FROM usage_analytics WHERE user_id = CAST(:uid AS uuid) "
                "AND action IN ('export', 'pdf_export', 'docx_export', 'download')), "
                "EXISTS(SELECT 1 FROM subscriptions WHERE user_id = CAST(:uid AS uuid) "
                "AND status IN ('active', 'cancel_scheduled', 'past_due', 'on_hold', 'paused')), "
                "(SELECT count(*) FROM session WHERE CAST(\"userId\" AS uuid) = CAST(:uid AS uuid)), "
                "(SELECT count(*) FROM passkey WHERE CAST(\"userId\" AS uuid) = CAST(:uid AS uuid))"
            ),
            {"uid": user_id, "since": since_30d},
        )
    ).one()
    resume_count = int(aggregate[0] or 0)
    compilation_count = int(aggregate[1] or 0)
    successful_compilations = int(aggregate[2] or 0)
    failed_compilations = int(aggregate[3] or 0)
    last_compilation = aggregate[4]
    optimization_count = int(aggregate[5] or 0)
    last_optimization = aggregate[6]
    usage_30d = int(aggregate[7] or 0)
    last_activity = aggregate[8]
    has_export = bool(aggregate[9])
    has_paid = bool(aggregate[10])
    session_count = int(aggregate[11] or 0)
    passkey_count = int(aggregate[12] or 0)
    recent_resumes = (
        await db.execute(
            select(Resume.id, Resume.title, Resume.document_type, Resume.created_at, Resume.updated_at)
            .where(Resume.user_id == user_id)
            .order_by(Resume.updated_at.desc())
            .limit(8)
        )
    ).all()
    usage_rows = (
        await db.execute(
            select(UsageAnalytics.action, func.count(), func.max(UsageAnalytics.created_at))
            .where(UsageAnalytics.user_id == user_id)
            .group_by(UsageAnalytics.action)
            .order_by(func.count().desc())
            .limit(20)
        )
    ).all()
    recent_events = (
        await db.execute(
            select(UsageAnalytics.action, UsageAnalytics.resource_type, UsageAnalytics.created_at)
            .where(UsageAnalytics.user_id == user_id)
            .order_by(UsageAnalytics.created_at.desc())
            .limit(20)
        )
    ).all()

    subscriptions = (
        await db.execute(
            select(Subscription).where(Subscription.user_id == user_id).order_by(Subscription.created_at.desc()).limit(20)
        )
    ).scalars().all()
    payments = (
        await db.execute(
            select(Payment).where(Payment.user_id == user_id).order_by(Payment.created_at.desc()).limit(20)
        )
    ).scalars().all()
    payment_ids = [payment.id for payment in payments]
    refunds = (
        await db.execute(
            select(PaymentRefund).where(PaymentRefund.payment_id.in_(payment_ids)).order_by(PaymentRefund.created_at.desc()).limit(20)
        )
    ).scalars().all() if payment_ids else []
    refund_requests = (
        await db.execute(
            select(AdminRefundRequest).join(Payment, Payment.id == AdminRefundRequest.payment_id)
            .where(Payment.user_id == user_id)
            .order_by(AdminRefundRequest.requested_at.desc())
            .limit(20)
        )
    ).scalars().all()

    sessions = (
        await db.execute(
            text(
                'SELECT id, "createdAt", "expiresAt", "userAgent" FROM session '
                'WHERE "userId" = :uid ORDER BY "createdAt" DESC NULLS LAST LIMIT 20'
            ),
            {"uid": user_id},
        )
    ).all()
    byok_keys = (
        await db.execute(
            select(UserAPIKey.id, UserAPIKey.provider, UserAPIKey.key_name, UserAPIKey.is_active, UserAPIKey.created_at)
            .where(UserAPIKey.user_id == user_id)
            .order_by(UserAPIKey.created_at.desc())
            .limit(20)
        )
    ).all()
    developer_keys = (
        await db.execute(
            select(
                DeveloperAPIKey.id,
                DeveloperAPIKey.key_prefix,
                DeveloperAPIKey.name,
                DeveloperAPIKey.is_active,
                DeveloperAPIKey.request_count,
                DeveloperAPIKey.last_used_at,
            )
            .where(DeveloperAPIKey.user_id == user_id)
            .order_by(DeveloperAPIKey.created_at.desc())
            .limit(20)
        )
    ).all()
    admin_actions = []
    if actor_role == "admin":
        admin_actions = (
            await db.execute(
                select(models.AdminAuditLog)
                .where(
                    models.AdminAuditLog.target_type == "user",
                    models.AdminAuditLog.target_id == user_id,
                )
                .order_by(models.AdminAuditLog.created_at.desc())
                .limit(20)
            )
        ).scalars().all()

    tenant_rows = (
        await db.execute(
            select(TenantMember.tenant_id, TenantMember.role, TenantMember.joined_at)
            .where(TenantMember.user_id == user_id)
            .order_by(TenantMember.joined_at.desc())
            .limit(10)
        )
    ).all()
    referral_row = (
        await db.execute(
            select(ReferralAttribution.status, ReferralAttribution.referrer_user_id)
            .where(ReferralAttribution.referred_user_id == user_id)
            .limit(1)
        )
    ).one_or_none()
    referrals_made = int(
        (
            await db.execute(
                select(func.count()).select_from(ReferralAttribution).where(
                    ReferralAttribution.referrer_user_id == user_id
                )
            )
        ).scalar_one()
    )

    return {
        "user": {
            "id": user.id,
            "email": mask_email(user.email),
            "name": mask_name(user.name),
            "pii_masked": True,
            "role": user.role,
            "subscription_plan": user.subscription_plan,
            "subscription_status": user.subscription_status,
            "email_verified": bool(user.email_verified),
            "two_factor_enabled": bool(user.two_factor_enabled),
            "trial_used": bool(user.trial_used),
            "created_at": _iso(user.created_at),
            "updated_at": _iso(user.updated_at),
            "public_username": user.public_username,
            "portfolio_enabled": bool(user.portfolio_enabled),
            "default_tenant_id": user.default_tenant_id,
        },
        "activation": {
            "has_resume": resume_count > 0,
            "has_compile": compilation_count > 0,
            "has_optimization": optimization_count > 0,
            "has_export": has_export,
            "has_paid": has_paid,
            "last_activity_at": _iso(last_activity),
        },
        "usage": {
            "events_30d": usage_30d,
            "actions": [
                {"action": action, "count": int(count), "last_at": _iso(last)}
                for action, count, last in usage_rows
            ],
            "recent_events": [
                {"action": action, "resource_type": resource_type, "created_at": _iso(created_at)}
                for action, resource_type, created_at in recent_events
            ],
        },
        "production": {
            "resumes": resume_count,
            "recent_resumes": [
                {
                    "id": resume_id,
                    "title": title,
                    "document_type": document_type,
                    "created_at": _iso(created_at),
                    "updated_at": _iso(updated_at),
                }
                for resume_id, title, document_type, created_at, updated_at in recent_resumes
            ],
            "compilations": compilation_count,
            "successful_compilations": successful_compilations,
            "failed_compilations": failed_compilations,
            "last_compilation_at": _iso(last_compilation),
            "optimizations": optimization_count,
            "last_optimization_at": _iso(last_optimization),
        },
        "links": {
            "default_tenant_id": user.default_tenant_id,
            "tenants": [
                {
                    "tenant_id": tenant_id,
                    "role": role,
                    "joined_at": _iso(joined_at),
                }
                for tenant_id, role, joined_at in tenant_rows
            ],
            "referral": (
                {
                    "referred_by_user_id": referral_row[1],
                    "status": referral_row[0],
                }
                if referral_row is not None
                else None
            ),
            "referrals_made": referrals_made,
        },
        "integrations": _provider_presence(user),
        "billing": {
            "subscriptions": [
                {
                    "id": row.id,
                    "plan_id": row.plan_id,
                    "status": row.status,
                    "provider": row.provider,
                    "provider_subscription_id": row.provider_subscription_id,
                    "current_period_start": _iso(row.current_period_start),
                    "current_period_end": _iso(row.current_period_end),
                    "cancelled_at": _iso(row.cancelled_at),
                    "created_at": _iso(row.created_at),
                }
                for row in subscriptions
            ],
            "payments": [
                {
                    "id": row.id,
                    "provider_payment_id": row.provider_payment_id,
                    "amount": row.amount,
                    "currency": row.currency,
                    "status": row.status,
                    "payment_method": row.payment_method,
                    "created_at": _iso(row.created_at),
                }
                for row in payments
            ],
            "refunds": [
                {
                    "id": row.id,
                    "payment_id": row.payment_id,
                    "provider_refund_id": row.provider_refund_id,
                    "amount": row.amount,
                    "currency": row.currency,
                    "status": row.status,
                    "reason": row.reason,
                    "created_at": _iso(row.created_at),
                }
                for row in refunds
            ],
            "refund_requests": [
                {
                    "id": row.id,
                    "payment_id": row.payment_id,
                    "status": row.status,
                    "amount": row.amount,
                    "currency": row.currency,
                    "requested_at": _iso(row.requested_at),
                    "decided_at": _iso(row.decided_at),
                    "executed_at": _iso(row.executed_at),
                }
                for row in refund_requests
            ],
        },
        "security": {
            "sessions": [
                {
                    "id": row[0],
                    "created_at": _iso(row[1]),
                    "expires_at": _iso(row[2]),
                    "user_agent": (row[3] or "")[:200] or None,
                }
                for row in sessions
            ],
            "session_count": session_count,
            "passkey_count": passkey_count,
            "byok_keys": [
                {
                    "id": row.id,
                    "provider": row.provider,
                    "name": row.key_name,
                    "is_active": bool(row.is_active),
                    "created_at": _iso(row.created_at),
                }
                for row in byok_keys
            ],
            "developer_keys": [
                {
                    "id": row.id,
                    "prefix": row.key_prefix,
                    "name": row.name,
                    "is_active": bool(row.is_active),
                    "request_count": int(row.request_count or 0),
                    "last_used_at": _iso(row.last_used_at),
                }
                for row in developer_keys
            ],
        },
        "recent_admin_actions": [audit_row_summary(row) for row in admin_actions],
    }


async def reveal_user_pii(
    db: AsyncSession,
    *,
    user_id: str,
    actor: AdminActor,
    reason: str,
    request=None,
) -> dict[str, Any]:
    user = await db.get(User, user_id)
    if user is None:
        raise KeyError("User not found")
    cleaned_reason = " ".join((reason or "").split())[:1000]
    if not cleaned_reason:
        raise ValueError("A reason is required to reveal PII")
    await record_admin_audit(
        db,
        actor=actor,
        action="user.pii.reveal",
        target_type="user",
        target_id=user_id,
        reason=cleaned_reason,
        before={"pii_masked": True},
        after={"pii_masked": False, "fields": ["email", "name"]},
        request=request,
        commit=True,
    )
    return {"email": user.email, "name": user.name}


async def set_user_plan(
    db: AsyncSession,
    *,
    user_id: str,
    plan: str,
    status: str,
    actor: AdminActor,
    reason: str,
    request=None,
) -> dict[str, Any]:
    user = await db.get(User, user_id)
    if user is None:
        raise KeyError("User not found")
    normalized_plan = plan.strip().lower()
    supported_plans = {
        str(sku).strip().lower()
        for sku in settings.SUBSCRIPTION_PLANS
    }
    if normalized_plan not in supported_plans:
        raise ValueError("Unknown plan SKU")
    plan = normalized_plan
    cleaned_status = status.strip().lower()
    if cleaned_status not in {"active", "inactive", "trialing", "past_due", "cancelled", "comped"}:
        raise ValueError("Unsupported subscription status")
    cleaned_reason = " ".join((reason or "").split())[:1000]
    if not cleaned_reason:
        raise ValueError("A reason is required for a plan change")
    before = {"subscription_plan": user.subscription_plan, "subscription_status": user.subscription_status}
    user.subscription_plan = plan
    user.subscription_status = cleaned_status
    await record_admin_audit(
        db,
        actor=actor,
        action="user.plan.change",
        target_type="user",
        target_id=user_id,
        reason=cleaned_reason,
        before=before,
        after={"subscription_plan": user.subscription_plan, "subscription_status": user.subscription_status},
        request=request,
    )
    await db.commit()
    await db.refresh(user)
    await invalidate_user_360_cache(user_id)
    return {
        "subscription_plan": user.subscription_plan,
        "subscription_status": user.subscription_status,
    }


async def reset_user_trial(
    db: AsyncSession,
    *,
    user_id: str,
    actor: AdminActor,
    reason: str,
    request=None,
) -> dict[str, Any]:
    user = await db.get(User, user_id)
    if user is None:
        raise KeyError("User not found")
    cleaned_reason = " ".join((reason or "").split())[:1000]
    if not cleaned_reason:
        raise ValueError("A reason is required to reset a trial")
    fingerprints = [
        row[0]
        for row in (
            await db.execute(
                select(UsageAnalytics.device_fingerprint)
                .where(UsageAnalytics.user_id == user_id, UsageAnalytics.device_fingerprint.is_not(None))
                .distinct()
            )
        ).all()
        if row[0]
    ]
    before = {"trial_used": bool(user.trial_used), "device_trials": 0}
    reset_count = 0
    if fingerprints:
        result = await db.execute(
            update(models.DeviceTrial)
            .where(models.DeviceTrial.device_fingerprint.in_(fingerprints))
            .values(usage_count=0, blocked=False)
        )
        reset_count = int(result.rowcount or 0)
    user.trial_used = False
    before["device_trials"] = reset_count
    await record_admin_audit(
        db,
        actor=actor,
        action="user.trial.reset",
        target_type="user",
        target_id=user_id,
        reason=cleaned_reason,
        before=before,
        after={"trial_used": False, "device_trials": reset_count},
        request=request,
    )
    await db.commit()
    await invalidate_user_360_cache(user_id)
    return {"trial_used": False, "device_trials_reset": reset_count}


async def reset_user_quota(
    db: AsyncSession,
    *,
    user_id: str,
    dimension: str | None,
    actor: AdminActor,
    reason: str,
    request=None,
) -> dict[str, Any]:
    user = await db.get(User, user_id)
    if user is None:
        raise KeyError("User not found")
    cleaned_reason = " ".join((reason or "").split())[:1000]
    if not cleaned_reason:
        raise ValueError("A reason is required to reset quota")
    dimensions = list(QUOTA_DIMENSIONS) if dimension is None else [dimension]
    if any(item not in QUOTA_DIMENSIONS for item in dimensions):
        raise ValueError("Unknown quota dimension")
    from .entitlement_service import _current_period

    keys: list[str] = []
    for item in dimensions:
        window = get_plan_quota_window(user.subscription_plan, item)
        period = _current_period(window)
        keys.append(f"latexy:quota:{item}:{user_id}:{period}")
    from ..core.redis import get_redis_cache_client

    # Persist the intent before the external mutation. If Redis succeeds and
    # the completion audit fails, the immutable started row still proves who
    # reset what and why; a retry cannot erase that history.
    intent = await record_admin_audit(
        db,
        actor=actor,
        action="user.quota.reset.started",
        target_type="user",
        target_id=user_id,
        reason=cleaned_reason,
        before={"dimensions": dimensions, "counter_keys": len(keys)},
        request=request,
        commit=True,
    )
    try:
        redis = await get_redis_cache_client()
        deleted = int(await redis.delete(*keys)) if keys else 0
    except Exception:
        await record_admin_audit(
            db,
            actor=actor,
            action="user.quota.reset.failed",
            target_type="user",
            target_id=user_id,
            reason=cleaned_reason,
            before={"dimensions": dimensions, "counter_keys": len(keys)},
            after={"deleted_keys": 0},
            metadata={"operation_id": intent.id},
            request=request,
            commit=True,
        )
        raise
    await record_admin_audit(
        db,
        actor=actor,
        action="user.quota.reset.completed",
        target_type="user",
        target_id=user_id,
        reason=cleaned_reason,
        before={"dimensions": dimensions, "counter_keys": len(keys)},
        after={"deleted_keys": deleted},
        metadata={"operation_id": intent.id},
        request=request,
        commit=True,
    )
    await invalidate_user_360_cache(user_id)
    return {"dimensions": dimensions, "deleted_keys": deleted}


async def revoke_user_sessions(
    db: AsyncSession,
    *,
    user_id: str,
    actor: AdminActor,
    reason: str,
    request=None,
) -> dict[str, Any]:
    user = await db.get(User, user_id)
    if user is None:
        raise KeyError("User not found")
    cleaned_reason = " ".join((reason or "").split())[:1000]
    if not cleaned_reason:
        raise ValueError("A reason is required to revoke sessions")
    result = await db.execute(text('DELETE FROM session WHERE "userId" = :uid'), {"uid": user_id})
    count = int(result.rowcount or 0)
    await record_admin_audit(
        db,
        actor=actor,
        action="user.sessions.revoke",
        target_type="user",
        target_id=user_id,
        reason=cleaned_reason,
        before={"active_sessions": count},
        after={"active_sessions": 0},
        request=request,
    )
    await db.commit()
    await invalidate_user_360_cache(user_id)
    return {"revoked_sessions": count}


async def revoke_user_passkeys(
    db: AsyncSession,
    *,
    user_id: str,
    actor: AdminActor,
    reason: str,
    request=None,
) -> dict[str, Any]:
    user = await db.get(User, user_id)
    if user is None:
        raise KeyError("User not found")
    cleaned_reason = " ".join((reason or "").split())[:1000]
    if not cleaned_reason:
        raise ValueError("A reason is required to revoke passkeys")
    result = await db.execute(text('DELETE FROM passkey WHERE "userId" = :uid'), {"uid": user_id})
    count = int(result.rowcount or 0)
    await record_admin_audit(
        db,
        actor=actor,
        action="user.passkeys.revoke",
        target_type="user",
        target_id=user_id,
        reason=cleaned_reason,
        before={"passkeys": count},
        after={"passkeys": 0},
        request=request,
    )
    await db.commit()
    await invalidate_user_360_cache(user_id)
    return {"revoked_passkeys": count}


async def revoke_user_api_keys(
    db: AsyncSession,
    *,
    user_id: str,
    scope: str,
    actor: AdminActor,
    reason: str,
    request=None,
) -> dict[str, Any]:
    user = await db.get(User, user_id)
    if user is None:
        raise KeyError("User not found")
    if scope not in {"byok", "developer", "all"}:
        raise ValueError("Key scope must be byok, developer, or all")
    cleaned_reason = " ".join((reason or "").split())[:1000]
    if not cleaned_reason:
        raise ValueError("A reason is required to revoke API keys")
    byok_count = developer_count = 0
    if scope in {"byok", "all"}:
        result = await db.execute(
            update(UserAPIKey).where(UserAPIKey.user_id == user_id, UserAPIKey.is_active.is_(True)).values(is_active=False)
        )
        byok_count = int(result.rowcount or 0)
    if scope in {"developer", "all"}:
        result = await db.execute(
            update(DeveloperAPIKey)
            .where(DeveloperAPIKey.user_id == user_id, DeveloperAPIKey.is_active.is_(True))
            .values(is_active=False)
        )
        developer_count = int(result.rowcount or 0)
    await record_admin_audit(
        db,
        actor=actor,
        action="user.api_keys.revoke",
        target_type="user",
        target_id=user_id,
        reason=cleaned_reason,
        before={"scope": scope, "byok_active": byok_count, "developer_active": developer_count},
        after={"scope": scope, "byok_active": 0, "developer_active": 0},
        request=request,
    )
    await db.commit()
    await invalidate_user_360_cache(user_id)
    return {"revoked_byok_keys": byok_count, "revoked_developer_keys": developer_count}
