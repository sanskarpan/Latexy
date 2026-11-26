"""Admin live activity feed with a bounded, incremental cursor.

The feed projects only opaque identifiers and typed, allowlisted event names
from existing first-party tables. It never selects resume content, prompts,
emails, IP addresses, user agents, payment credentials, provider payloads or
free-text errors, and it does not return ``usage_analytics.event_metadata``.
Every projected row is still passed through the shared telemetry redaction
boundary as defence in depth.

Two modes are supported:

* ``live`` composes typed signup, payment, compile, optimize and error events
  directly from domain tables.
* ``fallback`` is used when any live source is unavailable and tails the same
  ``usage_analytics`` rows as the existing admin recent-events view, mapped onto
  the same five categories. Fallback rows contain the event name only; no
  metadata values are read or returned.

Cursors are opaque ``(created_at, event_id)`` tokens. Incremental pages are
returned oldest-first so a caller that honours ``has_more`` never skips rows;
the serialized items remain newest-first for direct display.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Sequence
from uuid import UUID

from sqlalchemy import String, and_, cast, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logging import get_logger
from ..core.telemetry_metadata import redact_metadata
from ..database import models

logger = get_logger(__name__)

ActivityCategory = Literal["signup", "payment", "compile", "optimize", "error"]

ACTIVITY_CATEGORIES: tuple[ActivityCategory, ...] = (
    "signup",
    "payment",
    "compile",
    "optimize",
    "error",
)

DEFAULT_ACTIVITY_LIMIT = 50
MAX_ACTIVITY_LIMIT = 100
MAX_CURSOR_LENGTH = 512
FALLBACK_DETAIL = "Live activity sources are unavailable; showing recent first-party usage events in fallback mode."

_SOURCE_PREFIXES = frozenset({"signup", "payment", "compile", "optimize", "usage"})
_SOURCE_PATTERN = re.compile(r"^(signup|payment|compile|optimize|usage):([0-9a-fA-F-]{36})$")
_EVENT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,100}$")
_CURSOR_VERSION = 1

_HREF_BY_CATEGORY: dict[ActivityCategory, str] = {
    "signup": "/admin?tab=customers",
    "payment": "/admin?tab=billing",
    "compile": "/admin?tab=analytics",
    "optimize": "/admin?tab=analytics",
    "error": "/admin?tab=analytics",
}


@dataclass(frozen=True)
class _FeedEvent:
    id: str
    category: ActivityCategory
    event: str
    created_at: datetime
    href: str | None


@dataclass(frozen=True)
class _Cursor:
    created_at: datetime
    event_id: str
    token: str


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    normalized = _as_utc(value)
    return normalized.isoformat() if normalized else None


def _bounded_limit(limit: Any) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int):
        return DEFAULT_ACTIVITY_LIMIT
    return max(1, min(limit, MAX_ACTIVITY_LIMIT))


def _event_key(source: str, entity_id: Any) -> str:
    return f"{source}:{entity_id}"


def _key_expression(model: Any, source: str) -> Any:
    """Return the same ``source:uuid`` key used by the Python-side merge."""

    return func.concat(literal(f"{source}:"), cast(model.id, String))


def encode_cursor(created_at: datetime, event_id: str) -> str:
    """Encode an opaque ``(timestamp, event id)`` cursor."""

    payload = {
        "v": _CURSOR_VERSION,
        "t": _iso(created_at),
        "i": str(event_id),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(token: str | None) -> _Cursor | None:
    """Validate and decode an opaque cursor, raising ``ValueError`` when bad."""

    if not token:
        return None
    if len(token) > MAX_CURSOR_LENGTH:
        raise ValueError("activity cursor is too long")
    padded = token + "=" * (-len(token) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(raw)
    except (ValueError, UnicodeError, binascii.Error, json.JSONDecodeError):
        raise ValueError("activity cursor is invalid") from None
    if not isinstance(payload, dict) or payload.get("v") != _CURSOR_VERSION:
        raise ValueError("activity cursor is invalid")
    raw_time = payload.get("t")
    raw_id = payload.get("i")
    if not isinstance(raw_time, str) or not isinstance(raw_id, str):
        raise ValueError("activity cursor is invalid")
    match = _SOURCE_PATTERN.fullmatch(raw_id)
    if match is None or match.group(1) not in _SOURCE_PREFIXES:
        raise ValueError("activity cursor is invalid")
    try:
        created_at = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
        UUID(match.group(2))
    except (TypeError, ValueError):
        raise ValueError("activity cursor is invalid") from None
    normalized = _as_utc(created_at)
    if normalized is None:
        raise ValueError("activity cursor is invalid")
    return _Cursor(
        created_at=normalized,
        event_id=_event_key(match.group(1), str(UUID(match.group(2)))),
        token=token,
    )


def classify_compile_status(status: Any) -> tuple[ActivityCategory, str]:
    """Map a compile lifecycle status to a typed category and event name."""

    normalized = str(status or "").strip().lower()
    if normalized in {"failed", "failure", "error", "timeout", "timed_out"}:
        return "error", "compile_failed"
    if normalized in {"completed", "complete", "succeeded", "success"}:
        return "compile", "compile_completed"
    if normalized in {"cancelled", "canceled"}:
        return "compile", "compile_cancelled"
    if normalized in {"queued", "pending", "submitted"}:
        return "compile", "compile_queued"
    if normalized in {"processing", "running", "started"}:
        return "compile", "compile_started"
    return "compile", "compile_updated"


def classify_payment_status(status: Any) -> tuple[ActivityCategory, str]:
    """Map a payment lifecycle status to a typed category and event name."""

    normalized = str(status or "").strip().lower()
    if normalized in {"paid", "succeeded", "success", "completed"}:
        return "payment", "payment_succeeded"
    if normalized in {"refunded", "partially_refunded", "partially-refunded"}:
        return "payment", "payment_refunded"
    if normalized in {"failed", "failure", "declined"}:
        return "payment", "payment_failed"
    if normalized in {"pending", "processing", "checkout_unknown", "review"}:
        return "payment", "payment_pending"
    return "payment", "payment_updated"


def classify_usage_action(action: Any) -> tuple[ActivityCategory, str] | None:
    """Best-effort mapping for the fallback ``usage_analytics`` tail.

    Unknown actions are dropped rather than echoed, so the fallback can never
    surface an arbitrary client-supplied string as a feed event.
    """

    text = str(action or "").strip()
    if not text or _EVENT_NAME_PATTERN.fullmatch(text) is None:
        return None
    folded = text.casefold()
    if any(token in folded for token in ("signup", "register", "account_created")):
        return "signup", text
    if any(token in folded for token in ("payment", "checkout", "subscription", "refund", "billing")):
        return "payment", text
    if any(token in folded for token in ("error", "failed", "failure")):
        return "error", text
    if "compile" in folded:
        return "compile", text
    if "optimize" in folded or "optimization" in folded:
        return "optimize", text
    return None


def _cursor_filter(model: Any, source: str, cursor: _Cursor | None) -> Any | None:
    if cursor is None:
        return None
    key = _key_expression(model, source)
    return or_(
        model.created_at > cursor.created_at,
        and_(model.created_at == cursor.created_at, key > cursor.event_id),
    )


async def _select_source(
    db: AsyncSession,
    *,
    model: Any,
    source: str,
    value_column: Any,
    cursor: _Cursor | None,
    limit: int,
) -> Sequence[Any]:
    """Return at most ``limit`` rows for one source in cursor order.

    Initial reads take the newest rows. Incremental reads take the oldest rows
    newer than the cursor so the caller can advance without gaps.
    """

    key = _key_expression(model, source)
    stmt = select(
        model.id.label("entity_id"),
        value_column.label("value"),
        model.created_at.label("created_at"),
    ).where(model.created_at.is_not(None))
    cursor_clause = _cursor_filter(model, source, cursor)
    if cursor_clause is not None:
        stmt = stmt.where(cursor_clause).order_by(model.created_at.asc(), key.asc())
    else:
        stmt = stmt.order_by(model.created_at.desc(), key.desc())
    stmt = stmt.limit(limit)
    return (await db.execute(stmt)).all()


def _live_event(
    source: str,
    entity_id: Any,
    value: Any,
    created_at: datetime | None,
) -> _FeedEvent | None:
    normalized_at = _as_utc(created_at)
    if normalized_at is None:
        return None
    if source == "signup":
        category: ActivityCategory = "signup"
        event = "signup_completed"
    elif source == "payment":
        category, event = classify_payment_status(value)
    elif source == "compile":
        category, event = classify_compile_status(value)
    elif source == "optimize":
        category = "optimize"
        event = "optimize_completed"
    else:  # pragma: no cover - guarded by the caller
        return None
    feed_id = _event_key(source, entity_id)
    return _FeedEvent(
        id=feed_id,
        category=category,
        event=event,
        created_at=normalized_at,
        href=_HREF_BY_CATEGORY.get(category),
    )


async def _load_live_events(
    db: AsyncSession,
    *,
    cursor: _Cursor | None,
    limit: int,
) -> tuple[list[_FeedEvent], bool]:
    """Compose live sources. Raises when any source cannot be read."""

    events: list[_FeedEvent] = []
    may_have_more = False

    source_specs = (
        (models.User, "signup", literal(None)),
        (models.Payment, "payment", models.Payment.status),
        (models.Compilation, "compile", models.Compilation.status),
        (models.Optimization, "optimize", literal(None)),
    )
    for model, source, value_column in source_specs:
        rows = await _select_source(
            db,
            model=model,
            source=source,
            value_column=value_column,
            cursor=cursor,
            limit=limit,
        )
        if cursor is not None and len(rows) >= limit:
            # The query only returned the oldest page; newer rows may exist.
            may_have_more = True
        for row in rows:
            event = _live_event(source, row.entity_id, row.value, row.created_at)
            if event is not None:
                events.append(event)

    if cursor is None:
        events.sort(key=lambda item: (item.created_at, item.id), reverse=True)
        return list(reversed(events[:limit])), False

    events.sort(key=lambda item: (item.created_at, item.id))
    if len(events) > limit:
        may_have_more = True
    return events[:limit], may_have_more


async def _load_fallback_events(
    db: AsyncSession,
    *,
    cursor: _Cursor | None,
    limit: int,
) -> tuple[list[_FeedEvent], bool, tuple[datetime, str] | None]:
    """Tail the same redacted usage rows as the existing recent-events view.

    The returned anchor always advances past scanned rows, including usage
    actions that do not map onto one of the five feed categories. Advancing on
    the raw tail keeps fallback polling live even when the newest rows are page
    views or other unclassified actions.
    """

    scan_limit = min(limit * 4, MAX_ACTIVITY_LIMIT * 4)
    rows = await _select_source(
        db,
        model=models.UsageAnalytics,
        source="usage",
        value_column=models.UsageAnalytics.action,
        cursor=cursor,
        limit=scan_limit,
    )
    events: list[_FeedEvent] = []
    for row in rows:
        mapped = classify_usage_action(row.value)
        if mapped is None:
            continue
        category, event_name = mapped
        created_at = _as_utc(row.created_at)
        if created_at is None:
            continue
        events.append(
            _FeedEvent(
                id=_event_key("usage", row.entity_id),
                category=category,
                event=event_name,
                created_at=created_at,
                href=_HREF_BY_CATEGORY.get(category),
            )
        )

    def _anchor_for(row: Any) -> tuple[datetime, str] | None:
        created_at = _as_utc(row.created_at)
        if created_at is None:
            return None
        return created_at, _event_key("usage", row.entity_id)

    if cursor is None:
        events.sort(key=lambda item: (item.created_at, item.id), reverse=True)
        anchor = _anchor_for(rows[0]) if rows else None
        return list(reversed(events[:limit])), False, anchor

    events.sort(key=lambda item: (item.created_at, item.id))
    if len(events) > limit:
        # The displayed page is bounded; anchor on its newest row so the rest
        # of the recognized events are returned by the next page.
        return events[:limit], True, (events[limit - 1].created_at, events[limit - 1].id)

    anchor = _anchor_for(rows[-1]) if rows else None
    return events, len(rows) >= scan_limit, anchor


def _serialize(event: _FeedEvent) -> dict[str, Any]:
    payload = {
        "id": event.id,
        "category": event.category,
        "event": event.event,
        "created_at": _iso(event.created_at),
        "href": event.href,
    }
    # Defence in depth: every item crosses the shared telemetry redaction
    # boundary even though the projection above contains no metadata.
    redacted = redact_metadata(payload)
    return {key: redacted.get(key) for key in payload}


async def get_activity_feed(
    db: AsyncSession,
    *,
    cursor: str | None = None,
    limit: int = DEFAULT_ACTIVITY_LIMIT,
) -> dict[str, Any]:
    """Return one bounded activity page plus its next cursor."""

    parsed_cursor = decode_cursor(cursor)
    bounded_limit = _bounded_limit(limit)
    anchor: tuple[datetime, str] | None = None

    try:
        async with db.begin_nested():
            events, has_more = await _load_live_events(
                db,
                cursor=parsed_cursor,
                limit=bounded_limit,
            )
        if events:
            anchor = (events[-1].created_at, events[-1].id)
        mode: Literal["live", "fallback"] = "live"
        degraded = False
        detail: str | None = None
    except Exception as exc:
        # A failed live read must not poison the surrounding transaction: the
        # savepoint is rolled back, then the existing recent-events source is
        # tried on the same session.
        logger.warning(
            "Admin activity live source unavailable (%s); using fallback",
            type(exc).__name__,
        )
        events, has_more, anchor = await _load_fallback_events(
            db,
            cursor=parsed_cursor,
            limit=bounded_limit,
        )
        mode = "fallback"
        degraded = True
        detail = FALLBACK_DETAIL

    if anchor is not None:
        next_cursor = encode_cursor(anchor[0], anchor[1])
    elif events:
        next_cursor = encode_cursor(events[-1].created_at, events[-1].id)
    else:
        next_cursor = parsed_cursor.token if parsed_cursor is not None else None

    return {
        "items": [_serialize(event) for event in reversed(events)],
        "next_cursor": next_cursor,
        "has_more": has_more,
        "mode": mode,
        "degraded": degraded,
        "detail": detail,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
