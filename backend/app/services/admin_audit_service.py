"""Append-only audit records and request context for admin mutations.

The audit log is intentionally small and boring: it identifies the actor,
action, target, reason, request, and a bounded before/after diff. It must never
become a shadow copy of resumes, prompts, job descriptions, tokens, or billing
credentials. Callers should pass curated fields, not raw ORM rows.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping

from fastapi import Request
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.log_sanitize import sanitize_for_log
from ..database.models import AdminAuditLog

_ACTION_RE = re.compile(r"^[a-z][a-z0-9_.-]{2,119}$")
_TARGET_RE = re.compile(r"^[a-z][a-z0-9_.-]{1,49}$")
_MAX_REASON = 1000
_MAX_STRING = 500
_MAX_ITEMS = 40
_MAX_DEPTH = 3

_REDACT_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "authorization",
    "cookie",
    "api_key",
    "apikey",
    "encrypted",
    "private",
    "credential",
    "latex",
    "content",
    "prompt",
    "job_description",
    "job_description_text",
    "original_latex",
    "optimized_latex",
    "structured_content",
    "document",
    "cover_letter",
)


@dataclass(frozen=True)
class AdminActor:
    user_id: str
    email: str | None
    role: str


@dataclass(frozen=True)
class AuditRequestContext:
    request_id: str | None
    ip_address: str | None


def audit_request_context(request: Request | None) -> AuditRequestContext:
    """Extract only server-observed request metadata; never trust a forwarded IP."""
    if request is None:
        return AuditRequestContext(None, None)
    request_id = getattr(request.state, "request_id", None)
    if not isinstance(request_id, str) or not request_id.strip():
        request_id = None
    else:
        request_id = request_id.strip()[:255]
    candidate = request.client.host if request.client else None
    ip_address: str | None = None
    if candidate:
        try:
            ip_address = str(ipaddress.ip_address(candidate))
        except ValueError:
            ip_address = None
    return AuditRequestContext(request_id, ip_address)


def _redact_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in _REDACT_KEY_PARTS)


def _bounded_json(value: Any, *, depth: int = 0) -> Any:
    if depth > _MAX_DEPTH:
        return "[truncated]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= _MAX_STRING else value[:_MAX_STRING] + "…"
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= _MAX_ITEMS:
                result["_truncated"] = True
                break
            text_key = str(key)[:100]
            if _redact_key(text_key):
                result[text_key] = "[redacted]"
            else:
                result[text_key] = _bounded_json(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple, set)):
        return [_bounded_json(item, depth=depth + 1) for item in list(value)[:_MAX_ITEMS]]
    return str(value)[:_MAX_STRING]


def _reason(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(str(value).split())
    if not cleaned:
        return None
    return cleaned[:_MAX_REASON]


def _audit_payload(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    bounded = _bounded_json(value)
    return bounded if isinstance(bounded, dict) else {"value": bounded}


async def record_admin_audit(
    db: AsyncSession,
    *,
    actor: AdminActor,
    action: str,
    target_type: str,
    target_id: str | None,
    reason: str | None = None,
    before: Mapping[str, Any] | None = None,
    after: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
    request: Request | None = None,
    commit: bool = False,
) -> AdminAuditLog:
    """Add one immutable audit row.

    ``commit=False`` is the default so the mutation and its audit record share
    one transaction. Read-only sensitive actions (for example a PII reveal) have
    no other mutation and should pass ``commit=True``.
    """
    if not _ACTION_RE.fullmatch(action):
        raise ValueError("Invalid audit action identifier")
    if not _TARGET_RE.fullmatch(target_type):
        raise ValueError("Invalid audit target type")
    cleaned_reason = _reason(reason)
    if target_id is not None:
        target_id = str(target_id)[:255]
    context = audit_request_context(request)
    row = AdminAuditLog(
        actor_user_id=actor.user_id[:36],
        actor_email=actor.email[:255] if actor.email else None,
        action=action,
        target_type=target_type,
        target_id=target_id,
        reason=cleaned_reason,
        request_id=context.request_id,
        ip_address=context.ip_address,
        before_state=_audit_payload(before),
        after_state=_audit_payload(after),
        event_metadata=_audit_payload(metadata),
    )
    db.add(row)
    if commit:
        await db.commit()
        await db.refresh(row)
    else:
        await db.flush()
    return row


def _audit_select(
    *, actor_user_id: str | None, action: str | None, target_type: str | None,
    target_id: str | None, created_after: datetime | None, created_before: datetime | None,
) -> Select:
    stmt = select(AdminAuditLog)
    if actor_user_id:
        stmt = stmt.where(AdminAuditLog.actor_user_id == actor_user_id)
    if action:
        stmt = stmt.where(AdminAuditLog.action == action)
    if target_type:
        stmt = stmt.where(AdminAuditLog.target_type == target_type)
    if target_id:
        stmt = stmt.where(AdminAuditLog.target_id == target_id)
    if created_after:
        stmt = stmt.where(AdminAuditLog.created_at >= created_after)
    if created_before:
        stmt = stmt.where(AdminAuditLog.created_at <= created_before)
    return stmt


async def list_admin_audit(
    db: AsyncSession,
    *,
    actor_user_id: str | None = None,
    action: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AdminAuditLog], int]:
    stmt = _audit_select(
        actor_user_id=actor_user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        created_after=created_after,
        created_before=created_before,
    )
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = int((await db.execute(count_stmt)).scalar_one())
    rows = (
        await db.execute(stmt.order_by(AdminAuditLog.created_at.desc()).limit(limit).offset(offset))
    ).scalars().all()
    return list(rows), total


def audit_row_summary(row: AdminAuditLog) -> dict[str, Any]:
    """Stable API representation; actor email is already an audit snapshot."""
    return {
        "id": row.id,
        "actor_user_id": row.actor_user_id,
        "actor_email": row.actor_email,
        "action": row.action,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "reason": row.reason,
        "request_id": row.request_id,
        "ip_address": str(row.ip_address) if row.ip_address else None,
        "before": row.before_state,
        "after": row.after_state,
        "metadata": row.event_metadata,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def safe_log_actor(actor: AdminActor) -> str:
    return sanitize_for_log(actor.user_id)


def unique_strings(values: Iterable[str]) -> list[str]:
    """Small helper for filtered action lists in the admin UI."""
    return sorted({value for value in values if value})
