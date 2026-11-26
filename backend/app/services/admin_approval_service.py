"""Two-person approvals for sensitive administrative actions.

A request captures an immutable, canonical payload hash. A second admin must
approve it, and the mutation that consumes it must present the same payload.
The approval row is locked for the decision and execution transitions so
concurrent approvers cannot both win, and every transition writes an
append-only admin audit row.

Only bounded identifiers are accepted in a payload: target/user UUIDs, roles,
feature keys and booleans. Documents, prompts, emails, tokens, raw IPs, user
agents and provider payloads are rejected rather than redacted.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.feature_registry import CAPABILITY_ROLES, PLAN_MATRIX_KEYS, get_feature, is_gateable
from ..database.models import AdminApproval
from .admin_audit_service import AdminActor, record_admin_audit

REQUEST_TYPES = (
    "refund",
    "account_deletion",
    "impersonation",
    "role_escalation",
    "bulk_entitlement_change",
)
STATUSES = (
    "pending",
    "approved",
    "rejected",
    "executing",
    "executed",
    "failed",
    "expired",
    "cancelled",
)
OPEN_STATUSES = ("pending", "approved", "executing")
TERMINAL_STATUSES = ("rejected", "executed", "failed", "expired", "cancelled")

DEFAULT_TTL = timedelta(hours=24)
MIN_TTL = timedelta(minutes=5)
MAX_TTL = timedelta(days=30)

MAX_REASON = 1000
MAX_NOTE = 1000
MAX_BULK_CHANGES = 50
_ASSIGNABLE_ROLES = frozenset({"user", "support", "admin"})
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


class ApprovalError(Exception):
    status_code = 409
    code = "approval_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details


class ApprovalNotFound(ApprovalError):
    status_code = 404
    code = "approval_not_found"


class ApprovalValidationError(ApprovalError):
    status_code = 422
    code = "approval_invalid"


class ApprovalRequired(ApprovalError):
    status_code = 409
    code = "approval_required"


class ApprovalForbidden(ApprovalError):
    status_code = 409
    code = "approval_self_review"


class ApprovalExpired(ApprovalError):
    status_code = 409
    code = "approval_expired"


class ApprovalReplay(ApprovalError):
    status_code = 409
    code = "approval_replayed"


class ApprovalConflict(ApprovalError):
    status_code = 409
    code = "approval_conflict"


class ApprovalPayloadMismatch(ApprovalError):
    status_code = 409
    code = "approval_payload_mismatch"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _clean_reason(value: str | None) -> str:
    cleaned = " ".join((value or "").split())[:MAX_REASON]
    if len(cleaned) < 3:
        raise ApprovalValidationError("A reason of at least 3 characters is required")
    return cleaned


def _clean_note(value: str | None) -> str | None:
    cleaned = " ".join((value or "").split())[:MAX_NOTE]
    return cleaned or None


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _uuid(value: Any, field: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise ApprovalValidationError(f"{field} must be a UUID") from None


def _bounded_string(value: Any, field: str, *, max_length: int) -> str:
    text = str(value or "").strip()
    if not text or len(text) > max_length:
        raise ApprovalValidationError(f"{field} must be 1-{max_length} characters")
    return text


def _bool(value: Any, field: str) -> bool:
    if type(value) is not bool:
        raise ApprovalValidationError(f"{field} must be a boolean")
    return value


def _reject_extra_keys(value: Mapping[str, Any], allowed: set[str], request_type: str) -> None:
    extra = set(value) - allowed
    if extra:
        raise ApprovalValidationError(
            f"Unsupported {request_type} payload field(s): {', '.join(sorted(extra))}"
        )


def _normalize_change(raw: Any, index: int) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ApprovalValidationError(f"changes[{index}] must be an object")
    scope = raw.get("scope")
    feature_key = raw.get("feature_key")
    enabled = _bool(raw.get("enabled"), f"changes[{index}].enabled")
    if scope not in {"plan", "role", "kill_switch"}:
        raise ApprovalValidationError(
            f"changes[{index}].scope must be plan, role or kill_switch"
        )
    if not isinstance(feature_key, str) or not is_gateable(feature_key):
        raise ApprovalValidationError(f"changes[{index}].feature_key is unknown or non-gateable")
    feature = get_feature(feature_key)
    assert feature is not None
    change: dict[str, Any] = {
        "scope": scope,
        "feature_key": feature.key,
        "enabled": enabled,
    }
    if scope == "plan":
        _reject_extra_keys(raw, {"scope", "plan_family", "feature_key", "enabled"}, "plan change")
        plan_family = raw.get("plan_family")
        if plan_family not in PLAN_MATRIX_KEYS:
            raise ApprovalValidationError(
                f"changes[{index}].plan_family is unknown"
            )
        change["plan_family"] = str(plan_family)
    elif scope == "role":
        _reject_extra_keys(raw, {"scope", "role", "feature_key", "enabled"}, "role change")
        role = raw.get("role")
        if role not in CAPABILITY_ROLES:
            raise ApprovalValidationError(f"changes[{index}].role is unknown")
        change["role"] = str(role)
    else:
        _reject_extra_keys(raw, {"scope", "feature_key", "enabled"}, "kill-switch change")
    return change


def normalize_payload(request_type: str, payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return the canonical, hash-stable payload for a request type.

    Unknown keys and types are rejected outright. This keeps the approval from
    becoming an opaque arbitrary-action executor and makes stale payloads
    detectable even when a caller reuses an approval id.
    """
    if request_type not in REQUEST_TYPES:
        raise ApprovalValidationError("Unknown approval request type")
    if not isinstance(payload, Mapping):
        raise ApprovalValidationError("An approval payload is required")

    if request_type == "role_escalation":
        _reject_extra_keys(
            payload,
            {"target_user_id", "previous_role", "new_role"},
            request_type,
        )
        target_user_id = _uuid(payload.get("target_user_id"), "target_user_id")
        previous_role = _bounded_string(payload.get("previous_role"), "previous_role", max_length=16)
        new_role = _bounded_string(payload.get("new_role"), "new_role", max_length=16)
        if previous_role not in _ASSIGNABLE_ROLES or previous_role == "admin":
            raise ApprovalValidationError("previous_role must be user or support")
        if new_role != "admin":
            raise ApprovalValidationError("role_escalation may only grant admin")
        return {
            "target_user_id": target_user_id,
            "previous_role": previous_role,
            "new_role": new_role,
        }

    if request_type == "bulk_entitlement_change":
        _reject_extra_keys(payload, {"changes"}, request_type)
        raw_changes = payload.get("changes")
        if not isinstance(raw_changes, list) or not raw_changes:
            raise ApprovalValidationError("changes must be a non-empty list")
        if len(raw_changes) > MAX_BULK_CHANGES:
            raise ApprovalValidationError(
                f"changes cannot contain more than {MAX_BULK_CHANGES} entries"
            )
        changes = [_normalize_change(raw, index) for index, raw in enumerate(raw_changes)]
        seen: set[tuple[str, str, str]] = set()
        for change in changes:
            scope_key = change.get("plan_family") or change.get("role") or ""
            identity = (change["scope"], scope_key, change["feature_key"])
            if identity in seen:
                raise ApprovalValidationError("changes contains a duplicate cell")
            seen.add(identity)
        changes.sort(
            key=lambda item: (
                item["scope"],
                item.get("plan_family") or item.get("role") or "",
                item["feature_key"],
            )
        )
        return {"changes": changes}

    if request_type == "refund":
        _reject_extra_keys(
            payload,
            {"refund_request_id", "payment_id", "amount", "currency"},
            request_type,
        )
        amount = payload.get("amount")
        if amount is not None:
            if type(amount) is not int or amount <= 0 or amount > 100_000_000:
                raise ApprovalValidationError("amount must be a positive integer")
        currency = payload.get("currency")
        if currency is not None:
            currency = _bounded_string(currency, "currency", max_length=3).upper()
            if not _CURRENCY_RE.fullmatch(currency):
                raise ApprovalValidationError("currency must be a three-letter ISO code")
        return {
            "refund_request_id": _uuid(payload.get("refund_request_id"), "refund_request_id"),
            "payment_id": _uuid(payload.get("payment_id"), "payment_id"),
            "amount": amount,
            "currency": currency,
        }

    if request_type == "account_deletion":
        _reject_extra_keys(payload, {"gdpr_request_id", "user_id"}, request_type)
        return {
            "gdpr_request_id": _uuid(payload.get("gdpr_request_id"), "gdpr_request_id"),
            "user_id": _uuid(payload.get("user_id"), "user_id"),
        }

    # Impersonation/view-as is reserved so a future surface cannot execute
    # without an approved, payload-bound request. No such endpoint exists yet.
    _reject_extra_keys(payload, {"target_user_id", "mode"}, request_type)
    if payload.get("mode") != "view_as":
        raise ApprovalValidationError("impersonation mode must be view_as")
    return {
        "target_user_id": _uuid(payload.get("target_user_id"), "target_user_id"),
        "mode": "view_as",
    }


