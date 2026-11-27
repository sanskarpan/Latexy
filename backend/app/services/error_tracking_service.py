"""Aggregate-only error grouping, admin feed and rate-limited alert delivery.

The service is the single boundary for exception *metadata*. Callers may only
supply a source, a route, a release and an error class; there is no field for a
message, stack trace, source snippet, prompt, document content, email, token,
user id, IP address or user agent. Every value is normalized here before it can
reach the database or an alert payload.

Grouping is intentionally coarse:

* ``(source, route, release, error_class)`` identifies a group.
* ``occurrence_count`` is the lifetime count shown in the admin feed.
* ``window_events`` is the rolling burst count used by the alert threshold. A
  gap longer than the configured window resets it to one.
* ``last_alerted_at`` / ``alert_count`` rate-limit repeat delivery per group.

The admin feed suppresses groups with fewer than five occurrences, mirroring the
five-user suppression used by the other admin analytics surfaces. Alert payloads
carry the sanitized group key, counters and a runbook link only.
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Mapping, Sequence
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from sqlalchemy import case, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.logging import get_logger
from ..database import models
from .admin_audit_service import AdminActor, record_admin_audit

logger = get_logger(__name__)

MIN_COHORT_SIZE = 5
MAX_FEED_GROUPS = 50
MAX_ALERTS_PER_RUN = 5
MAX_WINDOW_CANDIDATES = 100
RUNBOOK_URL = "https://github.com/sanskarpan/Latexy/blob/main/docs/observability/error-alert-runbook.md"
SLACK_TIMEOUT_SECONDS = 5.0

SOURCES = ("frontend", "backend")

#: Sanitized product routes accepted from browser telemetry. Anything else,
#: including a document/share/portfolio path, is bucketed or dropped.
FRONTEND_ROUTES = frozenset(
    {
        "/",
        "/login",
        "/signup",
        "/dashboard",
        "/templates",
        "/tracker",
        "/billing",
        "/pricing",
        "/settings",
    }
)

#: First segments that always refer to a document or a document-sharing
#: surface. These are never recorded, even as a template.
BLOCKED_ROUTE_SEGMENTS = frozenset(
    {
        "workspace",
        "workspaces",
        "resume",
        "resumes",
        "document",
        "documents",
        "share",
        "portfolio",
        "r",
        "u",
        "try",
    }
)

_RELEASE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_ERROR_CLASS_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,63}$")
_SAFE_ROUTE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._~{}-]{1,64}$")
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_HEX_ID_RE = re.compile(r"^[0-9a-fA-F]{16,}$")
_NUMERIC_RE = re.compile(r"^\d+$")
_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_TOKEN_RE = re.compile(r"(?:sk-|phc_|phx_|bearer\s+|ghp_|eyJ)[A-Za-z0-9._\-]{8,}", re.IGNORECASE)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _normalize_source(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized not in SOURCES:
        raise ValueError("source must be frontend or backend")
    return normalized


def sanitize_release(value: object) -> str:
    """Return a bounded release identifier or ``unknown``."""
    if not isinstance(value, str):
        return "unknown"
    release = value.strip()
    if re.match(r"^(?:phc_|phx_|sk-|bearer)", release, re.IGNORECASE):
        return "unknown"
    return release if _RELEASE_RE.fullmatch(release) else "unknown"


def sanitize_error_class(value: object) -> str:
    """Return a bounded error class name or ``UnknownError``.

    Rejecting everything outside a conservative identifier pattern also drops
    pasted messages, emails, bearer tokens and provider payload fragments.
    """
    if not isinstance(value, str):
        return "UnknownError"
    error_class = value.strip()
    if not error_class or _EMAIL_RE.search(error_class) or _TOKEN_RE.search(error_class):
        return "UnknownError"
    if not _ERROR_CLASS_RE.fullmatch(error_class):
        return "UnknownError"
    return error_class


def _is_blocked_route(path: str) -> bool:
    segments = [segment for segment in path.split("/") if segment]
    if segments and segments[0].lower() == "api":
        segments = segments[1:]
    return bool(segments) and segments[0].lower() in BLOCKED_ROUTE_SEGMENTS


def _clean_path(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    raw = value.strip().split("?", 1)[0].split("#", 1)[0]
    if not raw.startswith("/") or not raw.isascii():
        return None
    if any(ord(char) < 32 or ord(char) == 127 for char in raw):
        return None
    collapsed = re.sub(r"/{2,}", "/", raw)
    return collapsed[:256] or "/"


def normalize_error_route(value: object, *, source: str) -> str | None:
    """Return a sanitized route template, ``/other``, or ``None``.

    ``None`` means the surface is blocked (document, share, portfolio, guest
    editor) and the caller must not record the event at all.
    """
    path = _clean_path(value)
    if path is None:
        return "/other"
    if _is_blocked_route(path):
        return None

    if source == "frontend":
        if path in FRONTEND_ROUTES:
            return path
        return "/other"

    parts: list[str] = []
    for part in path.split("/"):
        if not part:
            continue
        if _UUID_RE.fullmatch(part) or _HEX_ID_RE.fullmatch(part) or _NUMERIC_RE.fullmatch(part):
            parts.append(":id")
        elif not _SAFE_ROUTE_SEGMENT_RE.fullmatch(part):
            parts.append(":id")
        else:
            parts.append(part)
    template = "/" + "/".join(parts) if parts else "/"
    return template[:128]


def normalize_route_filter(value: object) -> str | None:
    """Normalize a feed filter route without the product-route allowlist."""
    return normalize_error_route(value, source="backend")


def current_release() -> str:
    return sanitize_release(getattr(settings, "APP_VERSION", "unknown"))


def _group_key(*, source: str, route: str, release: str, error_class: str) -> str:
    material = f"{source}|{route}|{release}|{error_class}".encode()
    return hashlib.sha256(material).hexdigest()[:32]


async def record_error_group(
    db: AsyncSession,
    *,
    source: str,
    route: object,
    error_class: object,
    release: object = None,
    occurred_at: datetime | None = None,
) -> str | None:
    """Upsert one sanitized aggregate row. Returns the group id or ``None``.

    ``None`` is returned when tracking is disabled or the route is a blocked
    document/share surface. No caller-supplied text is stored.
    """
    if not getattr(settings, "ERROR_TRACKING_ENABLED", True):
        return None
    normalized_source = _normalize_source(source)
    normalized_route = normalize_error_route(route, source=normalized_source)
    if normalized_route is None:
        return None
    normalized_release = sanitize_release(release if release is not None else current_release())
    normalized_class = sanitize_error_class(error_class)
    now = occurred_at or _now()
    window = timedelta(minutes=max(1, int(settings.ERROR_ALERT_WINDOW_MINUTES)))
    window_cutoff = now - window

    statement = (
        pg_insert(models.AdminErrorGroup)
        .values(
            id=str(uuid4()),
            source=normalized_source,
            route=normalized_route,
            release=normalized_release,
            error_class=normalized_class,
            occurrence_count=1,
            window_events=1,
            window_started_at=now,
            first_seen_at=now,
            last_seen_at=now,
            alert_count=0,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_update(
            constraint="uq_admin_error_groups_key",
            set_={
                "occurrence_count": models.AdminErrorGroup.occurrence_count + 1,
                "window_events": case(
                    (models.AdminErrorGroup.window_started_at < window_cutoff, 1),
                    else_=models.AdminErrorGroup.window_events + 1,
                ),
                "window_started_at": case(
                    (models.AdminErrorGroup.window_started_at < window_cutoff, now),
                    else_=models.AdminErrorGroup.window_started_at,
                ),
                "last_seen_at": func.greatest(models.AdminErrorGroup.last_seen_at, now),
                "updated_at": now,
            },
        )
        .returning(models.AdminErrorGroup.id)
    )
    return (await db.execute(statement)).scalar_one()


def _group_row(row: models.AdminErrorGroup) -> dict[str, Any]:
    return {
        "id": row.id,
        "source": row.source,
        "route": row.route,
        "release": row.release,
        "error_class": row.error_class,
        "occurrence_count": int(row.occurrence_count or 0),
        "window_events": int(row.window_events or 0),
        "window_started_at": _iso(row.window_started_at),
        "first_seen_at": _iso(row.first_seen_at),
        "last_seen_at": _iso(row.last_seen_at),
        "last_alerted_at": _iso(row.last_alerted_at),
        "alert_count": int(row.alert_count or 0),
    }


def threshold_config() -> dict[str, int]:
    return {
        "occurrences": max(1, int(settings.ERROR_ALERT_THRESHOLD)),
        "window_minutes": max(1, int(settings.ERROR_ALERT_WINDOW_MINUTES)),
        "cooldown_minutes": max(1, int(settings.ERROR_ALERT_COOLDOWN_MINUTES)),
    }


def _delivery_channels() -> list[str]:
    channels: list[str] = []
    if _slack_webhook_url():
        channels.append("slack")
    if _email_recipients():
        channels.append("email")
    return channels


def _slack_webhook_url() -> str | None:
    raw = (getattr(settings, "ALERT_SLACK_WEBHOOK_URL", "") or "").strip()
    if not raw:
        return None
    parsed = urlsplit(raw)
    if parsed.scheme != "https" or not parsed.netloc:
        return None
    return raw


def _email_recipients() -> list[str]:
    raw = (getattr(settings, "ALERT_EMAIL_TO", "") or "").strip()
    if not raw:
        return []
    recipients: list[str] = []
    for candidate in raw.split(","):
        address = candidate.strip()
        if address and _EMAIL_RE.fullmatch(address) and len(address) <= 254:
            recipients.append(address)
        if len(recipients) >= 5:
            break
    return recipients


async def error_feed(
    db: AsyncSession,
    *,
    days: int = 7,
    source: str | None = None,
    route: str | None = None,
    error_class: str | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Return aggregate groups plus suppression and delivery state."""
    days = max(1, min(int(days), 90))
    limit = max(1, min(int(limit), MAX_FEED_GROUPS))
    now = _now()
    start = now - timedelta(days=days)

    filters = [models.AdminErrorGroup.last_seen_at >= start]
    normalized_route: str | None = None
    normalized_class: str | None = None
    if source is not None:
        filters.append(models.AdminErrorGroup.source == _normalize_source(source))
    if route is not None:
        normalized_route = normalize_route_filter(route)
        if normalized_route is None:
            raise ValueError("route is not an eligible aggregate route")
        filters.append(models.AdminErrorGroup.route == normalized_route)
    if error_class is not None:
        normalized_class = sanitize_error_class(error_class)
        if normalized_class != error_class.strip():
            raise ValueError("error_class must be a bounded error class identifier")
        filters.append(models.AdminErrorGroup.error_class == normalized_class)

    total_events = int(
        (
            await db.execute(
                select(func.coalesce(func.sum(models.AdminErrorGroup.occurrence_count), 0)).where(*filters)
            )
        ).scalar()
        or 0
    )
    group_total = int((await db.execute(select(func.count(models.AdminErrorGroup.id)).where(*filters))).scalar() or 0)
    suppressed_filters = [
        *filters,
        models.AdminErrorGroup.occurrence_count < MIN_COHORT_SIZE,
    ]
    suppressed_groups = int(
        (await db.execute(select(func.count(models.AdminErrorGroup.id)).where(*suppressed_filters))).scalar() or 0
    )
    suppressed_events = int(
        (
            await db.execute(
                select(func.coalesce(func.sum(models.AdminErrorGroup.occurrence_count), 0)).where(*suppressed_filters)
            )
        ).scalar()
        or 0
    )

    rows = (
        (
            await db.execute(
                select(models.AdminErrorGroup)
                .where(*filters, models.AdminErrorGroup.occurrence_count >= MIN_COHORT_SIZE)
                .order_by(
                    models.AdminErrorGroup.occurrence_count.desc(),
                    models.AdminErrorGroup.last_seen_at.desc(),
                )
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    visible_filters = [*filters, models.AdminErrorGroup.occurrence_count >= MIN_COHORT_SIZE]
    visible_groups = int(
        (await db.execute(select(func.count(models.AdminErrorGroup.id)).where(*visible_filters))).scalar() or 0
    )
    distinct_routes = int(
        (
            await db.execute(select(func.count(func.distinct(models.AdminErrorGroup.route))).where(*visible_filters))
        ).scalar()
        or 0
    )
    distinct_releases = int(
        (
            await db.execute(select(func.count(func.distinct(models.AdminErrorGroup.release))).where(*visible_filters))
        ).scalar()
        or 0
    )

    channels = _delivery_channels()
    return {
        "generated_at": _iso(now),
        "days": days,
        "window": {"start": _iso(start), "end": _iso(now)},
        "filters": {"source": source, "route": normalized_route, "error_class": normalized_class},
        "threshold": threshold_config(),
        "groups": [_group_row(row) for row in rows],
        "totals": {
            "events": total_events,
            "groups": group_total,
            "visible_groups": visible_groups,
            "routes": distinct_routes,
            "releases": distinct_releases,
            "suppressed_groups": suppressed_groups,
            "suppressed_events": suppressed_events,
        },
        "suppression": {
            "minimum_cohort_size": MIN_COHORT_SIZE,
            "user_dimension_included": False,
            "messages_included": False,
        },
        "delivery": {
            "configured": bool(channels),
            "channels": channels,
        },
        "runbook_url": RUNBOOK_URL,
    }


def build_error_alert_payload(group: models.AdminErrorGroup, *, now: datetime | None = None) -> dict[str, Any]:
    """Build the only payload shape allowed to leave the service boundary."""
    config = threshold_config()
    return {
        "kind": "error_threshold",
        "source": group.source,
        "route": group.route,
        "release": group.release,
        "error_class": group.error_class,
        "window_events": int(group.window_events or 0),
        "total_events": int(group.occurrence_count or 0),
        "threshold": config["occurrences"],
        "window_minutes": config["window_minutes"],
        "first_seen_at": _iso(group.first_seen_at),
        "last_seen_at": _iso(group.last_seen_at),
        "environment": settings.ENVIRONMENT,
        "runbook_url": RUNBOOK_URL,
    }


def render_slack_message(alerts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    lines = []
    for alert in alerts:
        lines.append(
            f"*{alert['error_class']}* on `{alert['route']}` ({alert['source']}, "
            f"release `{alert['release']}`) - {alert['window_events']} events in "
            f"{alert['window_minutes']}m (threshold {alert['threshold']})"
        )
    text = "\n".join(lines)
    return {
        "text": f"Latexy error threshold crossed: {len(alerts)} group(s). Runbook: {RUNBOOK_URL}",
        "channel": (getattr(settings, "ALERT_SLACK_CHANNEL", "") or "").strip() or "#alerts",
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "Latexy error threshold crossed"},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": text},
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"<{RUNBOOK_URL}|Open the error alert runbook>",
                    }
                ],
            },
        ],
    }


