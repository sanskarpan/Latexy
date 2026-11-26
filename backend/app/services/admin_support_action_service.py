"""Admin-triggered support emails with cooldown, audit and token hygiene.

The self-service Better Auth flows remain the only public way to request a
verification or password-reset email. This module adds an admin-only support
path that reuses the same email transport and produces tokens Better Auth can
consume, without ever returning a token, one-time link or recipient address to
the caller or writing one to the audit log.

Actions are cooldown-gated per actor+target and audited as an append-only
``started`` row followed by a terminal ``completed``/``failed`` row. That
ordering means even a provider timeout leaves durable evidence of who attempted
to send what, for which target, and why.
"""

from __future__ import annotations

import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence
from urllib.parse import quote

import jwt
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.logging import get_logger
from ..core.redis import get_redis_client
from ..database import models
from .admin_audit_service import AdminActor, record_admin_audit
from .admin_user_service import invalidate_user_360_cache
from .dodo_provider import DodoAPIError
from .email_health_service import recipient_digest
from .email_service import (
    EmailAttachment,
    EmailSendResult,
    email_service,
    render_account_password_reset_email,
    render_account_verification_email,
    render_payment_receipt_email,
)
from .payment_service import payment_service

logger = get_logger(__name__)

User = models.User
Payment = models.Payment
Subscription = models.Subscription
AdminAuditLog = models.AdminAuditLog

# One send per actor+target per action window. Verification and receipts are
# routine support actions; a reset invalidates the target's previous reset
# links, so it gets a longer window.
SUPPORT_ACTION_WINDOWS: dict[str, int] = {
    "verification_email": 300,
    "password_reset": 600,
    "payment_receipt": 300,
}

_VERIFICATION_TOKEN_TTL_SECONDS = 3600
_PASSWORD_RESET_TOKEN_TTL_SECONDS = 3600
_MAX_REASON = 1000
_RECEIPT_ACTION = "user.payment_receipt.send"
_RECEIPT_IN_PROGRESS_SECONDS = 120
_IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9._:-]{8,64}$")
_RECEIPT_SETTLED_STATUSES = frozenset({"paid", "partially_refunded"})
_MAX_INVOICE_ATTACHMENT_BYTES = 4 * 1024 * 1024

# Atomic fixed-window counter. TTL is only attached on the first increment so
# a burst cannot extend the window indefinitely.
_SUPPORT_ACTION_LUA = """
local n = redis.call('INCR', KEYS[1])
if n == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {n, ttl}
"""


class SupportActionNotEligible(RuntimeError):
    """The target exists but cannot receive this action right now."""


class SupportActionCooldown(RuntimeError):
    """Raised when one actor+target exceeds the action cooldown."""

    def __init__(self, retry_after: int):
        self.retry_after = max(1, int(retry_after))
        super().__init__("Support action cooldown is active")


class SupportActionProviderError(RuntimeError):
    """Provider failure with a safe, caller-visible status and message."""

    def __init__(self, message: str, *, status_code: int = 502, retryable: bool = False):
        self.status_code = status_code
        self.retryable = bool(retryable)
        super().__init__(message)


class SupportActionUnavailable(RuntimeError):
    """Server-side prerequisite (auth secret or email transport) is missing."""


class SupportActionConflict(RuntimeError):
    """An idempotency key is already in flight or belongs to another target.

    A conflict is deliberately distinct from a cooldown: the operator must not
    retry with a fresh key for the same logical send, and a key can never be
    reused for a different payment.
    """


def _clean_reason(reason: str) -> str:
    cleaned = " ".join((reason or "").split())[:_MAX_REASON]
    if len(cleaned) < 3:
        raise ValueError("A reason of at least 3 characters is required")
    return cleaned


def _canonical_uuid(value: str) -> str | None:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return None


def _normalize_idempotency_key(value: str | None) -> str:
    """Accept a caller key or mint one; never persist a free-form value."""
    if value is None:
        return uuid.uuid4().hex
    key = (value or "").strip()
    if not _IDEMPOTENCY_KEY_RE.fullmatch(key):
        raise ValueError(
            "idempotency_key must be 8-64 characters of letters, digits, dot, "
            "underscore, colon or hyphen"
        )
    return key


def _metadata_value(row: AdminAuditLog, key: str) -> Any:
    metadata = row.event_metadata if isinstance(row.event_metadata, Mapping) else {}
    return metadata.get(key)


def _seconds_since(value: datetime | None) -> float:
    if not isinstance(value, datetime):
        return float("inf")
    moment = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - moment).total_seconds())


