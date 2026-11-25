"""First-party traffic-source analytics with a strict allowlist.

Landing and signup-attribution rows reuse the existing ``usage_analytics``
JSONB metadata column, so this feature needs no schema migration. The rows
never carry a raw IP, user agent, email, name, token, or full URL: only the
five allowlisted UTM values, a sanitized landing path, and an external
referrer host are persisted.

The browser must capture the UTM query string before ``sanitizeAnalyticsPath``
removes it; this service re-validates every value because the endpoint is
public. Signup attribution is claimed from a server-stored landing row using
an HttpOnly first-party visitor cookie, never from a client-supplied campaign.
"""

from __future__ import annotations

import ipaddress
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Mapping
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logging import get_logger
from ..database import models

logger = get_logger(__name__)

UTM_FIELDS = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")
UTM_MAX_LENGTH = 64
UTM_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~+-]{0,63}$")

MIN_COHORT_SIZE = 5
MAX_GROUPS = 50
MAX_LANDING_ROWS = 100_000
ATTRIBUTION_LOOKBACK_DAYS = 30
VISITOR_COOKIE_NAME = "latexy_traffic_visitor"
VISITOR_COOKIE_MAX_AGE = 180 * 24 * 60 * 60

LANDING_ACTION = "traffic_landing"
SIGNUP_ACTION = "traffic_signup"
RESOURCE_TYPE = "traffic_source"

DIRECT_LABEL = "direct"
UNSET_LABEL = "not set"

SETTLED_PAYMENT_STATUSES = ("paid", "partially_refunded", "refunded", "captured")

_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_HOST_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
_OPAQUE_PATH_SEGMENTS = (
    (re.compile(r"/r/[^/]+"), "/r/:token"),
    (re.compile(r"/u/[^/]+"), "/u/:username"),
    (re.compile(r"/share/[^/]+"), "/share/:token"),
    (re.compile(r"/portfolio/[^/]+"), "/portfolio/:username"),
    (re.compile(r"/workspace/[^/]+"), "/workspace/:resumeId"),
    (re.compile(r"/workspaces/[^/]+"), "/workspaces/:workspaceId"),
)

UsageAnalytics = models.UsageAnalytics
User = models.User
Payment = models.Payment


def is_valid_visitor_id(value: Any) -> bool:
    """Return True for a server-issued or browser-generated opaque UUID."""

    return isinstance(value, str) and _UUID_PATTERN.fullmatch(value) is not None


def new_visitor_id() -> str:
    return str(uuid.uuid4())


def normalize_utm_values(values: Mapping[str, Any]) -> dict[str, str]:
    """Validate and lower-case the five UTM values.

    Free-form text (spaces, ``@``, slashes, ``?``, ``=``, etc.) and oversized
    values are rejected instead of being truncated, so a caller cannot smuggle
    an email, URL, token, or arbitrary label into the analytics store.
    """

    clean: dict[str, str] = {}
    for key in UTM_FIELDS:
        raw = values.get(key)
        if raw is None or raw == "":
            continue
        if not isinstance(raw, str):
            raise ValueError(f"{key} must be a string")
        if len(raw) > UTM_MAX_LENGTH or UTM_PATTERN.fullmatch(raw) is None:
            raise ValueError(f"{key} contains unsupported characters")
        clean[key] = raw.lower()
    return clean


def sanitize_landing_path(value: Any) -> str:
    """Reduce a landing location to a safe pathname, never a full URL.

    Query strings and fragments are dropped before the result is persisted, and
    opaque route identifiers are replaced with stable placeholders. A caller
    that sends an absolute URL or a non-path value is rejected.
    """

    if value is None or value == "":
        return "/"
    if not isinstance(value, str):
        raise ValueError("landing_path must be a string")
    raw = value.strip()
    if not raw:
        return "/"
    if len(raw) > 512:
        raise ValueError("landing_path is too long")
    if "://" in raw or raw.startswith("//"):
        raise ValueError("landing_path must be a path, not a URL")
    path = raw.split("?", 1)[0].split("#", 1)[0]
    if not path.startswith("/"):
        raise ValueError("landing_path must start with /")
    if any(ord(character) < 32 for character in path):
        raise ValueError("landing_path contains control characters")
    for pattern, replacement in _OPAQUE_PATH_SEGMENTS:
        path = pattern.sub(replacement, path)
    return path[:240] or "/"