def payload_hash(request_type: str, payload: Mapping[str, Any]) -> str:
    normalized = normalize_payload(request_type, payload)
    return hashlib.sha256(
        _canonical_json({"request_type": request_type, "payload": normalized}).encode("utf-8")
    ).hexdigest()


def _ttl(expires_in: timedelta | None) -> timedelta:
    if expires_in is None:
        return DEFAULT_TTL
    if expires_in < MIN_TTL or expires_in > MAX_TTL:
        raise ApprovalValidationError(
            "Approval expiry must be between 5 minutes and 30 days"
        )
    return expires_in


def approval_summary(row: AdminApproval, *, now: datetime | None = None) -> dict[str, Any]:
    current = now or _now()
    expires_at = _as_aware(row.expires_at)
    return {
        "id": row.id,
        "request_type": row.request_type,
        "resource_type": row.resource_type,
        "resource_id": row.resource_id,
        "payload_hash": row.payload_hash,
        "payload": row.payload,
        "reason": row.reason,
        "status": row.status,
        "requested_by": row.requested_by,
        "approved_by": row.approved_by,
        "executed_by": row.executed_by,
        "decision_note": row.decision_note,
        "execution_note": row.execution_note,
        "result": row.result,
        "requested_at": row.requested_at.isoformat() if row.requested_at else None,
        "expires_at": expires_at.isoformat(),
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        "executed_at": row.executed_at.isoformat() if row.executed_at else None,
        "is_expired": row.status in {"pending", "approved"} and expires_at <= current,
        "can_approve": row.status == "pending" and expires_at > current,
        "can_execute": row.status == "approved" and expires_at > current,
        "audit_request_id": row.audit_request_id,
        "audit_decision_id": row.audit_decision_id,
        "audit_execution_id": row.audit_execution_id,
    }