def render_error_alert_email(alerts: Sequence[Mapping[str, Any]]) -> tuple[str, str, str]:
    subject = f"[Latexy] {len(alerts)} error group(s) crossed the alert threshold"
    plain_lines: list[str] = []
    for alert in alerts:
        plain_lines.extend(
            [
                f"{alert['error_class']} on {alert['route']} ({alert['source']}, release {alert['release']})",
                f"  {alert['window_events']} events in {alert['window_minutes']}m "
                f"(threshold {alert['threshold']}, lifetime {alert['total_events']})",
            ]
        )
    plain_lines.extend(["", f"Runbook: {RUNBOOK_URL}"])
    plain = "\n".join(plain_lines)

    rows = []
    for alert in alerts:
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(alert['error_class']))}</td>"
            f"<td>{html.escape(str(alert['route']))}</td>"
            f"<td>{html.escape(str(alert['source']))}</td>"
            f"<td>{html.escape(str(alert['release']))}</td>"
            f"<td>{html.escape(str(alert['window_events']))}</td>"
            f"<td>{html.escape(str(alert['total_events']))}</td>"
            "</tr>"
        )
    body = (
        "<p>An error group crossed the configured threshold. This message contains "
        "aggregate error metadata only; no messages, stacks, prompts or document "
        "content are captured.</p>"
        "<table><thead><tr><th>Class</th><th>Route</th><th>Source</th>"
        "<th>Release</th><th>Window</th><th>Total</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
        f'<p><a href="{html.escape(RUNBOOK_URL)}">Error alert runbook</a></p>'
    )
    return subject, plain, body


