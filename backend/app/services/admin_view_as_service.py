"""Audited read-only view-as snapshots bound to two-person approvals.

This deliberately does not mint or reuse a target-user session. A second admin
approves one explicit target plus the fixed ``view_as`` mode, the starting admin
exchanges that approval once for a short-lived opaque token, and the token only
unlocks a server-composed read-only snapshot. The snapshot carries dashboard
counts, resume titles/timestamps, plan/usage state and the support billing
timeline. It never carries LaTeX, structured document content, prompts, raw
email/name, passwords, sessions, tokens, user agents or provider payloads.

The write guard in ``app.middleware.view_as_guard`` rejects every non-read
request that presents the preview token, so the preview cannot become an
ambient impersonation credential.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.feature_registry import get_feature
from ..database import models
from .admin_approval_service import (
    approval_summary,
    begin_execution,
    complete_execution,
    create_request,
    get_request,
    normalize_payload,
    require_approved,
)
from .admin_audit_service import AdminActor, record_admin_audit
from .admin_user_service import mask_email, mask_name
from .admin_user_timeline_service import (
    DEFAULT_TIMELINE_LIMIT,
    MAX_TIMELINE_LIMIT,
    build_subscription_timeline,
)
from .entitlement_service import entitlement_service

VIEW_AS_SCOPE = "read_only"
VIEW_AS_MAX_MINUTES = 15
VIEW_AS_MIN_MINUTES = 5
VIEW_AS_DEFAULT_MINUTES = 15
VIEW_AS_MAX_REASON = 1000
VIEW_AS_MAX_RESUMES = 20
VIEW_AS_MAX_SUBSCRIPTIONS = 20
VIEW_AS_MAX_USAGE_ACTIONS = 20
VIEW_AS_MAX_USAGE_EVENTS = 20
VIEW_AS_BANNER = "READ-ONLY view-as snapshot. No writes, credentials or document content."


class ViewAsError(Exception):
    status_code = 409
    code = "view_as_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details


class ViewAsNotFound(ViewAsError):
    status_code = 404
    code = "view_as_not_found"


class ViewAsValidationError(ViewAsError):
    status_code = 422
    code = "view_as_invalid"


class ViewAsForbidden(ViewAsError):
    status_code = 403
    code = "view_as_forbidden"


class ViewAsExpired(ViewAsError):
    status_code = 403
    code = "view_as_expired"


class ViewAsConflict(ViewAsError):
    status_code = 409
    code = "view_as_conflict"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _iso(value: datetime | None) -> str | None:
    return _as_aware(value).isoformat() if value else None


def _clean_reason(value: str | None, *, field: str = "reason") -> str:
    cleaned = " ".join((value or "").split())[:VIEW_AS_MAX_REASON]
    if len(cleaned) < 3:
        raise ViewAsValidationError(f"A {field} of at least 3 characters is required")
    return cleaned


def _canonical_user_id(value: Any) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise ViewAsValidationError("target_user_id must be a UUID") from None


def _session_minutes(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ViewAsValidationError("expires_in_minutes must be an integer")
    if value < VIEW_AS_MIN_MINUTES or value > VIEW_AS_MAX_MINUTES:
        raise ViewAsValidationError(
            f"expires_in_minutes must be between {VIEW_AS_MIN_MINUTES} and {VIEW_AS_MAX_MINUTES}"
        )
    return value


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def target_summary(user: models.User) -> dict[str, Any]:
    """Explicit target identity with masked PII; never a raw email or name."""
    return {
        "id": user.id,
        "email": mask_email(user.email),
        "name": mask_name(user.name),
        "pii_masked": True,
        "role": user.role,
        "subscription_plan": user.subscription_plan,
        "subscription_status": user.subscription_status,
        "trial_used": bool(user.trial_used),
        "created_at": _iso(user.created_at),
    }


def session_status(row: models.AdminViewAsSession, *, now: datetime | None = None) -> str:
    if row.ended_at is not None:
        return "ended"
    if _as_aware(row.expires_at) <= (now or _now()):
        return "expired"
    return "active"


def session_summary(
    row: models.AdminViewAsSession,
    user: models.User,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or _now()
    return {
        "id": row.id,
        "approval_id": row.approval_id,
        "target": target_summary(user),
        "scope": VIEW_AS_SCOPE,
        "status": session_status(row, now=current),
        "reason": row.reason,
        "read_only": True,
        "banner": VIEW_AS_BANNER,
        "created_at": _iso(row.created_at),
        "expires_at": _iso(row.expires_at),
        "ended_at": _iso(row.ended_at),
        "end_reason": row.end_reason,
        "seconds_remaining": max(
            0, int((_as_aware(row.expires_at) - current).total_seconds())
        ),
    }


async def _target_user(db: AsyncSession, user_id: str) -> models.User:
    user = await db.get(models.User, user_id)
    if user is None:
        raise ViewAsNotFound("Target user not found")
    return user


async def request_view_as(
    db: AsyncSession,
    *,
    target_user_id: str,
    reason: str,
    expires_in_minutes: int,
    actor: AdminActor,
    request=None,
) -> dict[str, Any]:
    """Create the two-person approval for one read-only target preview."""
    target_id = _canonical_user_id(target_user_id)
    minutes = _session_minutes(expires_in_minutes)
    cleaned_reason = _clean_reason(reason)
    if target_id == actor.user_id:
        raise ViewAsConflict("You cannot request view-as for yourself")
    target = await _target_user(db, target_id)

    payload = normalize_payload(
        "impersonation",
        {"target_user_id": target_id, "mode": "view_as"},
    )
    try:
        approval = await create_request(
            db,
            request_type="impersonation",
            payload=payload,
            reason=cleaned_reason,
            actor=actor,
            resource_type="user",
            resource_id=target_id,
            expires_in=timedelta(minutes=minutes),
            request=request,
            commit=False,
        )
        await record_admin_audit(
            db,
            actor=actor,
            action="admin.view_as.requested",
            target_type="user",
            target_id=target_id,
            reason=cleaned_reason,
            after={
                "status": "pending",
                "scope": VIEW_AS_SCOPE,
                "approval_id": approval.id,
                "expires_in_minutes": minutes,
            },
            metadata={
                "approval_id": approval.id,
                "approval_request_id": approval.audit_request_id,
                "target_user_id": target_id,
                "scope": VIEW_AS_SCOPE,
            },
            request=request,
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise ViewAsConflict("An open view-as approval already exists for this target") from None
    except Exception:
        await db.rollback()
        raise
    await db.refresh(approval)
    return {
        "approval": approval_summary(approval),
        "target": target_summary(target),
        "expires_in_minutes": minutes,
    }


async def start_view_as(
    db: AsyncSession,
    *,
    approval_id: str,
    note: str | None,
    actor: AdminActor,
    request=None,
) -> dict[str, Any]:
    """Consume an approved request once and mint a scoped preview token."""
    approval = await get_request(db, approval_id, for_update=True)
    if approval is None:
        raise ViewAsNotFound("Approval request not found")
    if approval.request_type != "impersonation":
        raise ViewAsConflict("This approval is not a view-as request")

    payload = normalize_payload("impersonation", approval.payload)
    target_id = str(payload["target_user_id"])
    if target_id == actor.user_id:
        raise ViewAsConflict("You cannot start a view-as session for your own account")
    await require_approved(
        db,
        approval_id=approval_id,
        request_type="impersonation",
        payload=payload,
        actor=actor,
        resource_type="user",
        resource_id=target_id,
        request=request,
    )
    target = await _target_user(db, target_id)

    existing = await db.scalar(
        select(models.AdminViewAsSession.id).where(
            models.AdminViewAsSession.approval_id == approval.id
        )
    )
    if existing is not None:
        raise ViewAsConflict("This approval already started a view-as session")

    token = f"lx_view_{secrets.token_urlsafe(32)}"
    now = _now()
    row = models.AdminViewAsSession(
        id=str(uuid.uuid4()),
        approval_id=approval.id,
        admin_user_id=actor.user_id,
        target_user_id=target_id,
        token_hash=hash_token(token),
        scope=VIEW_AS_SCOPE,
        reason=approval.reason,
        created_at=now,
        expires_at=now + timedelta(minutes=VIEW_AS_MAX_MINUTES),
    )
    db.add(row)
    await db.flush()

    await begin_execution(db, approval, actor=actor, note=note, request=request)
    await record_admin_audit(
        db,
        actor=actor,
        action="admin.view_as.started",
        target_type="user",
        target_id=target_id,
        reason=approval.reason,
        after={
            "status": "active",
            "scope": VIEW_AS_SCOPE,
            "session_id": row.id,
            "approval_id": approval.id,
            "expires_at": row.expires_at,
        },
        metadata={
            "session_id": row.id,
            "approval_id": approval.id,
            "target_user_id": target_id,
            "scope": VIEW_AS_SCOPE,
        },
        request=request,
    )
    await complete_execution(
        db,
        approval,
        actor=actor,
        result={
            "session_id": row.id,
            "target_user_id": target_id,
            "scope": VIEW_AS_SCOPE,
            "expires_at": _iso(row.expires_at),
        },
        note=note,
        request=request,
    )
    await db.commit()
    await db.refresh(row)
    await db.refresh(approval)
    return {
        "session": session_summary(row, target),
        "token": token,
        "approval": approval_summary(approval),
    }


async def list_sessions(
    db: AsyncSession,
    *,
    actor: AdminActor,
    limit: int = 20,
) -> dict[str, Any]:
    bounded = max(1, min(int(limit), 50))
    rows = (
        await db.execute(
            select(models.AdminViewAsSession)
            .where(models.AdminViewAsSession.admin_user_id == actor.user_id)
            .order_by(models.AdminViewAsSession.created_at.desc())
            .limit(bounded)
        )
    ).scalars().all()
    user_ids = {row.target_user_id for row in rows}
    users: dict[str, models.User] = {}
    if user_ids:
        users = {
            user.id: user
            for user in (
                await db.execute(select(models.User).where(models.User.id.in_(user_ids)))
            ).scalars()
        }
    now = _now()
    items = [
        session_summary(row, users[row.target_user_id], now=now)
        for row in rows
        if row.target_user_id in users
    ]
    return {"items": items, "total": len(items), "limit": bounded}


async def _load_owned_session(
    db: AsyncSession,
    *,
    session_id: str,
    token: str,
    actor: AdminActor,
    for_update: bool = False,
) -> models.AdminViewAsSession:
    if not token or len(token) > 200:
        raise ViewAsForbidden("A view-as token is required")
    stmt = select(models.AdminViewAsSession).where(
        models.AdminViewAsSession.id == session_id
    )
    if for_update:
        stmt = stmt.with_for_update()
    row = await db.scalar(stmt)
    if row is None:
        raise ViewAsNotFound("View-as session not found")
    if row.admin_user_id != actor.user_id:
        raise ViewAsForbidden("This view-as session belongs to another admin")
    if not hmac.compare_digest(row.token_hash, hash_token(token)):
        raise ViewAsForbidden("The view-as token is invalid")
    return row


async def _expire_session(
    db: AsyncSession,
    row: models.AdminViewAsSession,
    *,
    actor: AdminActor,
    request=None,
) -> None:
    if row.ended_at is not None:
        return
    row.ended_at = _now()
    row.ended_by = None
    row.end_reason = "expired"
    await record_admin_audit(
        db,
        actor=actor,
        action="admin.view_as.expired",
        target_type="user",
        target_id=row.target_user_id,
        reason="Preview session expired before use",
        before={"status": "active"},
        after={"status": "expired", "session_id": row.id},
        metadata={
            "session_id": row.id,
            "approval_id": row.approval_id,
            "target_user_id": row.target_user_id,
            "scope": VIEW_AS_SCOPE,
        },
        request=request,
    )
    await db.commit()


async def _dashboard(db: AsyncSession, user_id: str) -> dict[str, Any]:
    since_30d = _now() - timedelta(days=30)
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
                "AND status IN ('active', 'cancel_scheduled', 'past_due', 'on_hold', 'paused'))"
            ),
            {"uid": user_id, "since": since_30d},
        )
    ).one()
    return {
        "resumes": int(aggregate[0] or 0),
        "compilations": int(aggregate[1] or 0),
        "successful_compilations": int(aggregate[2] or 0),
        "failed_compilations": int(aggregate[3] or 0),
        "last_compilation_at": _iso(aggregate[4]),
        "optimizations": int(aggregate[5] or 0),
        "last_optimization_at": _iso(aggregate[6]),
        "usage_events_30d": int(aggregate[7] or 0),
        "last_activity_at": _iso(aggregate[8]),
        "has_export": bool(aggregate[9]),
        "has_active_subscription": bool(aggregate[10]),
    }


async def _resume_metadata(db: AsyncSession, user_id: str) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(
                models.Resume.id,
                models.Resume.title,
                models.Resume.document_type,
                models.Resume.created_at,
                models.Resume.updated_at,
            )
            .where(models.Resume.user_id == user_id)
            .order_by(models.Resume.updated_at.desc())
            .limit(VIEW_AS_MAX_RESUMES)
        )
    ).all()
    return [
        {
            "id": row[0],
            "title": row[1],
            "document_type": row[2],
            "created_at": _iso(row[3]),
            "updated_at": _iso(row[4]),
        }
        for row in rows
    ]


async def _plan_state(
    db: AsyncSession, user: models.User
) -> dict[str, Any]:
    subscriptions = (
        await db.execute(
            select(models.Subscription)
            .where(models.Subscription.user_id == user.id)
            .order_by(models.Subscription.created_at.desc())
            .limit(VIEW_AS_MAX_SUBSCRIPTIONS)
        )
    ).scalars().all()
    snapshot = await entitlement_service.effective_snapshot(user.id)
    quota = await entitlement_service.quota_snapshot(user.id, user.subscription_plan)
    features = {
        key: bool(value)
        for key, value in snapshot["features"].items()
        if get_feature(key) is not None and get_feature(key).gateable
    }
    return {
        "subscription_plan": user.subscription_plan,
        "subscription_status": user.subscription_status,
        "trial_used": bool(user.trial_used),
        "subscriptions": [
            {
                "id": row.id,
                "plan_id": row.plan_id,
                "status": row.status,
                "provider": row.provider,
                "current_period_start": _iso(row.current_period_start),
                "current_period_end": _iso(row.current_period_end),
                "cancelled_at": _iso(row.cancelled_at),
                "created_at": _iso(row.created_at),
            }
            for row in subscriptions
        ],
        "entitlements": {
            "features": features,
            "available": bool(snapshot.get("available")),
        },
        "quota": quota,
    }


async def _usage_state(db: AsyncSession, user_id: str) -> dict[str, Any]:
    actions = (
        await db.execute(
            select(
                models.UsageAnalytics.action,
                func.count(),
                func.max(models.UsageAnalytics.created_at),
            )
            .where(models.UsageAnalytics.user_id == user_id)
            .group_by(models.UsageAnalytics.action)
            .order_by(func.count().desc())
            .limit(VIEW_AS_MAX_USAGE_ACTIONS)
        )
    ).all()
    events = (
        await db.execute(
            select(
                models.UsageAnalytics.action,
                models.UsageAnalytics.resource_type,
                models.UsageAnalytics.created_at,
            )
            .where(models.UsageAnalytics.user_id == user_id)
            .order_by(models.UsageAnalytics.created_at.desc())
            .limit(VIEW_AS_MAX_USAGE_EVENTS)
        )
    ).all()
    return {
        "actions": [
            {"action": action, "count": int(count), "last_at": _iso(last)}
            for action, count, last in actions
        ],
        "recent_events": [
            {"action": action, "resource_type": resource_type, "created_at": _iso(created_at)}
            for action, resource_type, created_at in events
        ],
    }


async def _compose_snapshot(
    db: AsyncSession,
    *,
    row: models.AdminViewAsSession,
    target: models.User,
    timeline_limit: int,
    timeline_offset: int,
) -> dict[str, Any]:
    now = _now()
    bounded_limit = max(1, min(int(timeline_limit), MAX_TIMELINE_LIMIT))
    bounded_offset = max(0, int(timeline_offset))
    return {
        "session": session_summary(row, target, now=now),
        "dashboard": await _dashboard(db, target.id),
        "resumes": await _resume_metadata(db, target.id),
        "plan": await _plan_state(db, target),
        "usage": await _usage_state(db, target.id),
        "support_timeline": await build_subscription_timeline(
            db,
            user_id=target.id,
            actor_role="admin",
            limit=bounded_limit,
            offset=bounded_offset,
        ),
        "limitations": (
            "This is an audited read-only snapshot, not a target-user session. "
            "Document content, credentials, raw PII, user agents and provider "
            "payloads are excluded. Writes are refused for the preview token."
        ),
    }


async def build_snapshot(
    db: AsyncSession,
    *,
    session_id: str,
    token: str,
    actor: AdminActor,
    timeline_limit: int = DEFAULT_TIMELINE_LIMIT,
    timeline_offset: int = 0,
    request=None,
) -> dict[str, Any]:
    row = await _load_owned_session(
        db, session_id=session_id, token=token, actor=actor
    )
    now = _now()
    if row.ended_at is not None:
        raise ViewAsForbidden("This view-as session has ended")
    if _as_aware(row.expires_at) <= now:
        await _expire_session(db, row, actor=actor, request=request)
        raise ViewAsExpired("This view-as session has expired")
    target = await _target_user(db, row.target_user_id)
    return await _compose_snapshot(
        db,
        row=row,
        target=target,
        timeline_limit=timeline_limit,
        timeline_offset=timeline_offset,
    )


async def end_view_as(
    db: AsyncSession,
    *,
    session_id: str,
    reason: str,
    actor: AdminActor,
    request=None,
) -> dict[str, Any]:
    cleaned_reason = _clean_reason(reason)
    row = await db.scalar(
        select(models.AdminViewAsSession)
        .where(models.AdminViewAsSession.id == session_id)
        .with_for_update()
    )
    if row is None or row.admin_user_id != actor.user_id:
        raise ViewAsNotFound("View-as session not found")
    target = await _target_user(db, row.target_user_id)
    if row.ended_at is not None:
        return session_summary(row, target)
    row.ended_at = _now()
    row.ended_by = actor.user_id
    row.end_reason = cleaned_reason
    await record_admin_audit(
        db,
        actor=actor,
        action="admin.view_as.ended",
        target_type="user",
        target_id=row.target_user_id,
        reason=cleaned_reason,
        before={"status": "active"},
        after={
            "status": "ended",
            "session_id": row.id,
            "ended_at": row.ended_at,
        },
        metadata={
            "session_id": row.id,
            "approval_id": row.approval_id,
            "target_user_id": row.target_user_id,
            "scope": VIEW_AS_SCOPE,
        },
        request=request,
    )
    await db.commit()
    await db.refresh(row)
    return session_summary(row, target)