def sanitize_referrer_host(value: Any) -> str | None:
    """Return only a normalized external referrer host, or ``None``.

    Full referrer URLs (including any path or query string) are reduced to the
    registrable host before storage. IP-shaped hosts are discarded so the
    analytics store never persists an IP address.
    """

    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("referrer must be a string")
    raw = value.strip()
    if not raw:
        return None
    if len(raw) > 2048:
        raise ValueError("referrer is too long")

    parsed = urlsplit(raw if "://" in raw else f"//{raw}")
    host = parsed.hostname
    if not host:
        return None
    host = host.rstrip(".").lower()
    if not host or len(host) > 253:
        raise ValueError("referrer host is invalid")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return None
    if _HOST_PATTERN.fullmatch(host) is None:
        raise ValueError("referrer host is invalid")
    return host


def _stored_attribution(metadata: Mapping[str, Any]) -> dict[str, str] | None:
    """Re-validate a stored landing row before copying it to a signup."""

    try:
        attribution = normalize_utm_values(metadata)
        attribution["landing_path"] = sanitize_landing_path(metadata.get("landing_path"))
        referrer = sanitize_referrer_host(metadata.get("referrer_host"))
    except ValueError:
        return None
    if referrer:
        attribution["referrer_host"] = referrer
    return attribution


<<<<<<< HEAD
=======
def validate_stored_attribution(metadata: Mapping[str, Any]) -> dict[str, str] | None:
    """Public, side-effect-free validation for another analytics service.

    Trial attribution reads the same server-stored first-touch row and must
    apply the exact same allowlist and sanitizers. Invalid or absent metadata
    returns ``None`` rather than raising or echoing caller-controlled values.
    """

    return _stored_attribution(metadata)


>>>>>>> origin/t3/trial-to-paid-cohort-attribution
@dataclass
class _Bucket:
    visitors: set[str] = field(default_factory=set)
    sessions: set[str] = field(default_factory=set)
    signups: set[str] = field(default_factory=set)
    paid: set[str] = field(default_factory=set)


def _group_label(metadata: Mapping[str, Any], key: str, fallback: str) -> str:
    value = metadata.get(key)
    if isinstance(value, str) and value:
        return value
    return fallback


def _pct(value: int, total: int) -> float:
    return round((value / total) * 100, 2) if total else 0.0


async def capture_landing(
    db: AsyncSession,
    *,
    visitor_id: str,
    session_id: str | None,
    utm: Mapping[str, Any],
    landing_path: Any,
    referrer: Any,
) -> dict[str, Any]:
    """Persist one allowlisted, first-party landing event."""

    if not is_valid_visitor_id(visitor_id):
        raise ValueError("visitor id is invalid")
    if session_id is not None and not is_valid_visitor_id(session_id):
        raise ValueError("session id is invalid")

    clean_utm = normalize_utm_values(utm)
    path = sanitize_landing_path(landing_path)
    referrer_host = sanitize_referrer_host(referrer)

    metadata: dict[str, Any] = {
        "visitor_id": visitor_id,
        "session_id": session_id or new_visitor_id(),
        "landing_path": path,
    }
    if referrer_host:
        metadata["referrer_host"] = referrer_host
    metadata.update(clean_utm)

    db.add(
        UsageAnalytics(
            action=LANDING_ACTION,
            resource_type=RESOURCE_TYPE,
            event_metadata=metadata,
            ip_address=None,
            user_agent=None,
        )
    )
    await db.commit()
    return {"recorded": True}