async def create_request(
    db: AsyncSession,
    *,
    request_type: str,
    payload: Mapping[str, Any],
    reason: str | None,
    actor: AdminActor | None = None,
    requested_by: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    expires_in: timedelta | None = None,
    request=None,
    commit: bool = True,
) -> AdminApproval:
    """Create one pending approval, or fail if an open one already exists."""
    normalized = normalize_payload(request_type, payload)
    expected_hash = payload_hash(request_type, normalized)
    requester = (actor.user_id if actor else requested_by) or ""
    if not requester:
        raise ApprovalValidationError("A requester is required")
    requester = str(requester)[:36]
    cleaned_reason = _clean_reason(reason)
    ttl = _ttl(expires_in)

    existing = await db.scalar(
        select(AdminApproval)
        .where(
            AdminApproval.request_type == request_type,
            AdminApproval.payload_hash == expected_hash,
            AdminApproval.status.in_(OPEN_STATUSES),
        )
        .with_for_update()
    )
    if existing is not None:
        raise ApprovalConflict(
            "An open approval already exists for this payload",
            details={"approval_id": existing.id},
        )

    now = _now()
    row = AdminApproval(
        id=str(uuid.uuid4()),
        request_type=request_type,
        resource_type=(resource_type or "")[:32] or None,
        resource_id=(str(resource_id)[:255] if resource_id else None),
        payload_hash=expected_hash,
        payload=normalized,
        reason=cleaned_reason,
        status="pending",
        requested_by=requester,
        requested_at=now,
        expires_at=now + ttl,
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError:
        raise ApprovalConflict(
            "An open approval already exists for this payload"
        ) from None

    audit_actor = actor or AdminActor(user_id=requester, email=None, role="user")
    audit = await record_admin_audit(
        db,
        actor=audit_actor,
        action="admin.approval.requested",
        target_type="admin_approval",
        target_id=row.id,
        reason=cleaned_reason,
        after={
            "status": "pending",
            "request_type": request_type,
            "payload_hash": expected_hash,
            "expires_at": row.expires_at,
        },
        metadata={
            "approval_id": row.id,
            "request_type": request_type,
            "resource_type": row.resource_type,
            "resource_id": row.resource_id,
        },
        request=request,
    )
    row.audit_request_id = audit.id
    if commit:
        await db.commit()
        await db.refresh(row)
    return row


async def list_requests(
    db: AsyncSession,
    *,
    status: str | None = None,
    request_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int, dict[str, int]]:
    if status is not None and status not in STATUSES:
        raise ApprovalValidationError("Unknown approval status")
    if request_type is not None and request_type not in REQUEST_TYPES:
        raise ApprovalValidationError("Unknown approval request type")
    stmt = select(AdminApproval)
    count_stmt = select(func.count()).select_from(AdminApproval)
    if status:
        stmt = stmt.where(AdminApproval.status == status)
        count_stmt = count_stmt.where(AdminApproval.status == status)
    if request_type:
        stmt = stmt.where(AdminApproval.request_type == request_type)
        count_stmt = count_stmt.where(AdminApproval.request_type == request_type)
    total = int((await db.execute(count_stmt)).scalar_one())
    rows = (
        await db.execute(
            stmt.order_by(AdminApproval.requested_at.desc(), AdminApproval.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    count_rows = (
        await db.execute(
            select(AdminApproval.status, func.count()).group_by(AdminApproval.status)
        )
    ).all()
    counts = {status_name: 0 for status_name in STATUSES}
    counts.update({str(name): int(count) for name, count in count_rows})
    return [approval_summary(row) for row in rows], total, counts


async def get_request(
    db: AsyncSession, approval_id: str, *, for_update: bool = False
) -> AdminApproval | None:
    stmt = select(AdminApproval).where(AdminApproval.id == approval_id)
    if for_update:
        stmt = stmt.with_for_update()
    return await db.scalar(stmt)


async def get_open_for_resource(
    db: AsyncSession,
    *,
    request_type: str,
    resource_id: str,
    for_update: bool = False,
) -> AdminApproval | None:
    stmt = (
        select(AdminApproval)
        .where(
            AdminApproval.request_type == request_type,
            AdminApproval.resource_id == str(resource_id),
            AdminApproval.status.in_(OPEN_STATUSES),
        )
        .order_by(AdminApproval.requested_at.desc())
        .limit(1)
    )
    if for_update:
        stmt = stmt.with_for_update()
    return await db.scalar(stmt)


async def _expire(
    db: AsyncSession,
    row: AdminApproval,
    *,
    actor: AdminActor,
    request=None,
    trigger: str,
) -> None:
    before = row.status
    row.status = "expired"
    await record_admin_audit(
        db,
        actor=actor,
        action="admin.approval.expired",
        target_type="admin_approval",
        target_id=row.id,
        reason="Approval expired before use",
        before={"status": before},
        after={"status": "expired"},
        metadata={
            "approval_id": row.id,
            "request_type": row.request_type,
            "trigger": trigger,
        },
        request=request,
    )
    await db.flush()


async def _require_not_expired(
    db: AsyncSession,
    row: AdminApproval,
    *,
    actor: AdminActor,
    request=None,
) -> None:
    if row.status in {"pending", "approved"} and _as_aware(row.expires_at) <= _now():
        await _expire(db, row, actor=actor, request=request, trigger="accessed")
        await db.commit()
        raise ApprovalExpired("This approval expired before it could be used")


async def decide(
    db: AsyncSession,
    *,
    approval_id: str,
    decision: str,
    note: str | None,
    actor: AdminActor,
    request=None,
) -> AdminApproval:
    if decision not in {"approve", "reject"}:
        raise ApprovalValidationError("Decision must be approve or reject")
    row = await get_request(db, approval_id, for_update=True)
    if row is None:
        raise ApprovalNotFound("Approval request not found")
    if row.status == "executing":
        raise ApprovalReplay("This approval is already being executed")
    if row.status == "executed":
        raise ApprovalReplay("This approval was already executed")
    if row.status in TERMINAL_STATUSES:
        raise ApprovalReplay(f"This approval is already {row.status}")
    if row.status != "pending":
        raise ApprovalConflict("Only a pending approval can be decided")
    await _require_not_expired(db, row, actor=actor, request=request)
    if row.requested_by == actor.user_id:
        raise ApprovalForbidden("The requester cannot approve their own request")

    before = {"status": row.status, "approved_by": row.approved_by}
    row.status = "approved" if decision == "approve" else "rejected"
    row.approved_by = actor.user_id[:36]
    row.decision_note = _clean_note(note)
    row.decided_at = _now()
    audit = await record_admin_audit(
        db,
        actor=actor,
        action="admin.approval.approved" if decision == "approve" else "admin.approval.rejected",
        target_type="admin_approval",
        target_id=row.id,
        reason=row.decision_note,
        before=before,
        after={"status": row.status, "approved_by": row.approved_by},
        metadata={
            "approval_id": row.id,
            "request_type": row.request_type,
            "payload_hash": row.payload_hash,
            "resource_type": row.resource_type,
            "resource_id": row.resource_id,
        },
        request=request,
    )
    row.audit_decision_id = audit.id
    await db.commit()
    await db.refresh(row)
    return row


async def cancel(
    db: AsyncSession,
    *,
    approval_id: str,
    reason: str | None,
    actor: AdminActor,
    request=None,
) -> AdminApproval:
    row = await get_request(db, approval_id, for_update=True)
    if row is None:
        raise ApprovalNotFound("Approval request not found")
    if row.status != "pending":
        raise ApprovalConflict("Only a pending approval can be cancelled")
    if row.requested_by != actor.user_id:
        raise ApprovalForbidden("Only the requester can cancel this approval")
    cleaned = _clean_note(reason)
    row.status = "cancelled"
    row.decision_note = cleaned
    row.decided_at = _now()
    await record_admin_audit(
        db,
        actor=actor,
        action="admin.approval.cancelled",
        target_type="admin_approval",
        target_id=row.id,
        reason=cleaned,
        before={"status": "pending"},
        after={"status": "cancelled"},
        metadata={
            "approval_id": row.id,
            "request_type": row.request_type,
            "resource_type": row.resource_type,
            "resource_id": row.resource_id,
        },
        request=request,
    )
    await db.commit()
    await db.refresh(row)
    return row


async def require_approved(
    db: AsyncSession,
    *,
    approval_id: str,
    request_type: str,
    payload: Mapping[str, Any],
    actor: AdminActor,
    resource_type: str | None = None,
    resource_id: str | None = None,
    request=None,
) -> AdminApproval:
    """Lock and validate an approved request against the exact payload.

    Raises before any caller mutation so a stale, expired or replayed approval
    can never partially execute a sensitive action.
    """
    row = await get_request(db, approval_id, for_update=True)
    if row is None:
        raise ApprovalRequired("An approved two-person approval is required")
    expected_hash = payload_hash(request_type, payload)
    if row.request_type != request_type:
        raise ApprovalPayloadMismatch("The approval does not match this action type")
    if row.payload_hash != expected_hash:
        raise ApprovalPayloadMismatch(
            "The approved payload no longer matches this action; request a new approval"
        )
    if resource_type is not None and row.resource_type != resource_type:
        raise ApprovalPayloadMismatch("The approval does not match this resource type")
    if resource_id is not None and row.resource_id != str(resource_id):
        raise ApprovalPayloadMismatch("The approval does not match this resource")
    await _require_not_expired(db, row, actor=actor, request=request)
    if row.status == "executing":
        raise ApprovalReplay("This approval is already being executed")
    if row.status == "executed":
        raise ApprovalReplay("This approval was already executed")
    if row.status == "expired":
        raise ApprovalExpired("This approval has expired")
    if row.status in {"rejected", "cancelled", "failed"}:
        raise ApprovalReplay(f"This approval is {row.status} and cannot be executed")
    if row.status == "pending":
        raise ApprovalRequired("This approval is still awaiting a second admin")
    if row.status != "approved":
        raise ApprovalConflict("This approval is not approved")
    if not row.approved_by or row.approved_by == row.requested_by:
        raise ApprovalForbidden("This approval does not satisfy separation of duties")
    return row


async def begin_execution(
    db: AsyncSession,
    row: AdminApproval,
    *,
    actor: AdminActor,
    note: str | None = None,
    request=None,
) -> None:
    if row.status != "approved":
        raise ApprovalConflict("Only an approved request can start execution")
    row.status = "executing"
    row.executed_by = actor.user_id[:36]
    row.execution_note = _clean_note(note)
    await record_admin_audit(
        db,
        actor=actor,
        action="admin.approval.execution_started",
        target_type="admin_approval",
        target_id=row.id,
        reason=row.execution_note or row.reason,
        before={"status": "approved"},
        after={"status": "executing", "executed_by": row.executed_by},
        metadata={
            "approval_id": row.id,
            "request_type": row.request_type,
            "payload_hash": row.payload_hash,
            "resource_type": row.resource_type,
            "resource_id": row.resource_id,
        },
        request=request,
    )
    await db.flush()


async def complete_execution(
    db: AsyncSession,
    row: AdminApproval,
    *,
    actor: AdminActor,
    result: Mapping[str, Any] | None = None,
    note: str | None = None,
    request=None,
) -> None:
    if row.status not in {"approved", "executing", "failed"}:
        raise ApprovalConflict("This approval cannot be marked executed")
    row.status = "executed"
    row.executed_at = _now()
    row.executed_by = actor.user_id[:36]
    if note is not None:
        row.execution_note = _clean_note(note)
    row.result = dict(result) if result else None
    audit = await record_admin_audit(
        db,
        actor=actor,
        action="admin.approval.executed",
        target_type="admin_approval",
        target_id=row.id,
        reason=row.execution_note or row.reason,
        before={"status": "executing"},
        after={"status": "executed", "result": row.result},
        metadata={
            "approval_id": row.id,
            "request_type": row.request_type,
            "payload_hash": row.payload_hash,
            "resource_type": row.resource_type,
            "resource_id": row.resource_id,
        },
        request=request,
    )
    row.audit_execution_id = audit.id
    await db.flush()


async def fail_execution(
    db: AsyncSession,
    row: AdminApproval,
    *,
    actor: AdminActor,
    error_code: str = "execution_failed",
    note: str | None = None,
    request=None,
) -> None:
    if row.status != "executing":
        raise ApprovalConflict("Only an executing approval can be marked failed")
    row.status = "failed"
    row.executed_by = actor.user_id[:36]
    row.execution_note = _clean_note(note)
    row.result = {"error_code": str(error_code)[:64]}
    audit = await record_admin_audit(
        db,
        actor=actor,
        action="admin.approval.execution_failed",
        target_type="admin_approval",
        target_id=row.id,
        reason=row.execution_note or row.reason,
        before={"status": "executing"},
        after={"status": "failed", "result": row.result},
        metadata={
            "approval_id": row.id,
            "request_type": row.request_type,
            "payload_hash": row.payload_hash,
            "resource_type": row.resource_type,
            "resource_id": row.resource_id,
        },
        request=request,
    )
    row.audit_execution_id = audit.id
    await db.flush()


async def sync_decision(
    db: AsyncSession,
    *,
    request_type: str,
    resource_id: str,
    decision: str,
    note: str | None,
    actor: AdminActor,
    request=None,
) -> AdminApproval | None:
    """Mirror a decision made by a dedicated workflow into its approval row.

    Refund and deletion workflows own their domain state and audits. This keeps
    the shared pending queue in lockstep without making those endpoints depend
    on the queue's HTTP surface.
    """
    row = await get_open_for_resource(
        db, request_type=request_type, resource_id=resource_id, for_update=True
    )
    if row is None:
        return None
    if row.status == "approved" and decision == "approve":
        return row
    if row.status == "rejected" and decision == "reject":
        return row
    if row.status != "pending":
        raise ApprovalConflict("This approval is no longer pending")
    await _require_not_expired(db, row, actor=actor, request=request)
    if row.requested_by == actor.user_id:
        raise ApprovalForbidden("The requester cannot approve their own request")
    row.status = "approved" if decision == "approve" else "rejected"
    row.approved_by = actor.user_id[:36]
    row.decision_note = _clean_note(note)
    row.decided_at = _now()
    audit = await record_admin_audit(
        db,
        actor=actor,
        action="admin.approval.approved" if decision == "approve" else "admin.approval.rejected",
        target_type="admin_approval",
        target_id=row.id,
        reason=row.decision_note,
        before={"status": "pending"},
        after={"status": row.status, "approved_by": row.approved_by},
        metadata={
            "approval_id": row.id,
            "request_type": row.request_type,
            "payload_hash": row.payload_hash,
            "resource_type": row.resource_type,
            "resource_id": row.resource_id,
            "source": "workflow",
        },
        request=request,
    )
    row.audit_decision_id = audit.id
    await db.flush()
    return row


async def require_approved_for_resource(
    db: AsyncSession,
    *,
    request_type: str,
    resource_id: str,
    payload: Mapping[str, Any],
    actor: AdminActor,
    request=None,
) -> AdminApproval | None:
    row = await get_open_for_resource(
        db, request_type=request_type, resource_id=resource_id, for_update=True
    )
    if row is None:
        return None
    return await require_approved(
        db,
        approval_id=row.id,
        request_type=request_type,
        payload=payload,
        actor=actor,
        resource_type=row.resource_type,
        resource_id=resource_id,
        request=request,
    )


async def sync_execution_start(
    db: AsyncSession,
    *,
    request_type: str,
    resource_id: str,
    actor: AdminActor,
    note: str | None = None,
    request=None,
) -> AdminApproval | None:
    """Mark the linked approval executing before a provider side effect."""
    row = await get_open_for_resource(
        db, request_type=request_type, resource_id=resource_id, for_update=True
    )
    if row is None:
        return None
    await _require_not_expired(db, row, actor=actor, request=request)
    if row.status == "executing":
        return row
    if row.status == "pending":
        raise ApprovalRequired("This action has not been approved by a second admin")
    if row.status in {"rejected", "cancelled", "expired"}:
        raise ApprovalReplay(f"This approval is {row.status}")
    if row.status == "executed":
        raise ApprovalReplay("This approval was already executed")
    if row.status != "approved":
        raise ApprovalConflict("This approval cannot start execution")
    await begin_execution(db, row, actor=actor, note=note, request=request)
    return row


async def sync_execution(
    db: AsyncSession,
    *,
    request_type: str,
    resource_id: str,
    actor: AdminActor,
    result: Mapping[str, Any] | None = None,
    failed: bool = False,
    note: str | None = None,
    request=None,
) -> AdminApproval | None:
    row = await get_open_for_resource(
        db, request_type=request_type, resource_id=resource_id, for_update=True
    )
    if row is None:
        return None
    if row.status == "pending":
        raise ApprovalRequired("This action has not been approved by a second admin")
    if row.status in {"rejected", "cancelled", "expired"}:
        raise ApprovalReplay(f"This approval is {row.status}")
    if row.status == "executed":
        return row
    if row.status == "approved":
        await begin_execution(db, row, actor=actor, note=note, request=request)
    if row.status == "failed" and failed:
        return row
    if failed:
        await fail_execution(
            db,
            row,
            actor=actor,
            error_code="workflow_failed",
            note=note,
            request=request,
        )
    else:
        await complete_execution(
            db,
            row,
            actor=actor,
            result=result,
            note=note,
            request=request,
        )
    return row


async def _apply_bulk_entitlements(
    db: AsyncSession,
    *,
    changes: list[dict[str, Any]],
    actor: AdminActor,
    reason: str,
    approval_id: str | None,
    request=None,
) -> dict[str, Any]:
    from .entitlement_service import entitlement_service

    before_state = await entitlement_service.get_state(db)
    for change in changes:
        scope = change["scope"]
        enabled = bool(change["enabled"])
        feature_key = change["feature_key"]
        if scope == "kill_switch":
            await entitlement_service.set_kill_switch(
                feature_key, enabled, db, commit=False
            )
        elif scope == "plan":
            await entitlement_service.set_matrix_cell(
                change["plan_family"], feature_key, enabled, db, commit=False
            )
        else:
            await entitlement_service.set_role_cell(
                change["role"], feature_key, enabled, db, commit=False
            )

        if scope == "kill_switch":
            before = before_state["kill_switches"].get(feature_key)
            target_type = "feature_key"
            target_id = feature_key
        elif scope == "plan":
            before = before_state["matrix"].get(change["plan_family"], {}).get(feature_key)
            target_type = "plan_feature"
            target_id = f"{change['plan_family']}:{feature_key}"
        else:
            before = (before_state.get("role_matrix") or {}).get(change["role"], {}).get(feature_key)
            target_type = "role_feature"
            target_id = f"{change['role']}:{feature_key}"
        await record_admin_audit(
            db,
            actor=actor,
            action="entitlement.bulk.update",
            target_type=target_type,
            target_id=target_id,
            reason=reason,
            before={"enabled": before},
            after={"enabled": enabled},
            metadata={"approval_id": approval_id, "scope": scope, "feature_key": feature_key},
            request=request,
        )
    return {"applied": len(changes), "scopes": sorted({change["scope"] for change in changes})}


async def execute_bulk_approval(
    db: AsyncSession,
    *,
    approval_id: str,
    changes: list[dict[str, Any]],
    actor: AdminActor,
    note: str | None = None,
    request=None,
) -> AdminApproval:
    """Apply an approved bulk entitlement change exactly once."""
    payload = normalize_payload("bulk_entitlement_change", {"changes": changes})
    row = await require_approved(
        db,
        approval_id=approval_id,
        request_type="bulk_entitlement_change",
        payload=payload,
        actor=actor,
        resource_type="entitlement_bulk",
        request=request,
    )
    await begin_execution(db, row, actor=actor, note=note, request=request)
    result = await _apply_bulk_entitlements(
        db,
        changes=payload["changes"],
        actor=actor,
        reason=row.reason,
        approval_id=row.id,
        request=request,
    )
    await complete_execution(
        db, row, actor=actor, result=result, note=note, request=request
    )
    await db.commit()
    await db.refresh(row)
    return row


async def execute_role_escalation(
    db: AsyncSession,
    *,
    approval_id: str,
    target_user_id: str,
    previous_role: str,
    new_role: str,
    actor: AdminActor,
    note: str | None = None,
    request=None,
):
    """Apply an approved user role escalation exactly once."""
    from ..database.models import User

    payload = normalize_payload(
        "role_escalation",
        {
            "target_user_id": target_user_id,
            "previous_role": previous_role,
            "new_role": new_role,
        },
    )
    row = await require_approved(
        db,
        approval_id=approval_id,
        request_type="role_escalation",
        payload=payload,
        actor=actor,
        resource_type="user",
        resource_id=payload["target_user_id"],
        request=request,
    )
    user = await db.scalar(
        select(User).where(User.id == payload["target_user_id"]).with_for_update()
    )
    if user is None:
        raise ApprovalConflict("The target user no longer exists")
    if user.role != payload["previous_role"]:
        raise ApprovalPayloadMismatch(
            "The target's role changed after this approval was requested; request a new approval"
        )
    await begin_execution(db, row, actor=actor, note=note, request=request)
    user.role = payload["new_role"]
    await record_admin_audit(
        db,
        actor=actor,
        action="user.role.change",
        target_type="user",
        target_id=payload["target_user_id"],
        reason=row.reason,
        before={"role": payload["previous_role"]},
        after={"role": payload["new_role"], "approval_id": row.id},
        metadata={"approval_id": row.id, "request_type": "role_escalation"},
        request=request,
    )
    await complete_execution(
        db,
        row,
        actor=actor,
        result={
            "target_user_id": payload["target_user_id"],
            "previous_role": payload["previous_role"],
            "new_role": payload["new_role"],
        },
        note=note,
        request=request,
    )
    await db.commit()
    await db.refresh(row)
    await db.refresh(user)
    return row, user


async def pending_counts(db: AsyncSession) -> dict[str, int]:
    rows = (
        await db.execute(
            select(AdminApproval.request_type, func.count())
            .where(AdminApproval.status == "pending")
            .group_by(AdminApproval.request_type)
        )
    ).all()
    return {str(request_type): int(count) for request_type, count in rows}