async def _send_slack(
    url: str,
    payload: Mapping[str, Any],
    sender: Callable[[str, Mapping[str, Any]], Awaitable[None]] | None,
) -> bool:
    try:
        if sender is not None:
            await sender(url, payload)
        else:
            async with httpx.AsyncClient(timeout=SLACK_TIMEOUT_SECONDS) as client:
                response = await client.post(url, json=dict(payload))
                response.raise_for_status()
        return True
    except Exception as exc:  # pragma: no cover - network/provider failure
        logger.warning("error alert Slack delivery failed (%s)", type(exc).__name__)
        return False


async def _send_email(
    recipients: Sequence[str],
    subject: str,
    plain: str,
    body: str,
    sender: Callable[[str, str, str, str], Awaitable[bool]] | None,
) -> bool:
    delivered = False
    for recipient in recipients:
        try:
            if sender is not None:
                accepted = await sender(recipient, subject, body, plain)
            else:
                from .email_service import email_service

                accepted = await email_service.send_email(
                    to=recipient,
                    subject=subject,
                    html_body=body,
                    text_body=plain,
                )
        except Exception as exc:  # pragma: no cover - provider failure
            logger.warning("error alert email delivery failed (%s)", type(exc).__name__)
            continue
        delivered = delivered or bool(accepted)
    return delivered