async def claim_signup(
    db: AsyncSession,
    *,
    user_id: str,
    visitor_id: str | None,
) -> dict[str, Any]:
    """Copy the visitor's first-touch landing attribution onto their account.

    The visitor cookie is only a grouping key. The campaign values come from
    the server-stored landing row, so a caller cannot forge attribution by
    posting UTM parameters at signup time.
    """

    if not is_valid_visitor_id(visitor_id):
        return {"recorded": False, "reason": "no_landing"}

    existing = (
        await db.execute(
            select(UsageAnalytics.id)
            .where(
                UsageAnalytics.action == SIGNUP_ACTION,
                UsageAnalytics.user_id == user_id,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return {"recorded": False, "reason": "already_attributed"}

    cutoff = datetime.now(timezone.utc) - timedelta(days=ATTRIBUTION_LOOKBACK_DAYS)
    metadata = (
        await db.execute(
            select(UsageAnalytics.event_metadata)
            .where(
                UsageAnalytics.action == LANDING_ACTION,
                UsageAnalytics.created_at >= cutoff,
                UsageAnalytics.event_metadata["visitor_id"].as_string() == visitor_id,
            )
            .order_by(UsageAnalytics.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not isinstance(metadata, Mapping):
        return {"recorded": False, "reason": "no_landing"}

    attribution = _stored_attribution(metadata)
    if attribution is None:
        return {"recorded": False, "reason": "no_landing"}

    db.add(
        UsageAnalytics(
            user_id=user_id,
            action=SIGNUP_ACTION,
            resource_type=RESOURCE_TYPE,
            event_metadata=attribution,
            ip_address=None,
            user_agent=None,
        )
    )
    await db.commit()
    return {"recorded": True}


def resolve_period(
    *,
    days: int,
    start_date: date | None,
    end_date: date | None,
    now: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Return the UTC [start, end) bounds for a relative or explicit range."""

    current = now or datetime.now(timezone.utc)
    if end_date is not None:
        end_at = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=timezone.utc)
    else:
        end_at = current
    if start_date is not None:
        start_at = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
    else:
        start_at = end_at - timedelta(days=days)
    if start_at >= end_at:
        raise ValueError("start_date must be before end_date")
    if end_at - start_at > timedelta(days=366):
        raise ValueError("date range cannot exceed 366 days")
    return start_at, end_at


def _row(
    label: str,
    bucket: _Bucket,
) -> tuple[dict[str, Any] | None, bool]:
    """Build one group row. Returns (row, suppressed)."""

    visitors = len(bucket.visitors)
    if visitors < MIN_COHORT_SIZE:
        return None, True

    sessions = len(bucket.sessions)
    signups = len(bucket.signups)
    paid = len(bucket.paid)
    suppressed_cells: list[str] = []

    # A zero is safe to publish; a 1-4 user cell is not. This prevents a small
    # source cohort from being re-identified from an aggregate report.
    show_signups = signups == 0 or signups >= MIN_COHORT_SIZE
    show_paid = paid == 0 or paid >= MIN_COHORT_SIZE
    if not show_signups:
        suppressed_cells.append("signups")
    if not show_paid:
        suppressed_cells.append("paid_users")

    signup_conversion = min(100.0, _pct(signups, visitors)) if show_signups else None
    paid_conversion = (
        min(100.0, _pct(paid, signups))
        if show_paid and show_signups and signups > 0
        else (0.0 if show_paid and show_signups else None)
    )

    return (
        {
            "label": label,
            "sessions": sessions,
            "visitors": visitors,
            "signups": signups if show_signups else None,
            "paid_users": paid if show_paid else None,
            "signup_conversion": signup_conversion,
            "paid_conversion": paid_conversion,
            "suppressed_cells": suppressed_cells,
        },
        False,
    )


def _rows_for(
    buckets: Mapping[str, _Bucket],
) -> tuple[list[dict[str, Any]], int, int]:
    rows: list[dict[str, Any]] = []
    suppressed = 0
    ordered = sorted(
        buckets.items(),
        key=lambda item: (-len(item[1].sessions), -len(item[1].visitors), item[0]),
    )
    for label, bucket in ordered:
        row, hidden = _row(label, bucket)
        if hidden:
            suppressed += 1
            continue
        rows.append(row)
    truncated = max(0, len(rows) - MAX_GROUPS)
    return rows[:MAX_GROUPS], suppressed, truncated


async def aggregate(
    db: AsyncSession,
    *,
    days: int = 30,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    """Aggregate sessions, signups, and paid conversion by traffic source."""

    start_at, end_at = resolve_period(days=days, start_date=start_date, end_date=end_date)

    landing_rows = (
        await db.execute(
            select(UsageAnalytics.id, UsageAnalytics.created_at, UsageAnalytics.event_metadata)
            .where(
                UsageAnalytics.action == LANDING_ACTION,
                UsageAnalytics.created_at >= start_at,
                UsageAnalytics.created_at < end_at,
            )
            .order_by(UsageAnalytics.created_at.asc())
            .limit(MAX_LANDING_ROWS)
        )
    ).all()

    dimensions = ("source", "medium", "campaign", "referrer")
    buckets: dict[str, dict[str, _Bucket]] = {
        dimension: defaultdict(_Bucket) for dimension in dimensions
    }
    total_visitors: set[str] = set()
    total_sessions: set[str] = set()

    for row_id, _created_at, metadata in landing_rows:
        if not isinstance(metadata, Mapping):
            continue
        visitor = metadata.get("visitor_id")
        session = metadata.get("session_id")
        if not isinstance(visitor, str) or not visitor:
            continue
        session_key = session if isinstance(session, str) and session else str(row_id)

        labels = {
            "source": _group_label(metadata, "utm_source", DIRECT_LABEL),
            "medium": _group_label(metadata, "utm_medium", UNSET_LABEL),
            "campaign": _group_label(metadata, "utm_campaign", UNSET_LABEL),
            "referrer": _group_label(metadata, "referrer_host", DIRECT_LABEL),
        }
        total_visitors.add(visitor)
        total_sessions.add(session_key)
        for dimension, label in labels.items():
            bucket = buckets[dimension][label]
            bucket.visitors.add(visitor)
            bucket.sessions.add(session_key)

    attributed_signup_rows = (
        await db.execute(
            select(
                UsageAnalytics.user_id,
                UsageAnalytics.event_metadata,
            )
            .join(User, User.id == UsageAnalytics.user_id)
            .where(
                UsageAnalytics.action == SIGNUP_ACTION,
                User.created_at >= start_at,
                User.created_at < end_at,
            )
            .order_by(UsageAnalytics.created_at.asc())
        )
    ).all()

    attributed: dict[str, Mapping[str, Any]] = {}
    for user_id, metadata in attributed_signup_rows:
        if not user_id or not isinstance(metadata, Mapping):
            continue
        user_key = str(user_id)
        if user_key in attributed:
            continue
        attribution = _stored_attribution(metadata)
        if attribution is None:
            continue
        attributed[user_key] = attribution

    paid_users: set[str] = set()
    if attributed:
        paid_users = {
            str(user_id)
            for (user_id,) in (
                await db.execute(
                    select(Payment.user_id)
                    .where(
                        Payment.user_id.in_(list(attributed)),
                        Payment.status.in_(SETTLED_PAYMENT_STATUSES),
                    )
                    .distinct()
                )
            ).all()
            if user_id
        }

    for user_key, attribution in attributed.items():
        labels = {
            "source": _group_label(attribution, "utm_source", DIRECT_LABEL),
            "medium": _group_label(attribution, "utm_medium", UNSET_LABEL),
            "campaign": _group_label(attribution, "utm_campaign", UNSET_LABEL),
            "referrer": _group_label(attribution, "referrer_host", DIRECT_LABEL),
        }
        for dimension, label in labels.items():
            bucket = buckets[dimension][label]
            bucket.signups.add(user_key)
            if user_key in paid_users:
                bucket.paid.add(user_key)

    total_signup_count = (
        await db.execute(
            select(func.count(User.id)).where(
                User.created_at >= start_at,
                User.created_at < end_at,
            )
        )
    ).scalar() or 0

    by_dimension: dict[str, list[dict[str, Any]]] = {}
    suppressed: dict[str, int] = {}
    truncated: dict[str, int] = {}
    for dimension in dimensions:
        rows, hidden, cut = _rows_for(buckets[dimension])
        by_dimension[dimension] = rows
        suppressed[dimension] = hidden
        truncated[dimension] = cut

    attributed_count = len(attributed)
    paid_count = len(paid_users)
    return {
        "period": {
            "start": start_at.isoformat(),
            "end": end_at.isoformat(),
            "days": round((end_at - start_at).total_seconds() / 86_400, 2),
        },
        "minimum_cohort_size": MIN_COHORT_SIZE,
        "attribution_window_days": ATTRIBUTION_LOOKBACK_DAYS,
        "totals": {
            "sessions": len(total_sessions),
            "visitors": len(total_visitors),
            "signups": attributed_count,
            "paid_users": paid_count,
            "signup_conversion": min(100.0, _pct(attributed_count, len(total_visitors))),
            "paid_conversion": min(100.0, _pct(paid_count, attributed_count)),
        },
        "unattributed_signups": max(0, int(total_signup_count) - attributed_count),
        "by_source": by_dimension["source"],
        "by_medium": by_dimension["medium"],
        "by_campaign": by_dimension["campaign"],
        "by_referrer": by_dimension["referrer"],
        "suppressed": suppressed,
        "truncated": truncated,
        "notes": {
            "attribution": (
                "First-touch landing within the attribution window. Campaign values are "
                "server-stored allowlisted UTM labels; no raw IP, email, name, token, or "
                "full URL is stored."
            ),
            "suppression": (
                "Rows with fewer than 5 distinct visitors and 1-4 user conversion cells "
                "are hidden."
            ),
            "rates": (
                "signup_conversion is signups divided by distinct visitors; "
                "paid_conversion is distinct paid users divided by attributed signups."
            ),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
