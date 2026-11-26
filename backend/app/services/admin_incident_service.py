"""Admin incident timeline: validation, CRUD and state transitions.

Incident text is operator-authored operational context, never a customer record.
Every free-form field is checked for obvious direct identifiers (email address,
phone number, national ID) and credential-shaped secrets before it can be
persisted. The same rule applies to links, so an operator cannot paste a
support inbox, a phone number or a token into the timeline by accident.

Every mutation records an append-only admin audit row in the same transaction as
the incident change. Deletes are allowed for control-plane hygiene but remain
audited with the complete before snapshot.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

import phonenumbers
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import models
from .admin_audit_service import AdminActor, record_admin_audit

SEVERITIES = ("critical", "high", "medium", "low")
STATUSES = ("open", "resolved")
ACTIVE_STATUS = "open"

MAX_TITLE = 200
MAX_SUMMARY = 4000
MAX_OWNER = 64
MAX_SERVICES = 20
MAX_LINKS = 20
MAX_LINK_LENGTH = 500
MAX_ALERT_KEYS = 20
MAX_ALERT_KEY_LENGTH = 120
MAX_DEPLOY_SHA = 40

_SERVICE_RE = re.compile(r"^[a-z][a-z0-9_.-]{1,39}$")
_ALERT_KEY_RE = re.compile(r"^[a-z][a-z0-9_.-]{1,119}$")
_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_SECRET_RE = re.compile(
    r"(?i)(?:bearer\s+[a-z0-9._\-]{12,}|sk_(?:live|test)_[a-z0-9]{8,}|"
    r"ghp_[a-z0-9]{20,}|github_pat_[a-z0-9_]{20,}|"
    r"xox[baprs]-[a-z0-9\-]{10,}|AKIA[0-9A-Z]{16}|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"api[_-]?key\s*[:=]\s*\S{8,}|password\s*[:=]\s*\S{4,}|"
    r"authorization\s*:\s*\S{8,})"
)
_DOCUMENT_RE = re.compile(
    r"\\(?:documentclass|begin\s*\{\s*(?:document|resume|coverletter)|section\s*\{)",
    re.IGNORECASE,
)
_PHONE_REGIONS = ("US", "IN", "GB")


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    normalized = _as_utc(value)
    return normalized.isoformat() if normalized else None


def _reject_pii(text: str, *, field: str) -> None:
    """Reject obvious direct identifiers without echoing the offending value."""
    if _EMAIL_RE.search(text) or _SSN_RE.search(text) or _SECRET_RE.search(text):
        raise ValueError(
            f"{field} must not contain customer PII, identifiers or credentials"
        )
    if _DOCUMENT_RE.search(text):
        raise ValueError(f"{field} must not contain document content")
    for region in _PHONE_REGIONS:
        for match in phonenumbers.PhoneNumberMatcher(text, region):
            if phonenumbers.is_valid_number(match.number):
                raise ValueError(f"{field} must not contain customer PII or phone numbers")


def _text(
    value: Any,
    *,
    field: str,
    max_length: int,
    required: bool = True,
) -> str:
    if value is None:
        if required:
            raise ValueError(f"{field} is required")
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    cleaned = " ".join(value.split())
    if required and not cleaned:
        raise ValueError(f"{field} is required")
    if len(cleaned) > max_length:
        raise ValueError(f"{field} must be at most {max_length} characters")
    _reject_pii(cleaned, field=field)
    return cleaned


def _services(values: Iterable[Any] | None) -> list[str]:
    if values is None:
        raise ValueError("services is required")
    normalized: list[str] = []
    for raw in values:
        if not isinstance(raw, str):
            raise ValueError("service names must be text")
        value = raw.strip().casefold()
        if not _SERVICE_RE.fullmatch(value):
            raise ValueError(
                "service names must be 2-40 lowercase letters, digits, '.', '_' or '-'"
            )
        if value not in normalized:
            normalized.append(value)
    if not normalized:
        raise ValueError("at least one affected service is required")
    if len(normalized) > MAX_SERVICES:
        raise ValueError(f"at most {MAX_SERVICES} services may be recorded")
    return normalized


def _link(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("links must contain text URLs")
    url = value.strip()
    if not url or len(url) > MAX_LINK_LENGTH:
        raise ValueError(f"links must be 1-{MAX_LINK_LENGTH} characters")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("links must be absolute http(s) URLs")
    if parsed.username or parsed.password:
        raise ValueError("links must not embed credentials")
    _reject_pii(url, field="links")
    return url


def _links(values: Iterable[Any] | None) -> list[str]:
    if values is None:
        return []
    normalized: list[str] = []
    for raw in values:
        url = _link(raw)
        if url not in normalized:
            normalized.append(url)
    if len(normalized) > MAX_LINKS:
        raise ValueError(f"at most {MAX_LINKS} links may be recorded")
    return normalized


def _alert_keys(values: Iterable[Any] | None) -> list[str]:
    if values is None:
        return []
    normalized: list[str] = []
    for raw in values:
        if not isinstance(raw, str):
            raise ValueError("related_alert_keys must contain text keys")
        key = raw.strip().casefold()
        if not _ALERT_KEY_RE.fullmatch(key) or len(key) > MAX_ALERT_KEY_LENGTH:
            raise ValueError("related_alert_keys contains an invalid alert key")
        if key not in normalized:
            normalized.append(key)
    if len(normalized) > MAX_ALERT_KEYS:
        raise ValueError(f"at most {MAX_ALERT_KEYS} related alerts may be recorded")
    return normalized


def _deploy_sha(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("deploy_sha must be text")
    sha = value.strip().casefold()
    if not sha:
        return None
    if not _SHA_RE.fullmatch(sha) or len(sha) > MAX_DEPLOY_SHA:
        raise ValueError("deploy_sha must be a 7-40 character hexadecimal commit SHA")
    return sha


def _deploy_url(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        return None
    return _link(value)


def _started_at(value: datetime | None, *, now: datetime) -> datetime:
    when = _as_utc(value) or now
    if when > now + timedelta(minutes=5):
        raise ValueError("started_at cannot be in the future")
    return when


def _ended_at(value: datetime | None, *, started_at: datetime, now: datetime) -> datetime:
    when = _as_utc(value) or now
    if when > now + timedelta(minutes=5):
        raise ValueError("ended_at cannot be in the future")
    if when < started_at:
        raise ValueError("ended_at must be at or after started_at")
    return when


def _severity(value: Any) -> str:
    severity = str(value or "").strip().casefold()
    if severity not in SEVERITIES:
        raise ValueError("severity must be one of critical, high, medium or low")
    return severity


def _status(value: Any, *, allow_active: bool = True) -> str:
    status = str(value or "").strip().casefold()
    if allow_active and status == "active":
        return ACTIVE_STATUS
    if status not in STATUSES:
        raise ValueError("status must be open, resolved or active")
    return status


def _incident_id(value: Any) -> str:
    return str(value)


async def _get(db: AsyncSession, incident_id: str, *, lock: bool = False) -> models.AdminIncident:
    statement = select(models.AdminIncident).where(models.AdminIncident.id == incident_id)
    if lock:
        statement = statement.with_for_update()
    row = (await db.execute(statement)).scalar_one_or_none()
    if row is None:
        raise KeyError("Incident not found")
    return row


def _related_alerts_map(rows: Iterable[models.AdminAlert]) -> dict[str, list[dict[str, Any]]]:
    mapping: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        mapping.setdefault(row.dedupe_key, []).append(
            {
                "id": row.id,
                "dedupe_key": row.dedupe_key,
                "kind": row.kind,
                "severity": row.severity,
                "owner": row.owner,
                "title": row.title,
                "state": row.state,
                "occurrence_count": row.occurrence_count,
                "last_seen_at": _iso(row.last_seen_at),
            }
        )
    return mapping


async def _related_alerts(
    db: AsyncSession, keys: Iterable[str]
) -> dict[str, list[dict[str, Any]]]:
    unique = sorted({key for key in keys if key})
    if not unique:
        return {}
    rows = (
        await db.execute(
            select(models.AdminAlert)
            .where(models.AdminAlert.dedupe_key.in_(unique))
            .order_by(models.AdminAlert.last_seen_at.desc())
        )
    ).scalars().all()
    return _related_alerts_map(rows)


def _payload(
    row: models.AdminIncident,
    *,
    related_alerts: Mapping[str, list[dict[str, Any]]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    started = _as_utc(row.started_at)
    ended = _as_utc(row.ended_at)
    end_for_duration = ended or now
    duration = max(0, int((end_for_duration - started).total_seconds())) if started else None
    alert_map = related_alerts or {}
    related_rows: list[dict[str, Any]] = []
    for key in row.related_alert_keys or []:
        related_rows.extend(alert_map.get(key, []))
    return {
        "id": row.id,
        "status": row.status,
        "severity": row.severity,
        "title": row.title,
        "summary": row.summary,
        "services": list(row.services or []),
        "owner": row.owner,
        "links": list(row.links or []),
        "related_alert_keys": list(row.related_alert_keys or []),
        "related_alerts": related_rows,
        "deploy_sha": row.deploy_sha,
        "deploy_url": row.deploy_url,
        "started_at": _iso(row.started_at),
        "ended_at": _iso(row.ended_at),
        "duration_seconds": duration,
        "created_by": row.created_by,
        "updated_by": row.updated_by,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _audit_snapshot(row: models.AdminIncident) -> dict[str, Any]:
    return {
        "status": row.status,
        "severity": row.severity,
        "title": row.title,
        "summary": row.summary,
        "services": list(row.services or []),
        "owner": row.owner,
        "links": list(row.links or []),
        "related_alert_keys": list(row.related_alert_keys or []),
        "deploy_sha": row.deploy_sha,
        "deploy_url": row.deploy_url,
        "started_at": _iso(row.started_at),
        "ended_at": _iso(row.ended_at),
    }


def _reason(value: Any, fallback: str) -> str:
    if value is not None and str(value).strip():
        cleaned = " ".join(str(value).split())[:1000]
        _reject_pii(cleaned, field="reason")
        return cleaned
    return fallback


async def list_incidents(
    db: AsyncSession,
    *,
    service: str | None = None,
    services: Iterable[str] | None = None,
    severity: str | None = None,
    status: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Return a filtered incident timeline, newest first.

    Date bounds match when the incident started, which keeps the timeline view
    predictable: ``start_date`` is inclusive and ``end_date`` is inclusive at
    the supplied instant. Service filters match any of the incident's affected
    services.
    """
    now = datetime.now(timezone.utc)
    requested_services: list[str] = []
    if service:
        requested_services.extend(_services([service]))
    if services:
        requested_services.extend(_services(list(services)))

    conditions = []
    if requested_services:
        conditions.append(
            or_(
                *[
                    models.AdminIncident.services.contains([requested])
                    for requested in requested_services
                ]
            )
        )
    if severity:
        conditions.append(models.AdminIncident.severity == _severity(severity))
    if status:
        conditions.append(models.AdminIncident.status == _status(status))

    start = _as_utc(start_date)
    end = _as_utc(end_date)
    if start and end and start > end:
        raise ValueError("start_date must be at or before end_date")
    if start:
        conditions.append(models.AdminIncident.started_at >= start)
    if end:
        conditions.append(models.AdminIncident.started_at <= end)

    total = int(
        (
            await db.execute(
                select(func.count(models.AdminIncident.id)).where(*conditions)
            )
        ).scalar_one()
        or 0
    )
    active_count = int(
        (
            await db.execute(
                select(func.count(models.AdminIncident.id)).where(
                    models.AdminIncident.status == ACTIVE_STATUS
                )
            )
        ).scalar_one()
        or 0
    )
    rows = (
        await db.execute(
            select(models.AdminIncident)
            .where(*conditions)
            .order_by(models.AdminIncident.started_at.desc(), models.AdminIncident.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()

    keys: set[str] = set()
    for row in rows:
        keys.update(row.related_alert_keys or [])
    related = await _related_alerts(db, keys)

    return {
        "generated_at": now.isoformat(),
        "items": [_payload(row, related_alerts=related, now=now) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
        "active_count": active_count,
        "filters": {
            "service": sorted(set(requested_services)),
            "severity": severity,
            "status": status,
            "start_date": _iso(start),
            "end_date": _iso(end),
        },
    }


async def get_incident(db: AsyncSession, incident_id: str) -> dict[str, Any]:
    row = await _get(db, _incident_id(incident_id))
    related = await _related_alerts(db, row.related_alert_keys or [])
    return _payload(row, related_alerts=related)


async def create_incident(
    db: AsyncSession,
    *,
    actor: AdminActor,
    request=None,
    title: str | None,
    summary: str,
    severity: str,
    services: Iterable[str],
    owner: str,
    links: Iterable[str] | None = None,
    related_alert_keys: Iterable[str] | None = None,
    deploy_sha: str | None = None,
    deploy_url: str | None = None,
    started_at: datetime | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    clean_summary = _text(summary, field="summary", max_length=MAX_SUMMARY)
    clean_title = _text(
        title or clean_summary[:120],
        field="title",
        max_length=MAX_TITLE,
    )
    row = models.AdminIncident(
        status=ACTIVE_STATUS,
        severity=_severity(severity),
        title=clean_title,
        summary=clean_summary,
        services=_services(services),
        owner=_text(owner, field="owner", max_length=MAX_OWNER),
        links=_links(links),
        related_alert_keys=_alert_keys(related_alert_keys),
        deploy_sha=_deploy_sha(deploy_sha),
        deploy_url=_deploy_url(deploy_url),
        started_at=_started_at(started_at, now=now),
        ended_at=None,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    db.add(row)
    await db.flush()
    await record_admin_audit(
        db,
        actor=actor,
        action="admin.incident.open",
        target_type="admin_incident",
        target_id=row.id,
        reason=_reason(reason, "Incident opened"),
        after=_audit_snapshot(row),
        request=request,
        commit=False,
    )
    await db.commit()
    await db.refresh(row)
    related = await _related_alerts(db, row.related_alert_keys or [])
    return _payload(row, related_alerts=related)


async def update_incident(
    db: AsyncSession,
    *,
    incident_id: str,
    actor: AdminActor,
    request=None,
    changes: Mapping[str, Any],
    reason: str | None = None,
) -> dict[str, Any]:
    row = await _get(db, _incident_id(incident_id), lock=True)
    before = _audit_snapshot(row)
    now = datetime.now(timezone.utc)

    if "title" in changes:
        row.title = _text(
            changes["title"],
            field="title",
            max_length=MAX_TITLE,
        )
    if "summary" in changes:
        row.summary = _text(
            changes["summary"],
            field="summary",
            max_length=MAX_SUMMARY,
        )
    if "severity" in changes:
        row.severity = _severity(changes["severity"])
    if "services" in changes:
        row.services = _services(changes["services"])
    if "owner" in changes:
        row.owner = _text(changes["owner"], field="owner", max_length=MAX_OWNER)
    if "links" in changes:
        row.links = _links(changes["links"])
    if "related_alert_keys" in changes:
        row.related_alert_keys = _alert_keys(changes["related_alert_keys"])
    if "deploy_sha" in changes:
        row.deploy_sha = _deploy_sha(changes["deploy_sha"])
    if "deploy_url" in changes:
        row.deploy_url = _deploy_url(changes["deploy_url"])
    if "started_at" in changes:
        started = _as_utc(changes["started_at"])
        if started is None:
            raise ValueError("started_at is required")
        row.started_at = _started_at(started, now=now)
        if row.ended_at is not None and _as_utc(row.ended_at) < row.started_at:
            raise ValueError("started_at must be at or before ended_at")

    row.updated_by = actor.user_id
    await db.flush()
    await record_admin_audit(
        db,
        actor=actor,
        action="admin.incident.update",
        target_type="admin_incident",
        target_id=row.id,
        reason=_reason(reason, "Incident updated"),
        before=before,
        after=_audit_snapshot(row),
        request=request,
        commit=False,
    )
    await db.commit()
    await db.refresh(row)
    related = await _related_alerts(db, row.related_alert_keys or [])
    return _payload(row, related_alerts=related)


async def transition_incident(
    db: AsyncSession,
    *,
    incident_id: str,
    actor: AdminActor,
    request=None,
    target_status: str,
    reason: str | None = None,
    ended_at: datetime | None = None,
) -> dict[str, Any]:
    desired = _status(target_status, allow_active=False)
    row = await _get(db, _incident_id(incident_id), lock=True)
    if row.status == desired:
        raise ValueError(f"Incident is already {desired}")
    now = datetime.now(timezone.utc)
    before = _audit_snapshot(row)
    if desired == "resolved":
        row.status = "resolved"
        row.ended_at = _ended_at(
            ended_at,
            started_at=_as_utc(row.started_at) or now,
            now=now,
        )
        action = "admin.incident.resolve"
        fallback = "Incident resolved"
    else:
        row.status = "open"
        row.ended_at = None
        action = "admin.incident.reopen"
        fallback = "Incident reopened"
    row.updated_by = actor.user_id
    await db.flush()
    await record_admin_audit(
        db,
        actor=actor,
        action=action,
        target_type="admin_incident",
        target_id=row.id,
        reason=_reason(reason, fallback),
        before=before,
        after=_audit_snapshot(row),
        request=request,
        commit=False,
    )
    await db.commit()
    await db.refresh(row)
    related = await _related_alerts(db, row.related_alert_keys or [])
    return _payload(row, related_alerts=related)


async def delete_incident(
    db: AsyncSession,
    *,
    incident_id: str,
    actor: AdminActor,
    request=None,
    reason: str | None = None,
) -> dict[str, Any]:
    row = await _get(db, _incident_id(incident_id), lock=True)
    before = _audit_snapshot(row)
    deleted_id = row.id
    await record_admin_audit(
        db,
        actor=actor,
        action="admin.incident.delete",
        target_type="admin_incident",
        target_id=deleted_id,
        reason=_reason(reason, "Incident deleted"),
        before=before,
        request=request,
        commit=False,
    )
    await db.delete(row)
    await db.commit()
    return {"deleted": True, "id": deleted_id}


def safe_incident_text(value: Any, *, field: str = "text", max_length: int = 500) -> str:
    """Public helper for callers that need the same PII guard outside this module."""
    return _text(value, field=field, max_length=max_length)