async def deliver_error_alerts(
    alerts: Sequence[Mapping[str, Any]],
    *,
    slack_sender: Callable[[str, Mapping[str, Any]], Awaitable[None]] | None = None,
    email_sender: Callable[[str, str, str, str], Awaitable[bool]] | None = None,
) -> dict[str, Any]:
    """Deliver one aggregate message per configured channel.

    The payload is built by :func:`build_error_alert_payload`; no exception
    text, user identifier, email body or provider response is forwarded.
    """
    channels: list[dict[str, str]] = []
    if not alerts:
        return {"attempted": False, "delivered": False, "channels": []}

    slack_url = _slack_webhook_url()
    if slack_url:
        sent = await _send_slack(slack_url, render_slack_message(alerts), slack_sender)
        channels.append({"channel": "slack", "status": "sent" if sent else "failed"})

    recipients = _email_recipients()
    if recipients:
        subject, plain, body = render_error_alert_email(alerts)
        sent = await _send_email(recipients, subject, plain, body, email_sender)
        channels.append({"channel": "email", "status": "sent" if sent else "failed"})

    return {
        "attempted": bool(channels),
        "delivered": any(channel["status"] == "sent" for channel in channels),
        "channels": channels,
    }


async def evaluate_error_alerts(
    db: AsyncSession,
    *,
    actor: AdminActor,
    reason: str,
    request: Any = None,
    now: datetime | None = None,
    dry_run: bool = False,
    slack_sender: Callable[[str, Mapping[str, Any]], Awaitable[None]] | None = None,
    email_sender: Callable[[str, str, str, str], Awaitable[bool]] | None = None,
) -> dict[str, Any]:
    """Evaluate thresholds, deliver at most once per cooldown, and audit.

    ``dry_run`` computes the same candidate list without changing alert state,
    delivering a message or writing an audit row.
    """
    now = now or _now()
    config = threshold_config()
    window_start = now - timedelta(minutes=config["window_minutes"])
    cooldown_cutoff = now - timedelta(minutes=config["cooldown_minutes"])

    if not dry_run:
        # Serialize overlapping dispatches so the cooldown SELECT-then-UPDATE
        # path cannot send the same group twice.
        await db.execute(text("SELECT pg_advisory_xact_lock(hashtext('latexy_error_alerts'))"))

    candidates = (
        (
            await db.execute(
                select(models.AdminErrorGroup)
                .where(
                    models.AdminErrorGroup.window_events >= config["occurrences"],
                    models.AdminErrorGroup.last_seen_at >= window_start,
                )
                .order_by(
                    models.AdminErrorGroup.window_events.desc(),
                    models.AdminErrorGroup.last_seen_at.desc(),
                )
                .limit(MAX_WINDOW_CANDIDATES)
            )
        )
        .scalars()
        .all()
    )

    due = [row for row in candidates if row.last_alerted_at is None or row.last_alerted_at <= cooldown_cutoff]
    skipped_cooldown = max(0, len(candidates) - len(due))
    selected = due[:MAX_ALERTS_PER_RUN]
    payloads = [build_error_alert_payload(row, now=now) for row in selected]
    channels = _delivery_channels()

    result: dict[str, Any] = {
        "dry_run": dry_run,
        "threshold": config,
        "candidate_count": len(candidates),
        "selected_count": len(selected),
        "skipped_cooldown": skipped_cooldown,
        "delivery_configured": bool(channels),
        "runbook_url": RUNBOOK_URL,
        "alerts": payloads,
        "delivery": {"attempted": False, "delivered": False, "channels": []},
        "alerted": 0,
    }

    if dry_run:
        return result

    if selected and channels:
        delivery = await deliver_error_alerts(
            payloads,
            slack_sender=slack_sender,
            email_sender=email_sender,
        )
        result["delivery"] = delivery
        if delivery["delivered"]:
            for row in selected:
                row.last_alerted_at = now
                row.alert_count = int(row.alert_count or 0) + 1
                row.updated_at = now
            result["alerted"] = len(selected)

    await record_admin_audit(
        db,
        actor=actor,
        action="admin.error_alerts.evaluate",
        target_type="error_alert",
        target_id="threshold",
        reason=reason,
        after={
            "candidate_count": len(candidates),
            "selected_count": len(selected),
            "alerted": result["alerted"],
            "channels": [channel["channel"] for channel in result["delivery"]["channels"]],
            "window_minutes": config["window_minutes"],
            "threshold": config["occurrences"],
        },
        request=request,
    )
    await db.commit()
    return result