def _receipt_replay_response(row: AdminAuditLog, idempotency_key: str) -> dict[str, Any]:
    """Rebuild a completed response from its immutable audit metadata."""
    line_items_count = _metadata_value(row, "line_items_count")
    return {
        "action": "payment_receipt",
        "status": "already_sent",
        "delivery": "accepted",
        "duplicate": True,
        "idempotency_key": idempotency_key,
        "target_user_id": row.target_id,
        "payment_id": _metadata_value(row, "payment_id"),
        "line_items_count": line_items_count if type(line_items_count) is int else 0,
        "line_items_source": _metadata_value(row, "line_items_source") or "local",
        "line_items_state": _metadata_value(row, "line_items_state") or "not_linked",
        "invoice_state": _metadata_value(row, "invoice_state") or "not_linked",
        "invoice_attached": bool(_metadata_value(row, "invoice_attached")),
        "retry_after_seconds": 0,
    }


async def _completed_receipt_for_key(
    db: AsyncSession, *, idempotency_key: str, payment_id: str
) -> AdminAuditLog | None:
    """Return a completed send for this key, or reject unsafe reuse.

    The append-only audit log is the durable idempotency store. A key is bound
    to one payment for its lifetime; a recent ``started`` row without a terminal
    row is treated as in flight so a crash or Redis outage cannot immediately
    turn into a second email.
    """
    rows = list(
        (
            await db.execute(
                select(AdminAuditLog)
                .where(
                    AdminAuditLog.target_type == "user",
                    AdminAuditLog.action.in_(
                        [
                            f"{_RECEIPT_ACTION}.started",
                            f"{_RECEIPT_ACTION}.completed",
                            f"{_RECEIPT_ACTION}.failed",
                        ]
                    ),
                    AdminAuditLog.event_metadata["idempotency_key"].astext
                    == idempotency_key,
                )
                .order_by(AdminAuditLog.created_at.desc(), AdminAuditLog.id.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return None
    for row in rows:
        stored_payment_id = _metadata_value(row, "payment_id")
        if stored_payment_id is not None and str(stored_payment_id) != str(payment_id):
            raise SupportActionConflict(
                "This idempotency key was already used for another receipt"
            )
    completed = next(
        (row for row in rows if row.action == f"{_RECEIPT_ACTION}.completed"),
        None,
    )
    if completed is not None:
        return completed
    latest = rows[0]
    if (
        latest.action == f"{_RECEIPT_ACTION}.started"
        and _seconds_since(latest.created_at) < _RECEIPT_IN_PROGRESS_SECONDS
    ):
        raise SupportActionConflict(
            "A receipt send with this idempotency key is already in progress"
        )
    return None


_RECEIPT_LOCK_RELEASE_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


async def _acquire_receipt_lock(idempotency_key: str) -> tuple[bool, str | None]:
    """Best-effort Redis guard against concurrent duplicate sends.

    The audit log remains the durable duplicate check; Redis only shortens the
    race window. A cache outage fails open because blocking a support send on a
    cache incident is worse than the already-audited retry risk.
    """
    try:
        redis = await get_redis_client()
        token = secrets.token_urlsafe(18)
        acquired = await redis.set(
            f"latexy:admin:receipt-send:{idempotency_key}",
            token,
            nx=True,
            ex=_RECEIPT_IN_PROGRESS_SECONDS + 60,
        )
        return (True, token) if acquired else (False, None)
    except Exception as exc:
        logger.warning(
            "Receipt idempotency lock unavailable; relying on audit state",
            extra={"error_type": type(exc).__name__},
        )
        return True, None


async def _release_receipt_lock(idempotency_key: str, token: str | None) -> None:
    if not token:
        return
    try:
        redis = await get_redis_client()
        await redis.eval(
            _RECEIPT_LOCK_RELEASE_LUA,
            1,
            f"latexy:admin:receipt-send:{idempotency_key}",
            token,
        )
    except Exception as exc:
        logger.warning(
            "Receipt idempotency lock release failed",
            extra={"error_type": type(exc).__name__},
        )


async def _user_for_action(db: AsyncSession, user_id: str) -> User:
    canonical = _canonical_uuid(user_id)
    user = await db.get(User, canonical) if canonical else None
    if user is None:
        raise KeyError("User not found")
    if not user.email:
        raise SupportActionNotEligible("The target account has no email address")
    return user


def _frontend_base() -> str:
    base = (settings.FRONTEND_URL or "").strip().rstrip("/")
    if not base:
        raise SupportActionUnavailable("The application URL is not configured")
    return base


def _auth_secret() -> str:
    secret = (settings.BETTER_AUTH_SECRET or "").strip()
    if not secret:
        raise SupportActionUnavailable("The authentication secret is not configured")
    return secret


def _verification_link(user: User) -> str:
    """Create a Better Auth-compatible, short-lived verification JWT.

    Better Auth's ``GET /api/auth/verify-email`` verifies this HS256 JWT with
    the shared auth secret and only reads the ``email`` claim. The token is
    returned only inside the email body and is never persisted or logged.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "email": user.email.strip().lower(),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=_VERIFICATION_TOKEN_TTL_SECONDS)).timestamp()),
    }
    token = jwt.encode(payload, _auth_secret(), algorithm="HS256")
    callback = quote("/verify-email?verified=1", safe="")
    return f"{_frontend_base()}/api/auth/verify-email?token={quote(token, safe='')}&callbackURL={callback}"


async def _issue_password_reset_token(db: AsyncSession, user: User) -> tuple[str, str]:
    """Invalidate older admin reset links, then issue one Better Auth token.

    Better Auth stores reset tokens in ``verification`` as
    ``identifier = reset-password:<token>`` and ``value = user_id``. Writing
    that row directly is the only way to reuse the existing reset page without
    exposing the token through an internal HTTP hop.
    """
    base = _frontend_base()
    token = secrets.token_hex(12)
    verification_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=_PASSWORD_RESET_TOKEN_TTL_SECONDS)
    # A new support-issued reset supersedes older outstanding reset links for
    # this account. Only reset rows are touched; OAuth state is left alone.
    await db.execute(
        text("DELETE FROM verification WHERE value = :uid AND identifier LIKE 'reset-password:%'"),
        {"uid": user.id},
    )
    await db.execute(
        text(
            'INSERT INTO verification (id, identifier, value, "expiresAt", '
            '"createdAt", "updatedAt") '
            "VALUES (:id, :identifier, :value, :expires_at, :now, :now)"
        ),
        {
            "id": verification_id,
            "identifier": f"reset-password:{token}",
            "value": user.id,
            "expires_at": expires_at,
            "now": now,
        },
    )
    await db.commit()
    callback = quote("/reset-password", safe="")
    link = f"{base}/api/auth/reset-password/{token}?callbackURL={callback}"
    return verification_id, link


def _support_action_key(action: str, actor_user_id: str, target_key: str) -> str:
    return f"latexy:admin:support:{action}:{actor_user_id}:{target_key}"


async def _consume_support_action_budget(
    *,
    action: str,
    actor_user_id: str,
    target_key: str,
) -> int:
    """Fixed-window cooldown scoped to one actor and one target.

    Redis is only a counter. A cache outage fails open (and logs metadata only)
    so a cache incident cannot block a legitimate support escalation; the
    append-only audit log still records every attempt that proceeds.
    """
    window = SUPPORT_ACTION_WINDOWS[action]
    key = _support_action_key(action, actor_user_id, target_key)
    try:
        redis = await get_redis_client()
        result = await redis.eval(_SUPPORT_ACTION_LUA, 1, key, window)
        count, ttl = int(result[0]), int(result[1])
    except Exception as exc:  # Redis outage: fail open, no PII in the log.
        logger.warning(
            "Support action cooldown unavailable; failing open",
            extra={"error_type": type(exc).__name__, "action": action},
        )
        return window
    if count > 1:
        raise SupportActionCooldown(ttl or window)
    return window


async def _release_support_action_budget(
    *, action: str, actor_user_id: str, target_key: str
) -> None:
    """Undo a cooldown reservation when no email was handed to the provider.

    This keeps a provider outage or rejection from poisoning the window while
    still bounding successful sends. Failures here are best-effort.
    """
    try:
        redis = await get_redis_client()
        await redis.delete(_support_action_key(action, actor_user_id, target_key))
    except Exception as exc:
        logger.warning(
            "Support action cooldown release failed",
            extra={"error_type": type(exc).__name__, "action": action},
        )


async def _audit_result(
    db: AsyncSession,
    *,
    actor: AdminActor,
    action: str,
    target_id: str,
    reason: str,
    operation_id: str,
    outcome: str,
    metadata: Mapping[str, Any] | None = None,
    request=None,
) -> None:
    payload = {
        "operation_id": operation_id,
        "result": outcome,
        **(dict(metadata or {})),
    }
    await record_admin_audit(
        db,
        actor=actor,
        action=action,
        target_type="user",
        target_id=target_id,
        reason=reason,
        before={"sent": False},
        after={"sent": outcome == "accepted", "result": outcome},
        metadata=payload,
        request=request,
        commit=True,
    )


async def _begin_audit(
    db: AsyncSession,
    *,
    actor: AdminActor,
    action: str,
    target_id: str,
    reason: str,
    metadata: Mapping[str, Any] | None = None,
    request=None,
):
    payload = {"result": "started", **(dict(metadata or {}))}
    return await record_admin_audit(
        db,
        actor=actor,
        action=f"{action}.started",
        target_type="user",
        target_id=target_id,
        reason=reason,
        before={"sent": False},
        after={"sent": False, "result": "started"},
        metadata=payload,
        request=request,
        commit=True,
    )


async def _send_or_fail(
    db: AsyncSession,
    *,
    actor: AdminActor,
    action: str,
    target_id: str,
    reason: str,
    intent,
    to: str,
    subject: str,
    html_body: str,
    text_body: str,
    request=None,
    extra_result: Mapping[str, Any] | None = None,
    idempotency_key: str | None = None,
    attachments: Sequence[EmailAttachment] = (),
) -> EmailSendResult:
    try:
        result = await email_service.send_email_with_receipt(
            to=to,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            idempotency_key=idempotency_key or f"admin-support-{intent.id}",
            attachments=attachments,
        )
    except Exception as exc:
        logger.error(
            "Support email send failed",
            extra={"error_type": type(exc).__name__, "action": action},
        )
        await _audit_result(
            db,
            actor=actor,
            action=f"{action}.failed",
            target_id=target_id,
            reason=reason,
            operation_id=str(intent.id),
            outcome="provider_error",
            metadata={"retryable": True, **(dict(extra_result or {}))},
            request=request,
        )
        raise SupportActionProviderError(
            "The email provider could not be reached; nothing was delivered.",
            status_code=503,
            retryable=True,
        ) from None
    if not result.accepted:
        await _audit_result(
            db,
            actor=actor,
            action=f"{action}.failed",
            target_id=target_id,
            reason=reason,
            operation_id=str(intent.id),
            outcome="provider_error",
            metadata={
                "retryable": bool(result.transient),
                "provider_status": result.status_code,
                **(dict(extra_result or {})),
            },
            request=request,
        )
        raise SupportActionProviderError(
            "The email provider did not accept the message; nothing was delivered.",
            status_code=503 if result.transient else 502,
            retryable=bool(result.transient),
        )
    await _audit_result(
        db,
        actor=actor,
        action=f"{action}.completed",
        target_id=target_id,
        reason=reason,
        operation_id=str(intent.id),
        outcome="accepted",
        metadata={
            "provider_status": result.status_code,
            **(dict(extra_result or {})),
        },
        request=request,
    )
    return result


async def resend_verification_email(
    db: AsyncSession,
    *,
    user_id: str,
    actor: AdminActor,
    reason: str,
    request=None,
) -> dict[str, Any]:
    """Send a fresh verification link to an existing, unverified account."""
    cleaned_reason = _clean_reason(reason)
    user = await _user_for_action(db, user_id)
    if bool(user.email_verified):
        raise SupportActionNotEligible("The target email is already verified")

    retry_after = await _consume_support_action_budget(
        action="verification_email",
        actor_user_id=actor.user_id,
        target_key=user.id,
    )
    intent = await _begin_audit(
        db,
        actor=actor,
        action="user.verification_email.send",
        target_id=user.id,
        reason=cleaned_reason,
        metadata={"channel": "email"},
        request=request,
    )
    try:
        link = _verification_link(user)
    except SupportActionUnavailable as exc:
        await _audit_result(
            db,
            actor=actor,
            action="user.verification_email.send.failed",
            target_id=user.id,
            reason=cleaned_reason,
            operation_id=str(intent.id),
            outcome="unconfigured",
            metadata={"retryable": False},
            request=request,
        )
        raise exc from None

    html_body, text_body = render_account_verification_email(user.name, link)
    await _send_or_fail(
        db,
        actor=actor,
        action="user.verification_email.send",
        target_id=user.id,
        reason=cleaned_reason,
        intent=intent,
        to=user.email,
        subject="Verify your Latexy email",
        html_body=html_body,
        text_body=text_body,
        request=request,
    )
    await invalidate_user_360_cache(user.id)
    return {
        "action": "verification_email",
        "status": "sent",
        "delivery": "accepted",
        "target_user_id": user.id,
        "retry_after_seconds": retry_after,
    }


async def send_password_reset_email(
    db: AsyncSession,
    *,
    user_id: str,
    actor: AdminActor,
    reason: str,
    request=None,
) -> dict[str, Any]:
    """Send a Better Auth reset link to an account with a password credential."""
    cleaned_reason = _clean_reason(reason)
    user = await _user_for_action(db, user_id)
    has_credential = (
        await db.execute(
            text('SELECT 1 FROM account WHERE "userId" = :uid AND "providerId" = \'credential\' LIMIT 1'),
            {"uid": user.id},
        )
    ).first()
    if has_credential is None:
        raise SupportActionNotEligible("The target account does not use a password sign-in")

    retry_after = await _consume_support_action_budget(
        action="password_reset",
        actor_user_id=actor.user_id,
        target_key=user.id,
    )
    intent = await _begin_audit(
        db,
        actor=actor,
        action="user.password_reset.send",
        target_id=user.id,
        reason=cleaned_reason,
        metadata={"channel": "email"},
        request=request,
    )
    try:
        verification_id, link = await _issue_password_reset_token(db, user)
    except SupportActionUnavailable as exc:
        await _audit_result(
            db,
            actor=actor,
            action="user.password_reset.send.failed",
            target_id=user.id,
            reason=cleaned_reason,
            operation_id=str(intent.id),
            outcome="unconfigured",
            metadata={"retryable": False},
            request=request,
        )
        raise exc from None

    html_body, text_body = render_account_password_reset_email(link)
    try:
        await _send_or_fail(
            db,
            actor=actor,
            action="user.password_reset.send",
            target_id=user.id,
            reason=cleaned_reason,
            intent=intent,
            to=user.email,
            subject="Reset your Latexy password",
            html_body=html_body,
            text_body=text_body,
            request=request,
        )
    except Exception:
        # A reset link that never left the server must not stay valid.
        await db.execute(text("DELETE FROM verification WHERE id = :id"), {"id": verification_id})
        await db.commit()
        raise
    await invalidate_user_360_cache(user.id)
    return {
        "action": "password_reset",
        "status": "sent",
        "delivery": "accepted",
        "target_user_id": user.id,
        "retry_after_seconds": retry_after,
    }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _bounded_text(value: Any, *, limit: int = 200) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned[:limit] or None


def _bounded_int(value: Any) -> int | None:
    return value if type(value) is int else None


def _line_item_payloads(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]
    if isinstance(payload, Mapping):
        for key in ("items", "line_items", "data"):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, Mapping)]
    return []


def _normalize_line_items(payload: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in _line_item_payloads(payload)[:50]:
        description = _bounded_text(item.get("description") or item.get("product_name") or item.get("name"))
        quantity = _bounded_int(item.get("quantity"))
        amount = _bounded_int(item.get("amount"))
        if amount is None:
            amount = _bounded_int(item.get("total_amount"))
        if amount is None:
            amount = _bounded_int(item.get("price"))
        currency = _bounded_text(item.get("currency"), limit=8)
        normalized.append(
            {
                "description": description or "Line item",
                "quantity": quantity if quantity is not None and quantity >= 0 else 1,
                "amount_minor": amount,
                "currency": currency.upper() if currency else None,
            }
        )
    return normalized


async def _provider_line_items(payment: Payment) -> tuple[list[dict[str, Any]], str]:
    """Return normalized line items and an honest source state.

    A provider that does not expose line items for a payment, or has no
    credential configured, is not the same as a provider failure. In those
    cases the caller may still send a receipt backed by the local ledger and
    must label it as such. Transport/5xx failures are surfaced instead of
    silently downgrading.
    """
    if payment.provider != "dodo":
        return [], "not_linked"
    if not payment.provider_payment_id:
        return [], "not_linked"
    provider = payment_service.provider
    if not getattr(provider, "available", False):
        return [], "unconfigured"
    try:
        payload = await provider.get_payment_line_items(payment.provider_payment_id)
    except DodoAPIError as exc:
        if exc.status_code == 404:
            return [], "not_exposed"
        logger.warning(
            "Payment receipt line-item lookup failed",
            extra={"status": exc.status_code, "code": exc.code},
        )
        raise SupportActionProviderError(
            "The payment provider could not provide this receipt; nothing was sent.",
            status_code=503 if exc.status_code >= 500 else 502,
            retryable=exc.status_code >= 500,
        ) from None
    except Exception as exc:
        logger.error(
            "Payment receipt line-item lookup failed",
            extra={"error_type": type(exc).__name__},
        )
        raise SupportActionProviderError(
            "The payment provider could not provide this receipt; nothing was sent.",
            status_code=502,
            retryable=False,
        ) from None
    items = _normalize_line_items(payload)
    return items, "available" if items else "not_exposed"


async def _provider_invoice(payment: Payment) -> tuple[bytes | None, str]:
    """Fetch a bounded provider invoice PDF, or report an honest absence.

    A missing invoice (404) is distinct from a transport/5xx failure. The
    former can fall back to a ledger-only receipt; the latter must fail
    visibly rather than silently attach nothing or claim an invoice was sent.
    """
    if payment.provider != "dodo":
        return None, "not_linked"
    if not payment.provider_payment_id:
        return None, "not_linked"
    provider = payment_service.provider
    if not getattr(provider, "available", False):
        return None, "unconfigured"
    fetch_invoice = getattr(provider, "get_payment_invoice", None)
    if not callable(fetch_invoice):
        return None, "not_exposed"
    try:
        content = await fetch_invoice(payment.provider_payment_id)
    except DodoAPIError as exc:
        if exc.status_code == 404:
            return None, "not_exposed"
        logger.warning(
            "Payment receipt invoice lookup failed",
            extra={"status": exc.status_code, "code": exc.code},
        )
        raise SupportActionProviderError(
            "The payment provider could not provide this invoice; nothing was sent.",
            status_code=503 if exc.status_code >= 500 else 502,
            retryable=exc.status_code >= 500,
        ) from None
    except Exception as exc:
        logger.error(
            "Payment receipt invoice lookup failed",
            extra={"error_type": type(exc).__name__},
        )
        raise SupportActionProviderError(
            "The payment provider could not provide this invoice; nothing was sent.",
            status_code=502,
            retryable=False,
        ) from None
    if (
        not isinstance(content, (bytes, bytearray))
        or not content
        or not bytes(content).startswith(b"%PDF-")
        or len(content) > _MAX_INVOICE_ATTACHMENT_BYTES
    ):
        logger.warning("Payment receipt invoice payload was rejected")
        raise SupportActionProviderError(
            "The payment provider returned an unreadable invoice; nothing was sent.",
            status_code=502,
            retryable=False,
        )
    return bytes(content), "available"


async def _payment_for_target(db: AsyncSession, *, user_id: str, payment_id: str) -> Payment:
    canonical = _canonical_uuid(payment_id)
    payment = await db.get(Payment, canonical) if canonical else None
    if payment is None and payment_id:
        payment = (
            await db.execute(
                select(Payment)
                .where(
                    Payment.user_id == user_id,
                    Payment.provider_payment_id == payment_id,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
    if payment is None or str(payment.user_id) != str(user_id):
        raise KeyError("Payment not found")
    return payment


def _receipt_search_item(payment: Payment) -> dict[str, Any]:
    """Expose only ledger identifiers needed to choose a receipt."""
    settled = payment.status in _RECEIPT_SETTLED_STATUSES
    return {
        "payment_id": payment.id,
        "user_id": payment.user_id,
        "provider": payment.provider,
        "provider_payment_id": payment.provider_payment_id,
        "subscription_id": payment.subscription_id,
        "amount_minor": int(payment.amount or 0),
        "currency": (payment.currency or "").upper() or None,
        "status": payment.status,
        "payment_method": _bounded_text(payment.payment_method, limit=50),
        "created_at": _iso(payment.created_at),
        "settled": settled,
        "receipt_eligible": settled,
        "provider_linked": payment.provider == "dodo" and bool(payment.provider_payment_id),
    }


async def _limited_payments(
    db: AsyncSession, stmt, *, limit: int
) -> tuple[list[Payment], bool]:
    rows = list((await db.execute(stmt.limit(limit + 1))).scalars().all())
    return rows[:limit], len(rows) > limit


async def search_receipts(
    db: AsyncSession,
    *,
    payment_id: str | None = None,
    subscription_id: str | None = None,
    user_id: str | None = None,
    email_hash: str | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Find receipt-eligible payments by one exact, privacy-safe selector.

    Email is accepted only as the same one-way digest used by email health, so
    the request never carries an address. Responses contain ledger identifiers
    and money metadata only: no email, name, card fields or provider payload.
    """
    bounded_limit = max(1, min(int(limit), 50))
    selectors = [
        value.strip()
        for value in (payment_id, subscription_id, user_id, email_hash)
        if isinstance(value, str) and value.strip()
    ]
    if len(selectors) != 1:
        raise ValueError(
            "Provide exactly one of payment_id, subscription_id, user_id or email_hash"
        )

    payments: list[Payment] = []
    truncated = False
    if payment_id and payment_id.strip():
        raw = payment_id.strip()
        canonical = _canonical_uuid(raw)
        match_type = "payment_id"
        if canonical:
            payment = await db.get(Payment, canonical)
            payments = [payment] if payment is not None else []
        else:
            payments, truncated = await _limited_payments(
                db,
                select(Payment)
                .where(Payment.provider_payment_id == raw)
                .order_by(Payment.created_at.desc()),
                limit=bounded_limit,
            )
    elif subscription_id and subscription_id.strip():
        raw = subscription_id.strip()
        canonical = _canonical_uuid(raw)
        match_type = "subscription_id"
        subscription = await db.get(Subscription, canonical) if canonical else None
        if subscription is None:
            subscription = (
                await db.execute(
                    select(Subscription)
                    .where(
                        (Subscription.provider_subscription_id == raw)
                        | (Subscription.provider_checkout_session_id == raw)
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
        if subscription is not None:
            payments, truncated = await _limited_payments(
                db,
                select(Payment)
                .where(Payment.subscription_id == subscription.id)
                .order_by(Payment.created_at.desc()),
                limit=bounded_limit,
            )
    elif user_id and user_id.strip():
        canonical = _canonical_uuid(user_id.strip())
        if canonical is None:
            raise ValueError("user_id must be a UUID")
        match_type = "user_id"
        user = await db.get(User, canonical)
        if user is not None:
            payments, truncated = await _limited_payments(
                db,
                select(Payment)
                .where(Payment.user_id == user.id)
                .order_by(Payment.created_at.desc()),
                limit=bounded_limit,
            )
    else:
        raw = (email_hash or "").strip().lower()
        if re.fullmatch(r"[0-9a-f]{64}", raw) is None:
            raise ValueError("email_hash must be a 64-character SHA-256 hex digest")
        match_type = "email_hash"
        rows = (
            await db.execute(
                text(
                    "SELECT id FROM users WHERE email IS NOT NULL AND "
                    "encode(sha256(convert_to(btrim(lower(email)), 'UTF8')), 'hex') = :digest "
                    "LIMIT 20"
                ),
                {"digest": raw},
            )
        ).all()
        matched_ids = [row[0] for row in rows]
        if matched_ids:
            payments, truncated = await _limited_payments(
                db,
                select(Payment)
                .where(Payment.user_id.in_(matched_ids))
                .order_by(Payment.created_at.desc()),
                limit=bounded_limit,
            )

    return {
        "match_type": match_type,
        "items": [_receipt_search_item(payment) for payment in payments],
        "total": len(payments),
        "limit": bounded_limit,
        "truncated": truncated,
    }


async def get_payment_receipt(
    db: AsyncSession,
    *,
    user_id: str,
    payment_id: str,
) -> dict[str, Any]:
    """Admin-only receipt lookup. No customer identity or provider secret."""
    user = await _user_for_action(db, user_id)
    payment = await _payment_for_target(db, user_id=user.id, payment_id=payment_id)
    if payment.status not in _RECEIPT_SETTLED_STATUSES:
        raise SupportActionNotEligible("Only settled payments have a receipt")
    invoice_pdf, invoice_state = await _provider_invoice(payment)
    line_items, state = await _provider_line_items(payment)
    return {
        "payment_id": payment.id,
        "user_id": payment.user_id,
        "provider_payment_id": payment.provider_payment_id,
        "amount_minor": int(payment.amount),
        "currency": (payment.currency or "").upper() or None,
        "status": payment.status,
        "paid_at": _iso(payment.created_at),
        "line_items": line_items,
        "line_items_available": bool(line_items),
        "line_items_state": state,
        "line_items_source": "provider" if line_items else "local",
        "invoice_available": invoice_pdf is not None,
        "invoice_state": invoice_state,
        "invoice_size_bytes": len(invoice_pdf) if invoice_pdf else None,
    }


async def resend_payment_receipt(
    db: AsyncSession,
    *,
    user_id: str,
    payment_id: str,
    actor: AdminActor,
    reason: str,
    request=None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Send a receipt for one settled payment owned by the target account.

    ``idempotency_key`` is optional for older callers; when omitted a unique key
    is minted and still persisted. A repeated key returns the completed send
    from the append-only audit log instead of delivering a second email. The
    provider also receives a stable idempotency header derived from this key.
    """
    cleaned_reason = _clean_reason(reason)
    key = _normalize_idempotency_key(idempotency_key)
    user = await _user_for_action(db, user_id)
    payment = await _payment_for_target(db, user_id=user.id, payment_id=payment_id)
    if payment.status not in _RECEIPT_SETTLED_STATUSES:
        raise SupportActionNotEligible("Only settled payments have a receipt")

    replay = await _completed_receipt_for_key(
        db, idempotency_key=key, payment_id=payment.id
    )
    if replay is not None:
        return _receipt_replay_response(replay, key)

    acquired, lock_token = await _acquire_receipt_lock(key)
    if not acquired:
        raise SupportActionConflict(
            "A receipt send with this idempotency key is already in progress"
        )
    try:
        # Recheck under the lock so two concurrent requests cannot both pass
        # the audit-state check and send.
        replay = await _completed_receipt_for_key(
            db, idempotency_key=key, payment_id=payment.id
        )
        if replay is not None:
            return _receipt_replay_response(replay, key)

        retry_after = await _consume_support_action_budget(
            action="payment_receipt",
            actor_user_id=actor.user_id,
            target_key=f"{user.id}:{payment.id}",
        )
        audit_metadata = {
            "channel": "email",
            "payment_id": payment.id,
            "recipient_id": user.id,
            "recipient_digest": recipient_digest(user.email),
            "idempotency_key": key,
        }
        intent = await _begin_audit(
            db,
            actor=actor,
            action=_RECEIPT_ACTION,
            target_id=user.id,
            reason=cleaned_reason,
            metadata=audit_metadata,
            request=request,
        )
        try:
            invoice_pdf, invoice_state = await _provider_invoice(payment)
        except SupportActionProviderError as exc:
            await _audit_result(
                db,
                actor=actor,
                action=f"{_RECEIPT_ACTION}.failed",
                target_id=user.id,
                reason=cleaned_reason,
                operation_id=str(intent.id),
                outcome="provider_error",
                metadata={
                    **audit_metadata,
                    "retryable": exc.retryable,
                    "invoice_state": "provider_error",
                    "line_items_state": "not_checked",
                },
                request=request,
            )
            await _release_support_action_budget(
                action="payment_receipt",
                actor_user_id=actor.user_id,
                target_key=f"{user.id}:{payment.id}",
            )
            raise
        try:
            line_items, line_items_state = await _provider_line_items(payment)
        except SupportActionProviderError as exc:
            await _audit_result(
                db,
                actor=actor,
                action=f"{_RECEIPT_ACTION}.failed",
                target_id=user.id,
                reason=cleaned_reason,
                operation_id=str(intent.id),
                outcome="provider_error",
                metadata={
                    **audit_metadata,
                    "retryable": exc.retryable,
                    "invoice_state": invoice_state,
                    "line_items_state": "provider_error",
                },
                request=request,
            )
            await _release_support_action_budget(
                action="payment_receipt",
                actor_user_id=actor.user_id,
                target_key=f"{user.id}:{payment.id}",
            )
            raise

        attachments: tuple[EmailAttachment, ...] = ()
        if invoice_pdf is not None:
            attachments = (
                EmailAttachment(
                    filename=f"invoice-{payment.id[:8]}.pdf",
                    content=invoice_pdf,
                    content_type="application/pdf",
                ),
            )
        html_body, text_body = render_payment_receipt_email(
            user.name,
            payment_reference=payment.id,
            amount_minor=int(payment.amount),
            currency=(payment.currency or "").upper(),
            paid_at=payment.created_at,
            line_items=line_items,
            line_items_state=line_items_state,
            invoice_attached=invoice_pdf is not None,
        )
        try:
            await _send_or_fail(
                db,
                actor=actor,
                action=_RECEIPT_ACTION,
                target_id=user.id,
                reason=cleaned_reason,
                intent=intent,
                to=user.email,
                subject="Your Latexy payment receipt",
                html_body=html_body,
                text_body=text_body,
                request=request,
                idempotency_key=f"admin-receipt-{key}",
                attachments=attachments,
                extra_result={
                    **audit_metadata,
                    "payment_id": payment.id,
                    "line_items_count": len(line_items),
                    "line_items_source": "provider" if line_items else "local",
                    "line_items_state": line_items_state,
                    "invoice_state": invoice_state,
                    "invoice_attached": invoice_pdf is not None,
                },
            )
        except Exception:
            # A failed handoff sent nothing, so release the actor+target window
            # and let the same idempotency key be retried immediately. The
            # provider still receives a stable key for ambiguous timeouts.
            await _release_support_action_budget(
                action="payment_receipt",
                actor_user_id=actor.user_id,
                target_key=f"{user.id}:{payment.id}",
            )
            raise
        await invalidate_user_360_cache(user.id)
        return {
            "action": "payment_receipt",
            "status": "sent",
            "delivery": "accepted",
            "duplicate": False,
            "idempotency_key": key,
            "target_user_id": user.id,
            "payment_id": payment.id,
            "line_items_count": len(line_items),
            "line_items_source": "provider" if line_items else "local",
            "line_items_state": line_items_state,
            "invoice_state": invoice_state,
            "invoice_attached": invoice_pdf is not None,
            "retry_after_seconds": retry_after,
        }
    finally:
        await _release_receipt_lock(key, lock_token)
