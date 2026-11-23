"""User 360 composition and audited support actions.

This module deliberately composes existing tables. It never reads or returns
resume LaTeX, structured document content, prompts, job descriptions, or API-key
values. Support can see a masked account view; only an admin can reveal PII.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from ..core.config import QUOTA_DIMENSIONS, settings
from ..core.feature_registry import FEATURE_REGISTRY, get_feature
from ..core.logging import get_logger
from ..core.redis import cache_manager, get_redis_client
from ..database import models
from .admin_audit_service import AdminActor, audit_row_summary, record_admin_audit
from .entitlement_service import (
    ENTITLEMENT_OVERRIDES_KEY,
    entitlement_overrides_from_metadata,
    entitlement_service,
    invalidate_entitlement_cache,
)

logger = get_logger(__name__)

USER_360_CACHE_TTL = 60
USER_360_CACHE_PREFIX = "admin:user360:v2"

# A reveal is a single field, at most five times a minute for one operator,
# target, and field. Redis is only a counter; a Redis outage fails open so a
# cache incident cannot block a legitimate support escalation.
PII_REVEAL_LIMIT = 5
PII_REVEAL_WINDOW_SECONDS = 60
PII_FIELDS = frozenset({"email", "name"})
_PII_REVEAL_LUA = """
local n = redis.call('INCR', KEYS[1])
if n == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {n, ttl}
"""


class RevealRateLimited(RuntimeError):
    """Raised when one admin+target+field exceeds the reveal budget."""

    def __init__(self, retry_after: int):
        self.retry_after = max(1, int(retry_after))
        super().__init__("PII reveal rate limit exceeded")


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


TRIAL_METADATA_KEY = "trial"


def _metadata_dict(user: User) -> dict[str, Any]:
    return dict(user.user_metadata) if isinstance(user.user_metadata, dict) else {}


def _override_container(metadata: dict[str, Any]) -> dict[str, Any]:
    raw = metadata.get(ENTITLEMENT_OVERRIDES_KEY)
    return dict(raw) if isinstance(raw, dict) else {}


def _override_enabled(metadata: dict[str, Any], feature_key: str) -> bool | None:
    return entitlement_overrides_from_metadata(metadata).get(feature_key)


def _parse_trial_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _trial_state(user: User) -> dict[str, Any]:
    metadata = _metadata_dict(user)
    trial = metadata.get(TRIAL_METADATA_KEY)
    trial = trial if isinstance(trial, dict) else {}
    return {
        "trial_used": bool(user.trial_used),
        "eligible": not bool(user.trial_used),
        "extended_until": trial.get("extended_until"),
        "updated_at": trial.get("updated_at"),
        "updated_by": trial.get("updated_by"),
        "source": "support_override" if trial else "account",
    }


def _ensure_not_self_target(actor: AdminActor, user_id: str) -> None:
    """Privilege/quota-changing support actions cannot target the actor."""
    if actor.user_id == user_id:
        raise PermissionError("Admin actions cannot target your own account")


async def _locked_user(db: AsyncSession, user_id: str) -> User:
    user = (
        await db.execute(select(User).where(User.id == user_id).with_for_update())
    ).scalar_one_or_none()
    if user is None:
        raise KeyError("User not found")
    return user


async def _effective_feature_state(user_id: str, feature_key: str) -> dict[str, Any]:
    snapshot = await entitlement_service.effective_snapshot(user_id)
    return {
        "feature_key": feature_key,
        "effective": bool(snapshot["features"].get(feature_key)),
        "available": bool(snapshot.get("available")),
        "features": snapshot["features"],
    }


async def _reset_device_trials(db: AsyncSession, user_id: str) -> int:
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
    if not fingerprints:
        return 0
    result = await db.execute(
        update(models.DeviceTrial)
        .where(models.DeviceTrial.device_fingerprint.in_(fingerprints))
        .values(usage_count=0, blocked=False)
    )
    return int(result.rowcount or 0)


async def build_user_360(
    db: AsyncSession,
    *,
    user_id: str,
    actor_role: str,
) -> dict[str, Any]:
    """Compose the always-masked 360 view.

    Revealed PII is never overlaid here and never cached; the UI calls the
    single-field reveal endpoint and holds the value client-side.
    """
    cached = await _read_user_360_cache(user_id, actor_role)
    if cached is not None:
        return cached

    user = await db.get(User, user_id)
    if user is None:
        raise KeyError("User not found")
    payload = await _compose_user_360(db, user=user, actor_role=actor_role)
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
    passkeys = (
        await db.execute(
            text(
                'SELECT id, name, "deviceType", "backedUp", "createdAt" FROM passkey '
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

    # Entitlement/quota state is read through the same authority product routes
    # use. The override map is the support-plane delta, not a second policy
    # snapshot; global and role restrictions are already folded into effective.
    override_map = entitlement_overrides_from_metadata(user.user_metadata)
    effective_snapshot = await entitlement_service.effective_snapshot(user_id)
    quota_snapshot = await entitlement_service.quota_snapshot(user_id, user.subscription_plan)
    gateable_features = [
        {
            "key": feature.key,
            "label": feature.label,
            "category": feature.category,
            "parent_key": feature.parent_key,
        }
        for feature in FEATURE_REGISTRY
        if feature.gateable
    ]
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
            # Identification and metadata only. Public keys, credential IDs,
            # counters, and session tokens never enter this projection.
            "passkeys": [
                {
                    "id": row[0],
                    "name": (row[1] or "")[:255] or None,
                    "device_type": row[2],
                    "backed_up": bool(row[3]),
                    "created_at": _iso(row[4]),
                }
                for row in passkeys
            ],
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
        "entitlements": {
            "effective": {
                key: bool(value)
                for key, value in effective_snapshot["features"].items()
                if get_feature(key) is not None and get_feature(key).gateable
            },
            "overrides": {
                key: {"enabled": enabled}
                for key, enabled in override_map.items()
                if get_feature(key) is not None and get_feature(key).gateable
            },
            "available_features": gateable_features,
            "available": bool(effective_snapshot.get("available")),
        },
        "quota": quota_snapshot,
        "trial": _trial_state(user),
        "recent_admin_actions": [audit_row_summary(row) for row in admin_actions],
    }


async def _consume_reveal_budget(*, actor_user_id: str, user_id: str, field: str) -> None:
    """Fixed-window 5/min limiter scoped to admin+target+field.

    Only a Redis outage fails open. A malformed response from a healthy Redis is
    treated as a limiter failure and also fails open, because it cannot be
    distinguished from an outage; no other error path is caught here.
    """
    key = f"latexy:admin:pii-reveal:{actor_user_id}:{user_id}:{field}"
    try:
        redis = await get_redis_client()
        result = await redis.eval(_PII_REVEAL_LUA, 1, key, PII_REVEAL_WINDOW_SECONDS)
        count, ttl = int(result[0]), int(result[1])
    except Exception as exc:  # Redis outage: fail open, log without PII.
        logger.warning(
            "PII reveal rate limiter unavailable; failing open",
            extra={"error_type": type(exc).__name__},
        )
        return
    if count > PII_REVEAL_LIMIT:
        raise RevealRateLimited(ttl or PII_REVEAL_WINDOW_SECONDS)


async def reveal_user_pii(
    db: AsyncSession,
    *,
    user_id: str,
    field: str,
    actor: AdminActor,
    reason: str,
    request=None,
) -> dict[str, Any]:
    """Reveal exactly one PII field and write its immutable audit row.

    The response and the audit payload never contain the other field, and the
    revealed value itself is never written to the audit log or application log.
    """
    normalized_field = (field or "").strip().lower()
    if normalized_field not in PII_FIELDS:
        raise ValueError("field must be email or name")
    cleaned_reason = " ".join((reason or "").split())[:1000]
    if len(cleaned_reason) < 3:
        raise ValueError("A reason of at least 3 characters is required to reveal PII")

    user = await db.get(User, user_id)
    if user is None:
        raise KeyError("User not found")

    await _consume_reveal_budget(
        actor_user_id=actor.user_id,
        user_id=user_id,
        field=normalized_field,
    )
    await record_admin_audit(
        db,
        actor=actor,
        action="user.pii.reveal",
        target_type="user",
        target_id=user_id,
        reason=cleaned_reason,
        before={"pii_masked": True, "field": normalized_field},
        after={"pii_masked": False, "field": normalized_field},
        metadata={"field": normalized_field},
        request=request,
        commit=True,
    )
    return {"field": normalized_field, "value": getattr(user, normalized_field)}


async def _credential_already_revoked(
    db: AsyncSession,
    *,
    user_id: str,
    action: str,
    kind: str,
    item_id: str,
) -> bool:
    """Idempotency probe: a prior revoke audit row proves this item belonged here."""
    stmt = (
        select(models.AdminAuditLog.id)
        .where(
            models.AdminAuditLog.target_type == "user",
            models.AdminAuditLog.target_id == user_id,
            models.AdminAuditLog.action == action,
            models.AdminAuditLog.event_metadata["kind"].astext == kind,
            models.AdminAuditLog.event_metadata["item_id"].astext == item_id,
        )
        .limit(1)
    )
    return (await db.execute(stmt)).first() is not None


async def _revoke_audited_credential(
    db: AsyncSession,
    *,
    user_id: str,
    credential_id: str,
    kind: str,
    action: str,
    actor: AdminActor,
    reason: str,
    request=None,
) -> dict[str, Any]:
    """Shared audit/idempotency envelope for an individual credential revoke."""
    await record_admin_audit(
        db,
        actor=actor,
        action=action,
        target_type="user",
        target_id=user_id,
        reason=reason,
        before={"active": True, "kind": kind},
        after={"active": False, "kind": kind},
        metadata={"kind": kind, "item_id": credential_id},
        request=request,
    )
    await db.commit()
    await invalidate_user_360_cache(user_id)
    return {"kind": kind, "item_id": credential_id, "revoked": True, "already_revoked": False}


def _clean_revoke_reason(reason: str) -> str:
    cleaned_reason = " ".join((reason or "").split())[:1000]
    if len(cleaned_reason) < 3:
        raise ValueError("A reason of at least 3 characters is required")
    return cleaned_reason


def _normalize_uuid(value: str) -> str | None:
    """Return a canonical UUID string or None without touching the database."""
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return None


async def revoke_user_session(
    db: AsyncSession,
    *,
    user_id: str,
    session_id: str,
    actor: AdminActor,
    reason: str,
    request=None,
) -> dict[str, Any]:
    """Revoke one session for this user; a cross-user id is indistinguishable from missing."""
    cleaned_reason = _clean_revoke_reason(reason)
    if await db.get(User, user_id) is None:
        raise KeyError("User not found")
    owner = (
        await db.execute(
            text('SELECT "userId" FROM session WHERE id = :sid'),
            {"sid": session_id},
        )
    ).scalar_one_or_none()
    action = "user.session.revoke"
    kind = "session"
    if owner is None or str(owner) != user_id:
        if owner is None and await _credential_already_revoked(
            db, user_id=user_id, action=action, kind=kind, item_id=session_id
        ):
            return {"kind": kind, "item_id": session_id, "revoked": False, "already_revoked": True}
        raise KeyError("Session not found")
    result = await db.execute(
        text('DELETE FROM session WHERE id = :sid AND "userId" = :uid'),
        {"sid": session_id, "uid": user_id},
    )
    if int(result.rowcount or 0) == 0:
        return {"kind": kind, "item_id": session_id, "revoked": False, "already_revoked": True}
    return await _revoke_audited_credential(
        db,
        user_id=user_id,
        credential_id=session_id,
        kind=kind,
        action=action,
        actor=actor,
        reason=cleaned_reason,
        request=request,
    )


async def revoke_user_passkey(
    db: AsyncSession,
    *,
    user_id: str,
    passkey_id: str,
    actor: AdminActor,
    reason: str,
    request=None,
) -> dict[str, Any]:
    """Revoke one passkey for this user."""
    cleaned_reason = _clean_revoke_reason(reason)
    if await db.get(User, user_id) is None:
        raise KeyError("User not found")
    owner = (
        await db.execute(
            text('SELECT "userId" FROM passkey WHERE id = :pid'),
            {"pid": passkey_id},
        )
    ).scalar_one_or_none()
    action = "user.passkey.revoke"
    kind = "passkey"
    if owner is None or str(owner) != user_id:
        if owner is None and await _credential_already_revoked(
            db, user_id=user_id, action=action, kind=kind, item_id=passkey_id
        ):
            return {"kind": kind, "item_id": passkey_id, "revoked": False, "already_revoked": True}
        raise KeyError("Passkey not found")
    result = await db.execute(
        text('DELETE FROM passkey WHERE id = :pid AND "userId" = :uid'),
        {"pid": passkey_id, "uid": user_id},
    )
    if int(result.rowcount or 0) == 0:
        return {"kind": kind, "item_id": passkey_id, "revoked": False, "already_revoked": True}
    return await _revoke_audited_credential(
        db,
        user_id=user_id,
        credential_id=passkey_id,
        kind=kind,
        action=action,
        actor=actor,
        reason=cleaned_reason,
        request=request,
    )


async def revoke_user_byok_key(
    db: AsyncSession,
    *,
    user_id: str,
    key_id: str,
    actor: AdminActor,
    reason: str,
    request=None,
) -> dict[str, Any]:
    """Deactivate one BYOK key for this user, idempotently."""
    cleaned_reason = _clean_revoke_reason(reason)
    if await db.get(User, user_id) is None:
        raise KeyError("User not found")
    normalized_key_id = _normalize_uuid(key_id)
    key: UserAPIKey | None = None
    if normalized_key_id is not None:
        key = await db.get(UserAPIKey, normalized_key_id)
    action = "user.byok_key.revoke"
    kind = "byok"
    if key is None or key.user_id != user_id:
        if key is None and await _credential_already_revoked(
            db, user_id=user_id, action=action, kind=kind, item_id=normalized_key_id or key_id
        ):
            return {"kind": kind, "item_id": key_id, "revoked": False, "already_revoked": True}
        raise KeyError("API key not found")
    if not key.is_active:
        return {"kind": kind, "item_id": key_id, "revoked": False, "already_revoked": True}
    key.is_active = False
    return await _revoke_audited_credential(
        db,
        user_id=user_id,
        credential_id=normalized_key_id or key_id,
        kind=kind,
        action=action,
        actor=actor,
        reason=cleaned_reason,
        request=request,
    )


async def revoke_user_developer_key(
    db: AsyncSession,
    *,
    user_id: str,
    key_id: str,
    actor: AdminActor,
    reason: str,
    request=None,
) -> dict[str, Any]:
    """Deactivate one developer API key for this user, idempotently."""
    cleaned_reason = _clean_revoke_reason(reason)
    if await db.get(User, user_id) is None:
        raise KeyError("User not found")
    normalized_key_id = _normalize_uuid(key_id)
    key: DeveloperAPIKey | None = None
    if normalized_key_id is not None:
        key = await db.get(DeveloperAPIKey, normalized_key_id)
    action = "user.developer_key.revoke"
    kind = "developer"
    if key is None or key.user_id != user_id:
        if key is None and await _credential_already_revoked(
            db, user_id=user_id, action=action, kind=kind, item_id=normalized_key_id or key_id
        ):
            return {"kind": kind, "item_id": key_id, "revoked": False, "already_revoked": True}
        raise KeyError("API key not found")
    if not key.is_active:
        return {"kind": kind, "item_id": key_id, "revoked": False, "already_revoked": True}
    key.is_active = False
    return await _revoke_audited_credential(
        db,
        user_id=user_id,
        credential_id=normalized_key_id or key_id,
        kind=kind,
        action=action,
        actor=actor,
        reason=cleaned_reason,
        request=request,
    )


async def set_user_feature_override(
    db: AsyncSession,
    *,
    user_id: str,
    feature_key: str,
    enabled: bool,
    actor: AdminActor,
    reason: str,
    request=None,
) -> dict[str, Any]:
    """Idempotently grant/revoke one gateable feature in row-locked metadata."""
    feature = get_feature(feature_key)
    if feature is None or not feature.gateable:
        raise ValueError("Unknown or non-gateable feature key")
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be a boolean")
    cleaned_reason = " ".join((reason or "").split())[:1000]
    if not cleaned_reason:
        raise ValueError("A reason is required for a feature override")
    _ensure_not_self_target(actor, user_id)

    user = await _locked_user(db, user_id)
    plan = user.subscription_plan
    metadata = _metadata_dict(user)
    container = _override_container(metadata)
    current = _override_enabled(metadata, feature_key)
    if current is enabled:
        # The row lock still serializes concurrent identical requests; a no-op
        # must not create a duplicate audit row or rewrite metadata.
        await db.rollback()
        effective = await _effective_feature_state(user_id, feature_key)
        quota = await entitlement_service.quota_snapshot(user_id, plan)
        return {
            "feature_key": feature_key,
            "changed": False,
            "override": enabled,
            "before": {"override": current},
            "after": {"override": current},
            **effective,
            "entitlement": {
                "features": effective["features"],
                "available": effective["available"],
            },
            "quota": quota,
        }

    now = datetime.now(timezone.utc)
    container[feature_key] = {
        "enabled": enabled,
        "updated_at": now.isoformat(),
        "updated_by": actor.user_id,
        "reason": cleaned_reason,
    }
    metadata[ENTITLEMENT_OVERRIDES_KEY] = container
    user.user_metadata = metadata
    flag_modified(user, "user_metadata")
    await record_admin_audit(
        db,
        actor=actor,
        action="user.feature.grant" if enabled else "user.feature.revoke",
        target_type="user",
        target_id=user_id,
        reason=cleaned_reason,
        before={"override": current},
        after={"override": enabled},
        metadata={"feature_key": feature_key},
        request=request,
    )
    await db.commit()
    await db.refresh(user)
    await invalidate_user_360_cache(user_id)
    await invalidate_entitlement_cache()
    effective = await _effective_feature_state(user_id, feature_key)
    quota = await entitlement_service.quota_snapshot(user_id, plan)
    return {
        "feature_key": feature_key,
        "changed": True,
        "override": enabled,
        "before": {"override": current},
        "after": {"override": enabled},
        **effective,
        "entitlement": {
            "features": effective["features"],
            "available": effective["available"],
        },
        "quota": quota,
    }


async def extend_user_trial(
    db: AsyncSession,
    *,
    user_id: str,
    days: int,
    actor: AdminActor,
    reason: str,
    request=None,
) -> dict[str, Any]:
    """Extend support-granted trial eligibility without a new table."""
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 365:
        raise ValueError("Trial extension must be between 1 and 365 days")
    cleaned_reason = " ".join((reason or "").split())[:1000]
    if not cleaned_reason:
        raise ValueError("A reason is required to extend a trial")
    _ensure_not_self_target(actor, user_id)

    user = await _locked_user(db, user_id)
    metadata = _metadata_dict(user)
    trial = dict(metadata.get(TRIAL_METADATA_KEY)) if isinstance(metadata.get(TRIAL_METADATA_KEY), dict) else {}
    now = datetime.now(timezone.utc)
    existing_until = _parse_trial_datetime(trial.get("extended_until"))
    base = max(now, existing_until) if existing_until else now
    extended_until = base + timedelta(days=days)
    before = {
        "trial_used": bool(user.trial_used),
        "extended_until": trial.get("extended_until"),
    }
    device_trials_reset = await _reset_device_trials(db, user_id)
    user.trial_used = False
    trial.update(
        {
            "eligible": True,
            "extended_until": extended_until.isoformat(),
            "updated_at": now.isoformat(),
            "updated_by": actor.user_id,
            "reason": cleaned_reason,
            "days": days,
        }
    )
    metadata[TRIAL_METADATA_KEY] = trial
    user.user_metadata = metadata
    flag_modified(user, "user_metadata")
    await record_admin_audit(
        db,
        actor=actor,
        action="user.trial.extend",
        target_type="user",
        target_id=user_id,
        reason=cleaned_reason,
        before=before,
        after={
            "trial_used": False,
            "extended_until": extended_until.isoformat(),
            "device_trials_reset": device_trials_reset,
        },
        request=request,
    )
    await db.commit()
    await db.refresh(user)
    await invalidate_user_360_cache(user_id)
    return {
        "changed": True,
        "days": days,
        "device_trials_reset": device_trials_reset,
        "before": before,
        "after": _trial_state(user),
        "trial": _trial_state(user),
    }


async def set_user_trial_eligibility(
    db: AsyncSession,
    *,
    user_id: str,
    eligible: bool,
    actor: AdminActor,
    reason: str,
    request=None,
) -> dict[str, Any]:
    """Set trial eligibility explicitly; repeated identical calls are no-ops."""
    if not isinstance(eligible, bool):
        raise ValueError("eligible must be a boolean")
    cleaned_reason = " ".join((reason or "").split())[:1000]
    if not cleaned_reason:
        raise ValueError("A reason is required to change trial eligibility")
    _ensure_not_self_target(actor, user_id)

    user = await _locked_user(db, user_id)
    metadata = _metadata_dict(user)
    trial = dict(metadata.get(TRIAL_METADATA_KEY)) if isinstance(metadata.get(TRIAL_METADATA_KEY), dict) else {}
    currently_eligible = not bool(user.trial_used)
    if currently_eligible is eligible and bool(trial.get("eligible", currently_eligible)) is eligible:
        unchanged = _trial_state(user)
        await db.rollback()
        return {
            "changed": False,
            "before": unchanged,
            "after": unchanged,
            "trial": unchanged,
        }

    before = _trial_state(user)
    now = datetime.now(timezone.utc)
    device_trials_reset = 0
    if eligible:
        device_trials_reset = await _reset_device_trials(db, user_id)
    user.trial_used = not eligible
    trial.update(
        {
            "eligible": eligible,
            "updated_at": now.isoformat(),
            "updated_by": actor.user_id,
            "reason": cleaned_reason,
        }
    )
    if not eligible:
        trial["extended_until"] = None
    metadata[TRIAL_METADATA_KEY] = trial
    user.user_metadata = metadata
    flag_modified(user, "user_metadata")
    await record_admin_audit(
        db,
        actor=actor,
        action="user.trial.eligibility",
        target_type="user",
        target_id=user_id,
        reason=cleaned_reason,
        before=before,
        after={
            "eligible": eligible,
            "trial_used": not eligible,
            "device_trials_reset": device_trials_reset,
        },
        request=request,
    )
    await db.commit()
    await db.refresh(user)
    await invalidate_user_360_cache(user_id)
    return {
        "changed": True,
        "device_trials_reset": device_trials_reset,
        "before": before,
        "after": _trial_state(user),
        "trial": _trial_state(user),
    }


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
    _ensure_not_self_target(actor, user_id)
    cleaned_reason = " ".join((reason or "").split())[:1000]
    if not cleaned_reason:
        raise ValueError("A reason is required to reset quota")
    dimensions = list(QUOTA_DIMENSIONS) if dimension is None else [dimension]
    if any(item not in QUOTA_DIMENSIONS for item in dimensions):
        raise ValueError("Unknown quota dimension")

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
        before={"dimensions": dimensions},
        request=request,
        commit=True,
    )
    try:
        reset = await entitlement_service.reset_quota(
            user_id=user_id,
            dimensions=dimensions,
            plan=user.subscription_plan,
        )
    except Exception:
        await record_admin_audit(
            db,
            actor=actor,
            action="user.quota.reset.failed",
            target_type="user",
            target_id=user_id,
            reason=cleaned_reason,
            before={"dimensions": dimensions},
            after={"deleted_keys": 0},
            metadata={"operation_id": intent.id},
            request=request,
            commit=True,
        )
        raise
    quota = await entitlement_service.quota_snapshot(user_id, user.subscription_plan)
    await record_admin_audit(
        db,
        actor=actor,
        action="user.quota.reset.completed",
        target_type="user",
        target_id=user_id,
        reason=cleaned_reason,
        before={"dimensions": dimensions},
        after={
            "deleted_keys": reset["deleted_keys"],
            "counters": reset["results"],
        },
        metadata={"operation_id": intent.id},
        request=request,
        commit=True,
    )
    await invalidate_user_360_cache(user_id)
    return {
        "dimensions": dimensions,
        "deleted_keys": reset["deleted_keys"],
        "results": reset["results"],
        "quota": quota,
    }


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