def backend_error_signal(route: object, exc: BaseException) -> dict[str, str] | None:
    """Return the sanitized signal for an unhandled backend exception."""
    normalized_route = normalize_error_route(route, source="backend")
    if normalized_route is None:
        return None
    return {
        "source": "backend",
        "route": normalized_route,
        "release": current_release(),
        "error_class": sanitize_error_class(type(exc).__name__),
    }


async def record_backend_exception(
    db: AsyncSession,
    *,
    route: object,
    exc: BaseException,
    occurred_at: datetime | None = None,
) -> str | None:
    """Record an unhandled backend exception using only class and route."""
    signal = backend_error_signal(route, exc)
    if signal is None:
        return None
    return await record_error_group(
        db,
        source=signal["source"],
        route=signal["route"],
        release=signal["release"],
        error_class=signal["error_class"],
        occurred_at=occurred_at,
    )


_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()


async def _capture_backend_signal(signal: Mapping[str, str]) -> None:
    from ..database.connection import get_async_db_session

    try:
        async with get_async_db_session() as session:
            await record_error_group(session, **signal)
            await session.commit()
    except Exception as exc:  # pragma: no cover - DB outage must never break a 500
        logger.warning("backend error capture failed (%s)", type(exc).__name__)


def schedule_backend_capture(route: object, exc: BaseException) -> None:
    """Best-effort background capture for the global 500 handler.

    Test environments skip scheduling so an expected 500 in an unrelated suite
    cannot write telemetry through a second session; tests call the recorder
    directly instead.
    """
    if settings.ENVIRONMENT.lower() in {"test", "testing"}:
        return
    if not getattr(settings, "ERROR_TRACKING_ENABLED", True):
        return
    signal = backend_error_signal(route, exc)
    if signal is None:
        return
    try:
        task = asyncio.create_task(_capture_backend_signal(signal))
    except RuntimeError:  # pragma: no cover - no running loop
        return
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
