"""Resend email delivery health, suppression and aggregate reporting.

The public webhook is verified with Resend's Svix signature scheme before any
payload is parsed. Ingested events are append-only and deduplicate on the signed
webhook id. A provider message id links an event back to the durable
``document_email_deliveries`` row that submitted it.

Privacy contract:
* no recipient address, subject, body, header or raw provider payload is stored;
* only a one-way recipient digest is kept, for local suppression checks;
* the admin response contains aggregates and bounded operational labels only;
* rates are withheld below five observed outcomes so a tiny sample cannot
  identify an individual worker action.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..database.models import (
    DocumentEmailDelivery,
    EmailDeliveryEvent,
    EmailRecipientSuppression,
)

PROVIDER = "resend"
SIGNATURE_TOLERANCE_SECONDS = 300
MIN_RATE_SAMPLE = 5
COMPLAINT_REVIEW_PCT = 0.1
BOUNCE_REVIEW_PCT = 5.0
MAX_RECENT_FAILURES = 20

KNOWN_EVENT_TYPES = frozenset(
    {
        "email.sent",
        "email.delivered",
        "email.delivery_delayed",
        "email.bounced",
        "email.complained",
        "email.failed",
        "email.suppressed",
        "suppression.added",
        "suppression.removed",
    }
)
FAILURE_EVENT_TYPES = (
    "email.bounced",
    "email.complained",
    "email.delivery_delayed",
    "email.failed",
    "email.suppressed",
)



class EmailWebhookError(ValueError):
    """A webhook that cannot be authenticated or safely normalized."""


def _normalized_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    return {str(key).lower(): str(value) for key, value in (headers or {}).items()}


def _first_header(headers: dict[str, str], *names: str) -> str:
    for name in names:
        value = headers.get(name)
        if value:
            return value
    return ""


def verify_resend_signature(
    payload: bytes,
    headers: Mapping[str, str] | None,
    secret: str | None = None,
) -> bool:
    """Verify a Resend/Svix webhook signature against the raw body.

    Resend documents the Svix ``svix-*`` headers. Standard-webhook ``webhook-*``
    aliases are accepted for provider-compatible relays. A missing secret always
    fails closed.
    """
    signing_secret = secret if secret is not None else settings.RESEND_WEBHOOK_SECRET
    normalized = _normalized_headers(headers)
    webhook_id = _first_header(normalized, "svix-id", "webhook-id")
    timestamp = _first_header(normalized, "svix-timestamp", "webhook-timestamp")
    signatures = _first_header(normalized, "svix-signature", "webhook-signature")
    if not signing_secret or not webhook_id or not timestamp or not signatures:
        return False
    try:
        signed_at = int(timestamp)
        if abs(time.time() - signed_at) > SIGNATURE_TOLERANCE_SECONDS:
            return False
        key_text = signing_secret.removeprefix("whsec_")
        candidate_keys: list[bytes] = []
        try:
            candidate_keys.append(
                base64.b64decode(key_text + "=" * (-len(key_text) % 4), validate=True)
            )
        except ValueError:
            pass
        # Also accept a raw operator secret for relays that do not use Svix's
        # base64-encoded secret format.
        raw_key = key_text.encode("utf-8")
        if raw_key not in candidate_keys:
            candidate_keys.append(raw_key)
        message = webhook_id.encode() + b"." + timestamp.encode() + b"." + payload
        for signing_key in candidate_keys:
            expected = base64.b64encode(
                hmac.new(signing_key, message, hashlib.sha256).digest()
            ).decode()
            if any(
                hmac.compare_digest(candidate.split(",", 1)[-1], expected)
                for candidate in signatures.split()
                if candidate.startswith("v1,")
            ):
                return True
        return False
    except (ValueError, TypeError):
        return False


def _safe_text(value: Any, limit: int) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    cleaned = "".join(
        char for char in text if char.isprintable() and char not in "\r\n\t"
    )
    return cleaned[:limit] or None


_SAFE_LABEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]*")


def _safe_label(value: Any, limit: int) -> Optional[str]:
    """Keep only short operational labels; never free-form diagnostics."""
    text = _safe_text(value, limit)
    if text is None or _SAFE_LABEL_RE.fullmatch(text) is None:
        return None
    return text[:limit]


def _parse_time(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def recipient_digest(email: str | None) -> Optional[str]:
    """Return a one-way, normalized recipient digest; never the address."""
    address = (email or "").strip().lower()
    if not address or "@" not in address or len(address) > 320:
        return None
    return hashlib.sha256(address.encode("utf-8")).hexdigest()


def _recipient_from_data(data: Mapping[str, Any]) -> Optional[str]:
    recipients = data.get("to")
    if isinstance(recipients, (list, tuple)):
        for candidate in recipients:
            if isinstance(candidate, str) and candidate.strip():
                return candidate
    email = data.get("email")
    return email if isinstance(email, str) else None


def _normalize_bounce_type(data: Mapping[str, Any]) -> Optional[str]:
    bounce = data.get("bounce")
    if not isinstance(bounce, Mapping):
        return None
    raw = _safe_text(bounce.get("type"), 32)
    if not raw:
        return None
    lowered = raw.lower()
    if lowered in {"permanent", "hard"}:
        return "permanent"
    if lowered in {"temporary", "transient", "soft"}:
        return "transient"
    if lowered == "undetermined":
        return "undetermined"
    return "unknown"


def _normalize_bounce_subtype(data: Mapping[str, Any]) -> Optional[str]:
    bounce = data.get("bounce")
    if not isinstance(bounce, Mapping):
        return None
    return _safe_label(bounce.get("subType") or bounce.get("subtype"), 64)


def _event_kind(raw_type: Any) -> str:
    event_type = _safe_text(raw_type, 64)
    if event_type in KNOWN_EVENT_TYPES:
        return event_type
    return "unknown"


def _is_retryable(event_type: str, bounce_type: str | None) -> bool:
    """Only temporary provider conditions are retryable.

    Hard bounces, complaints, suppressions, invalid payloads and permanent
    provider failures must never be retried. A delayed delivery or a temporary
    bounce is safe to classify as transient.
    """
    return event_type == "email.delivery_delayed" or (
        event_type == "email.bounced" and bounce_type == "transient"
    )


async def _mapped_delivery(
    db: AsyncSession, provider_message_id: str | None
) -> DocumentEmailDelivery | None:
    if not provider_message_id:
        return None
    result = await db.execute(
        select(DocumentEmailDelivery)
        .where(DocumentEmailDelivery.provider_message_id == provider_message_id)
        .order_by(DocumentEmailDelivery.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _suppression_reason(event_type: str, bounce_type: str | None, data: Mapping[str, Any]) -> str | None:
    if event_type == "email.complained":
        return "complaint"
    if event_type == "email.bounced" and bounce_type != "transient":
        return "bounce"
    if event_type == "email.suppressed":
        return "provider"
    if event_type == "suppression.added":
        origin = _safe_text(data.get("origin"), 32)
        if origin in {"bounce", "complaint", "manual"}:
            return origin
        return "provider"
    return None


async def _upsert_suppression(
    db: AsyncSession,
    *,
    recipient_hash: str,
    reason: str,
    source_event_id: str,
    delivery_id: str | None,
) -> None:
    now = datetime.now(timezone.utc)
    statement = (
        pg_insert(EmailRecipientSuppression)
        .values(
            id=str(uuid4()),
            provider=PROVIDER,
            recipient_hash=recipient_hash,
            reason=reason,
            source_event_id=source_event_id,
            delivery_id=delivery_id,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_update(
            constraint="uq_email_recipient_suppressions_provider_hash",
            set_={
                "reason": reason,
                "source_event_id": source_event_id,
                "delivery_id": delivery_id,
                "updated_at": now,
            },
        )
    )
    await db.execute(statement)


async def ingest_resend_event(
    db: AsyncSession,
    payload: bytes,
    headers: Mapping[str, str] | None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Verify, deduplicate and persist one signed Resend webhook event."""
    if not settings.RESEND_WEBHOOK_SECRET:
        raise EmailWebhookError("webhook_verification_unconfigured")
    if not verify_resend_signature(payload, headers):
        raise EmailWebhookError("invalid_signature")

    normalized_headers = _normalized_headers(headers)
    provider_event_id = _safe_text(
        _first_header(normalized_headers, "svix-id", "webhook-id"), 255
    )
    if not provider_event_id:
        raise EmailWebhookError("missing_event_id")

    existing = await db.execute(
        select(EmailDeliveryEvent.id).where(
            EmailDeliveryEvent.provider == PROVIDER,
            EmailDeliveryEvent.provider_event_id == provider_event_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        return {"status": "duplicate", "event_type": None}

    import json

    try:
        envelope = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise EmailWebhookError("invalid_json") from exc
    if not isinstance(envelope, dict):
        raise EmailWebhookError("invalid_envelope")

    data = envelope.get("data")
    if not isinstance(data, dict):
        data = {}
    event_type = _event_kind(envelope.get("type"))
    provider_message_id = _safe_text(
        data.get("email_id") or data.get("source_id"), 255
    )
    bounce_type = _normalize_bounce_type(data)
    bounce_subtype = _normalize_bounce_subtype(data)
    recipient_hash = recipient_digest(_recipient_from_data(data))
    occurred_at = (
        _parse_time(envelope.get("created_at"))
        or _parse_time(data.get("created_at"))
        or now
        or datetime.now(timezone.utc)
    )
    delivery = await _mapped_delivery(db, provider_message_id)

    event = EmailDeliveryEvent(
        id=str(uuid4()),
        provider=PROVIDER,
        provider_event_id=provider_event_id,
        event_type=event_type,
        provider_message_id=provider_message_id,
        delivery_id=str(delivery.id) if delivery is not None else None,
        recipient_hash=recipient_hash,
        bounce_type=bounce_type,
        bounce_subtype=bounce_subtype,
        retryable=_is_retryable(event_type, bounce_type),
        occurred_at=occurred_at,
        received_at=now or datetime.now(timezone.utc),
    )
    db.add(event)
    try:
        await db.flush()
    except IntegrityError:
        # The unique (provider, event id) constraint is the final idempotency
        # fence if another delivery won the race between our read and insert.
        await db.rollback()
        return {"status": "duplicate", "event_type": None}

    suppression_reason = _suppression_reason(event_type, bounce_type, data)
    if recipient_hash and event_type == "suppression.removed":
        await db.execute(
            delete(EmailRecipientSuppression).where(
                EmailRecipientSuppression.provider == PROVIDER,
                EmailRecipientSuppression.recipient_hash == recipient_hash,
            )
        )
    elif recipient_hash and suppression_reason:
        await _upsert_suppression(
            db,
            recipient_hash=recipient_hash,
            reason=suppression_reason,
            source_event_id=provider_event_id,
            delivery_id=str(delivery.id) if delivery is not None else None,
        )

    await db.commit()
    return {
        "status": "ignored" if event_type == "unknown" else "processed",
        "event_type": event_type,
        "delivery_mapped": delivery is not None,
    }


async def is_recipient_suppressed(
    db: AsyncSession, email: str | None, *, provider: str = PROVIDER
) -> bool:
    digest = recipient_digest(email)
    if not digest:
        return False
    result = await db.execute(
        select(EmailRecipientSuppression.id).where(
            EmailRecipientSuppression.provider == provider,
            EmailRecipientSuppression.recipient_hash == digest,
        )
    )
    return result.scalar_one_or_none() is not None


def _rate(numerator: int, denominator: int) -> Optional[float]:
    if denominator < MIN_RATE_SAMPLE or denominator <= 0:
        return None
    return round(numerator / denominator * 100.0, 2)


async def email_health(
    db: AsyncSession,
    *,
    days: int = 30,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return aggregate delivery health, recent failures and suppression state."""
    end = now or datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    event_at = func.coalesce(EmailDeliveryEvent.occurred_at, EmailDeliveryEvent.received_at)

    event_rows = (
        await db.execute(
            select(EmailDeliveryEvent.event_type, func.count(EmailDeliveryEvent.id))
            .where(event_at >= start)
            .group_by(EmailDeliveryEvent.event_type)
        )
    ).all()
    event_counts = {str(row[0]): int(row[1]) for row in event_rows}

    delivery_rows = (
        await db.execute(
            select(DocumentEmailDelivery.status, func.count(DocumentEmailDelivery.id))
            .where(DocumentEmailDelivery.created_at >= start)
            .group_by(DocumentEmailDelivery.status)
        )
    ).all()
    delivery_counts = {str(row[0]): int(row[1]) for row in delivery_rows}

    active_suppressions = int(
        (
            await db.execute(
                select(func.count(EmailRecipientSuppression.id))
            )
        ).scalar_one()
        or 0
    )
    added_in_period = int(
        (
            await db.execute(
                select(func.count(EmailRecipientSuppression.id)).where(
                    EmailRecipientSuppression.created_at >= start
                )
            )
        ).scalar_one()
        or 0
    )
    removed_in_period = int(
        (
            await db.execute(
                select(func.count(EmailDeliveryEvent.id)).where(
                    EmailDeliveryEvent.event_type == "suppression.removed",
                    event_at >= start,
                )
            )
        ).scalar_one()
        or 0
    )

    recent_rows = (
        await db.execute(
            select(
                EmailDeliveryEvent,
                DocumentEmailDelivery.status.label("delivery_status"),
            )
            .outerjoin(
                DocumentEmailDelivery,
                DocumentEmailDelivery.id == EmailDeliveryEvent.delivery_id,
            )
            .where(
                event_at >= start,
                EmailDeliveryEvent.event_type.in_(FAILURE_EVENT_TYPES),
            )
            .order_by(event_at.desc())
            .limit(MAX_RECENT_FAILURES)
        )
    ).all()
    recent_failures = []
    for event, delivery_status in recent_rows:
        recent_failures.append(
            {
                "event_type": event.event_type,
                "occurred_at": (
                    event.occurred_at.isoformat()
                    if event.occurred_at
                    else event.received_at.isoformat()
                ),
                "bounce_type": event.bounce_type,
                "bounce_subtype": event.bounce_subtype,
                "retryable": bool(event.retryable),
                "delivery_mapped": event.delivery_id is not None,
                "delivery_status": delivery_status,
            }
        )

    delivered = event_counts.get("email.delivered", 0)
    bounced = event_counts.get("email.bounced", 0)
    complained = event_counts.get("email.complained", 0)
    attempted = delivered + bounced + complained
    rates_withheld = attempted < MIN_RATE_SAMPLE
    bounce_rate = None if rates_withheld else _rate(bounced, attempted)
    complaint_rate = None if rates_withheld else _rate(complained, attempted)
    delivery_rate = None if rates_withheld else _rate(delivered, attempted)

    signature_configured = bool(settings.RESEND_WEBHOOK_SECRET)
    if not signature_configured:
        health_status = "unconfigured"
    elif (
        complaint_rate is not None and complaint_rate >= COMPLAINT_REVIEW_PCT
    ) or (bounce_rate is not None and bounce_rate >= BOUNCE_REVIEW_PCT):
        health_status = "review"
    elif bounced or complained or event_counts.get("email.failed", 0):
        health_status = "watch"
    else:
        health_status = "ok"

    suppression_status = "unconfigured" if not signature_configured else health_status
    notes = [
        "Recipient addresses are never stored or returned; suppression uses a one-way digest.",
        "Rates are withheld until at least five delivered/bounced/complaint outcomes exist.",
        "Hard bounces, complaints and provider suppressions block future document emails.",
        "Temporary bounces and delivery delays are retryable; permanent failures are not.",
    ]

    return {
        "provider": PROVIDER,
        "configured_provider": str(settings.EMAIL_PROVIDER or "unknown"),
        "period": {
            "days": days,
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
        "minimum_rate_sample": MIN_RATE_SAMPLE,
        "signature_verification": {
            "configured": signature_configured,
            "scheme": "svix",
            "tolerance_seconds": SIGNATURE_TOLERANCE_SECONDS,
        },
        "summary": {
            "outbound": {
                "total": sum(delivery_counts.values()),
                "accepted": delivery_counts.get("accepted", 0),
                "failed": delivery_counts.get("failed", 0),
                "pending": delivery_counts.get("pending", 0)
                + delivery_counts.get("processing", 0),
            },
            "events": {
                "sent": event_counts.get("email.sent", 0),
                "delivered": delivered,
                "bounced": bounced,
                "complained": complained,
                "delayed": event_counts.get("email.delivery_delayed", 0),
                "failed": event_counts.get("email.failed", 0),
                "suppressed": event_counts.get("email.suppressed", 0),
                "suppression_added": event_counts.get("suppression.added", 0),
                "suppression_removed": event_counts.get("suppression.removed", 0),
                "unknown": event_counts.get("unknown", 0),
            },
            "attempted": attempted,
            "bounce_rate_pct": bounce_rate,
            "complaint_rate_pct": complaint_rate,
            "delivery_rate_pct": delivery_rate,
            # Stable aliases for dashboards that already use the shorter names.
            "bounce_rate": bounce_rate,
            "complaint_rate": complaint_rate,
            "delivery_rate": delivery_rate,
            "rates_withheld": rates_withheld,
            "sample_size": attempted,
        },
        "event_types": [
            {"event_type": event_type, "count": count}
            for event_type, count in sorted(
                event_counts.items(), key=lambda item: (-item[1], item[0])
            )
        ],
        "recent_failures": recent_failures,
        "suppression": {
            "status": suppression_status,
            "active_recipients": active_suppressions,
            "added_in_period": added_in_period,
            "removed_in_period": removed_in_period,
            "provider_side_suppression": True,
            "local_enforcement": True,
            "review_thresholds": {
                "complaint_rate_pct": COMPLAINT_REVIEW_PCT,
                "bounce_rate_pct": BOUNCE_REVIEW_PCT,
            },
            "policy": (
                "Resend suppresses hard bounces and complaints on its side. "
                "Latexy also stores a one-way digest locally and refuses new "
                "document emails to suppressed recipients."
            ),
        },
        "notes": notes,
        "generated_at": end.isoformat(),
    }
