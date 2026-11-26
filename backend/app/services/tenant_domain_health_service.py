"""Tenant-scoped custom-domain verification history and health.

The tenant row keeps only the latest verification timestamp, which is cleared
when a hostname is removed or replaced. This service records an allowlisted
event for every verification attempt so the tenant's owner/admin can still see
what happened afterwards.

Stored data is deliberately narrow: tenant UUID, tenant-owned hostname,
event type (``verified``, ``failed``, ``error``, ``removed``), an optional
allowlisted error class and the check timestamp. TXT record values, DNS answer
payloads, certificate material, user identifiers and emails are never stored or
returned here.

Health reads are scoped to one tenant by the caller. The probe is read-only: it
never renews DNS, changes TLS material, grants access, removes a domain or
mutates verification state.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import models

EVENT_VERIFIED = "verified"
EVENT_FAILED = "failed"
EVENT_ERROR = "error"
EVENT_REMOVED = "removed"

EVENT_TYPES = frozenset({EVENT_VERIFIED, EVENT_FAILED, EVENT_ERROR, EVENT_REMOVED})
CHECK_EVENT_TYPES = frozenset({EVENT_VERIFIED, EVENT_FAILED, EVENT_ERROR})
ERROR_CLASSES = frozenset({"txt_missing", "dns_unavailable"})

VERIFICATION_STALE_AFTER = timedelta(days=30)
EXPIRY_WARNING_WINDOW = timedelta(days=30)
HISTORY_LIMIT = 20

STATUS_NOT_CONFIGURED = "not_configured"
STATUS_UNVERIFIED = "unverified"
STATUS_HEALTHY = "healthy"
STATUS_STALE = "stale"
STATUS_UNHEALTHY = "unhealthy"


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _age_days(value: datetime | None, now: datetime) -> int | None:
    normalized = _as_utc(value)
    if normalized is None:
        return None
    return max(0, int((now - normalized).total_seconds() // 86400))


def _days_until(value: datetime | None, now: datetime) -> int | None:
    normalized = _as_utc(value)
    if normalized is None:
        return None
    return math.ceil((normalized - now).total_seconds() / 86400)


def _expiry_state(value: datetime | None, now: datetime) -> str:
    normalized = _as_utc(value)
    if normalized is None:
        return "unknown"
    if normalized <= now:
        return "expired"
    if normalized <= now + EXPIRY_WARNING_WINDOW:
        return "expiring"
    return "valid"


def _normalize_domain(value: object) -> str:
    return str(value or "").strip().lower().rstrip(".")[:253]


def record_domain_event(
    db: AsyncSession,
    *,
    tenant_id: str,
    domain: str,
    event_type: str,
    error_class: str | None = None,
    checked_at: datetime | None = None,
) -> models.TenantDomainEvent:
    """Stage one allowlisted event on the caller's transaction.

    The caller owns the commit so a domain-state change and its history entry
    are atomic. Every verification attempt gets a row; the table is not a
    latest-state snapshot.
    """

    normalized_domain = _normalize_domain(domain)
    if not normalized_domain:
        raise ValueError("Domain event requires a tenant-owned hostname")
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Unsupported tenant domain event type: {event_type}")
    if error_class is not None and error_class not in ERROR_CLASSES:
        raise ValueError(f"Unsupported tenant domain error class: {error_class}")

    event = models.TenantDomainEvent(
        tenant_id=tenant_id,
        domain=normalized_domain,
        event_type=event_type,
        error_class=error_class,
        checked_at=_as_utc(checked_at) or datetime.now(timezone.utc),
    )
    db.add(event)
    return event


def _domain_events(events: Iterable[models.TenantDomainEvent], domain: str) -> list[models.TenantDomainEvent]:
    normalized = _normalize_domain(domain)
    return [event for event in events if _normalize_domain(getattr(event, "domain", "")) == normalized]


def _history_entry(event: models.TenantDomainEvent) -> dict[str, Any]:
    return {
        "id": str(event.id),
        "domain": event.domain,
        "event_type": event.event_type,
        "error_class": event.error_class,
        "checked_at": _as_utc(event.checked_at),
    }


def _warning(
    code: str,
    severity: str,
    message: str,
    *,
    error_class: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "severity": severity, "message": message}
    if error_class:
        payload["error_class"] = error_class
    return payload


def domain_health_payload(
    tenant: models.Tenant,
    events: Sequence[models.TenantDomainEvent],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the owner/admin health response from tenant state plus history."""

    observed_at = _as_utc(now) or datetime.now(timezone.utc)
    ordered_events = sorted(
        events,
        key=lambda event: _as_utc(getattr(event, "checked_at", None)) or observed_at,
        reverse=True,
    )[:HISTORY_LIMIT]
    domain = _normalize_domain(getattr(tenant, "custom_domain", None))
    verified_at = _as_utc(getattr(tenant, "domain_verified_at", None))

    if domain:
        domain_events = _domain_events(ordered_events, domain)
        checks = [event for event in domain_events if event.event_type in CHECK_EVENT_TYPES]
        last_check = checks[0] if checks else None
        last_success = next(
            (event for event in domain_events if event.event_type == EVENT_VERIFIED),
            None,
        )
        last_checked_at = _as_utc(last_check.checked_at) if last_check else verified_at
        last_success_at = _as_utc(last_success.checked_at) if last_success else verified_at
    else:
        last_check = None
        last_success = None
        last_checked_at = None
        last_success_at = None

    warnings: list[dict[str, Any]] = []

    if not domain:
        status = STATUS_NOT_CONFIGURED
    elif last_check is not None and last_check.event_type in {EVENT_FAILED, EVENT_ERROR}:
        status = STATUS_UNHEALTHY if verified_at is not None else STATUS_UNVERIFIED
    elif verified_at is None:
        status = STATUS_UNVERIFIED
    elif last_success_at is not None and observed_at - last_success_at > VERIFICATION_STALE_AFTER:
        status = STATUS_STALE
    else:
        status = STATUS_HEALTHY

    if domain and status == STATUS_UNVERIFIED:
        error_class = getattr(last_check, "error_class", None) if last_check else None
        if error_class == "dns_unavailable":
            message = "The last DNS check could not be completed. Retry the check to confirm ownership."
        elif error_class == "txt_missing":
            message = "The DNS TXT record no longer resolves. Add it again and recheck to activate this domain."
        else:
            message = "This domain has not passed an ownership check yet."
        warnings.append(_warning("verification_unverified", "warning", message, error_class=error_class))
    elif domain and status == STATUS_UNHEALTHY:
        error_class = getattr(last_check, "error_class", None) if last_check else None
        message = (
            "The most recent DNS check failed. The earlier verification is still "
            "recorded; recheck to confirm DNS has not changed."
        )
        if error_class == "dns_unavailable":
            message = (
                "The most recent DNS check could not be completed. Ownership is "
                "still recorded from an earlier check; recheck when DNS is reachable."
            )
        warnings.append(_warning("verification_unhealthy", "warning", message, error_class=error_class))
    elif domain and status == STATUS_STALE:
        age_days = _age_days(last_success_at, observed_at)
        warnings.append(
            _warning(
                "verification_stale",
                "warning",
                f"No successful ownership check in {age_days or 0} days. Run a recheck to confirm DNS still resolves.",
            )
        )

    domain_expires_at = getattr(tenant, "domain_expires_at", None) if domain else None
    certificate_expires_at = getattr(tenant, "domain_certificate_expires_at", None) if domain else None
    domain_state = _expiry_state(domain_expires_at, observed_at)
    certificate_state = _expiry_state(certificate_expires_at, observed_at)

    if domain_state == "expired":
        warnings.append(
            _warning(
                "domain_expired",
                "critical",
                "The custom domain's registration expiry has passed.",
            )
        )
    elif domain_state == "expiring":
        warnings.append(
            _warning(
                "domain_expiring",
                "warning",
                "The custom domain registration expires within 30 days.",
            )
        )
    if certificate_state == "expired":
        warnings.append(
            _warning(
                "certificate_expired",
                "critical",
                "The custom domain certificate has expired.",
            )
        )
    elif certificate_state == "expiring":
        warnings.append(
            _warning(
                "certificate_expiring",
                "warning",
                "The custom domain certificate expires within 30 days.",
            )
        )

    return {
        "tenant_id": str(tenant.id),
        "domain": domain or None,
        "status": status,
        "verified": verified_at is not None,
        "verified_at": verified_at,
        "last_checked_at": last_checked_at,
        "last_success_at": last_success_at,
        "verification_age_days": (_age_days(last_success_at, observed_at) if domain and verified_at else None),
        "stale_after_days": int(VERIFICATION_STALE_AFTER.total_seconds() // 86400),
        "history": [_history_entry(event) for event in ordered_events],
        "warnings": warnings,
        "expiry": {
            "domain_expires_at": _as_utc(domain_expires_at),
            "certificate_expires_at": _as_utc(certificate_expires_at),
            "domain_state": domain_state,
            "certificate_state": certificate_state,
            "domain_days_until_expiry": _days_until(domain_expires_at, observed_at),
            "certificate_days_until_expiry": _days_until(certificate_expires_at, observed_at),
        },
        "generated_at": observed_at,
    }


async def load_domain_health(
    db: AsyncSession,
    tenant: models.Tenant,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Read recent tenant-scoped history and build the health payload."""

    result = await db.execute(
        select(models.TenantDomainEvent)
        .where(models.TenantDomainEvent.tenant_id == tenant.id)
        .order_by(models.TenantDomainEvent.checked_at.desc())
        .limit(HISTORY_LIMIT)
    )
    events = result.scalars().all()
    return domain_health_payload(tenant, events, now=now)
