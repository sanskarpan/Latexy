"""Privacy-safe public share and portfolio performance analytics (issue #2082).

Data boundary
-------------
Share metrics read ``resume_views`` rows, which already store a hashed viewer
session key, a validated country code, and a referrer host. Portfolio metrics
read first-party ``usage_analytics`` rows written only by the consent-gated
public portfolio capture routes. No raw IP address, user-agent string, email,
name, account id, share token, resume body, or free-form document text is
selected, stored, or returned by this module.

Suppression
-----------
A cohort with 1-4 distinct hashed viewers is never published. A group row whose
viewer cohort is smaller than five is omitted and counted in
``suppressed_groups``. A funnel or conversion cell whose numerator cohort is
smaller than five is replaced with ``null`` and named in ``suppressed_cells``.
Zero is always safe to publish.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Mapping
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..database import models
from .client_environment import normalize_country_code
from .traffic_source_service import sanitize_referrer_host

Resume = models.Resume
ResumeView = models.ResumeView
User = models.User
UsageAnalytics = models.UsageAnalytics

PORTFOLIO_VIEW_ACTION = "portfolio_view"
PORTFOLIO_CONTACT_ACTION = "portfolio_contact"
PORTFOLIO_SIGNUP_ACTION = "portfolio_signup"
PORTFOLIO_ACTIONS = (
    PORTFOLIO_VIEW_ACTION,
    PORTFOLIO_CONTACT_ACTION,
    PORTFOLIO_SIGNUP_ACTION,
)
PORTFOLIO_RESOURCE_TYPE = "portfolio"
PORTFOLIO_SOURCE = "public_portfolio"

MIN_COHORT_SIZE = 5
MAX_RANGE_DAYS = 366
MAX_SHARE_VIEW_ROWS = 200_000
MAX_PORTFOLIO_EVENT_ROWS = 200_000
MAX_GROUPS = 50
PORTFOLIO_ATTRIBUTION_LOOKBACK_DAYS = 30
SIGNUP_CLAIM_WINDOW_DAYS = 7
VIEW_DEBOUNCE_SECONDS = 300

UNKNOWN = "unknown"
DIRECT = "direct"

_USERNAME_PATTERN = re.compile(r"^[a-z0-9_-]{3,30}$")
_PLAN_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,49}$")
_VIEWER_KEY_PATTERN = re.compile(r"^[0-9a-f]{16}$")
_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def normalize_plan(value: str | None) -> str | None:
    """Validate the optional plan filter and return its canonical form."""

    if value is None or value == "":
        return None
    raw = str(value).strip().lower()
    if _PLAN_PATTERN.fullmatch(raw) is None:
        raise ValueError("plan must be a bounded lowercase plan identifier")
    return raw


def normalize_portfolio_username(value: str | None) -> str | None:
    """Validate an optional public portfolio username filter."""

    if value is None or value == "":
        return None
    raw = str(value).strip().lower()
    if _USERNAME_PATTERN.fullmatch(raw) is None:
        raise ValueError("portfolio username is invalid")
    return raw


def normalize_resume_id(value: str | None) -> str | None:
    """Validate an optional resume-id filter before it reaches a UUID column."""

    if value is None or value == "":
        return None
    raw = str(value).strip()
    if _UUID_PATTERN.fullmatch(raw) is None:
        raise ValueError("resume_id must be a UUID")
    return raw


def hash_viewer_key(ip: str | None, user_agent: str | None) -> str:
    """Return the same short, non-reversible viewer key used by share views.

    ``sha256(ip + user-agent)[:16]`` is deliberately lossy. The raw inputs are
    never returned, stored, or logged; the key only lets the report count
    distinct viewers and match a signup to an earlier portfolio visit.
    """

    raw_ip = (ip or UNKNOWN).strip() or UNKNOWN
    raw_user_agent = (user_agent or "").strip()
    return hashlib.sha256(f"{raw_ip}{raw_user_agent}".encode()).hexdigest()[:16]


def _request_ip(request: Any) -> str:
    """Return the peer address, honouring a trusted proxy when configured."""

    if getattr(settings, "TRUST_PROXY_HEADERS", False):
        try:
            from ..middleware.rate_limiting import client_ip_id

            return client_ip_id(request).removeprefix("ip:")
        except Exception:
            pass
    client = getattr(request, "client", None)
    host = getattr(client, "host", None) if client is not None else None
    return str(host or UNKNOWN)


def request_viewer_key(request: Any) -> str:
    """Derive the opaque viewer key for a request without keeping its inputs."""

    headers = getattr(request, "headers", {})
    user_agent = headers.get("user-agent", "") if headers is not None else ""
    return hash_viewer_key(_request_ip(request), user_agent)


def request_referrer_host(request: Any) -> str | None:
    """Return only the external referrer host from the request headers."""

    headers = getattr(request, "headers", {})
    if headers is None:
        return None
    raw = headers.get("referer") or headers.get("referrer")
    if not raw:
        return None
    try:
        return sanitize_referrer_host(raw)
    except (TypeError, ValueError):
        return None


def request_country_code(request: Any) -> str | None:
    """Return the server-validated country code, never a client claim."""

    from .client_environment import country_from_request

    return country_from_request(request)


def _resolve_period(
    *,
    days: int,
    start_date: date | None,
    end_date: date | None,
    now: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Return UTC ``[start, end)`` bounds for a relative or explicit range."""

    current = now or datetime.now(timezone.utc)
    if end_date is not None:
        end_at = datetime.combine(
            end_date + timedelta(days=1), time.min, tzinfo=timezone.utc
        )
    else:
        end_at = current
    if start_date is not None:
        start_at = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
    else:
        start_at = end_at - timedelta(days=max(1, min(int(days), MAX_RANGE_DAYS)))
    if start_at >= end_at:
        raise ValueError("start_date must be before end_date")
    if end_at - start_at > timedelta(days=MAX_RANGE_DAYS):
        raise ValueError("date range cannot exceed 366 days")
    return start_at, end_at


def _pct(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(min(100.0, (numerator / denominator) * 100), 2)


def _viewer_key_for_row(metadata: Any, event_id: Any) -> str:
    """Return a validated stored viewer key or a per-row fallback."""

    if isinstance(metadata, Mapping):
        stored = metadata.get("viewer_key")
        if isinstance(stored, str) and _VIEWER_KEY_PATTERN.fullmatch(stored):
            return f"v:{stored}"
    return f"e:{event_id}"


def _referrer_label(value: Any) -> str:
    """Reduce a stored referrer value to an external host-only label."""

    if not value:
        return DIRECT
    host = None
    try:
        parsed = urlsplit(str(value) if "://" in str(value) else f"//{str(value)}")
        host = parsed.hostname
    except Exception:
        host = None
    if not host:
        # Stored legacy values may be a bare host. Validate through the same
        # sanitizer before publishing anything.
        try:
            host = sanitize_referrer_host(value)
        except (TypeError, ValueError):
            host = None
    if not host:
        return DIRECT
    host = host.rstrip(".").lower()
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return host[:253]
    # An IP-shaped referrer is never published, matching the capture sanitizer.
    return DIRECT


def _country_label(value: Any) -> str:
    return normalize_country_code(value) or UNKNOWN


def _event_owner_id(row_id: Any, action: str, user_id: Any, metadata: Any) -> str | None:
    """Resolve the portfolio owner for one stored event without trusting PII."""

    if action in (PORTFOLIO_VIEW_ACTION, PORTFOLIO_CONTACT_ACTION):
        return str(user_id) if user_id else None
    if action == PORTFOLIO_SIGNUP_ACTION and isinstance(metadata, Mapping):
        owner_id = metadata.get("portfolio_owner_id")
        if isinstance(owner_id, str) and _UUID_PATTERN.fullmatch(owner_id):
            return owner_id
    return None


@dataclass(frozen=True)
class PortfolioOwner:
    """Minimal owner projection used by the analytics boundary."""

    id: str
    username: str | None
    enabled: bool


@dataclass
class _EventBucket:
    views: int = 0
    view_viewers: set[str] = field(default_factory=set)
    contacts: int = 0
    contact_viewers: set[str] = field(default_factory=set)
    signups: int = 0
    signup_viewers: set[str] = field(default_factory=set)


@dataclass
class _GroupBucket:
    views: int = 0
    viewers: set[str] = field(default_factory=set)


async def resolve_portfolio_owner(
    db: AsyncSession, username: str
) -> PortfolioOwner | None:
    """Find the owner of a public portfolio username without loading PII."""

    row = (
        await db.execute(
            select(User.id, User.public_username, User.portfolio_enabled).where(
                User.public_username == username.lower().strip()
            )
        )
    ).first()
    if row is None:
        return None
    owner_id, public_username, enabled = row
    return PortfolioOwner(
        id=str(owner_id),
        username=public_username,
        enabled=bool(enabled),
    )


async def _claim_debounce(key: str, ttl_seconds: int) -> bool:
    """Best-effort SET-NX debounce; analytics must never break the page."""

    try:
        from ..core.redis import get_redis_cache_client

        redis = await get_redis_cache_client()
        if redis is None:
            return True
        return bool(await redis.set(key, "1", ex=ttl_seconds, nx=True))
    except Exception:
        return True


def _event_metadata(
    *,
    owner: PortfolioOwner,
    viewer_key: str,
    referrer_host: str | None,
    country_code: str | None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "source": PORTFOLIO_SOURCE,
        "portfolio_username": owner.username,
        "portfolio_owner_id": str(owner.id),
        "viewer_key": viewer_key,
    }
    if referrer_host:
        metadata["referrer_host"] = referrer_host
    if country_code:
        metadata["country"] = country_code
    return metadata


async def record_portfolio_event(
    db: AsyncSession,
    *,
    action: str,
    username: str,
    request: Any,
    analytics_consent: bool,
) -> dict[str, Any]:
    """Persist one consent-gated portfolio view or contact event."""

    if action not in (PORTFOLIO_VIEW_ACTION, PORTFOLIO_CONTACT_ACTION):
        raise ValueError("unsupported portfolio event")
    if not analytics_consent:
        return {"recorded": False, "reason": "consent_required"}

    normalized = username.lower().strip()
    if _USERNAME_PATTERN.fullmatch(normalized) is None:
        raise ValueError("portfolio username is invalid")

    owner = await resolve_portfolio_owner(db, normalized)
    if owner is None or not owner.enabled:
        raise LookupError("portfolio not found")

    from .entitlement_service import entitlement_service

    if not await entitlement_service.has_feature("g12", user=owner.id):
        raise LookupError("portfolio not found")

    viewer_key = request_viewer_key(request)
    if action == PORTFOLIO_VIEW_ACTION:
        claimed = await _claim_debounce(
            f"portfolio:view:{normalized}:{viewer_key}",
            VIEW_DEBOUNCE_SECONDS,
        )
        if not claimed:
            return {"recorded": False, "reason": "debounced"}

    metadata = _event_metadata(
        owner=owner,
        viewer_key=viewer_key,
        referrer_host=request_referrer_host(request),
        country_code=request_country_code(request),
    )
    try:
        db.add(
            UsageAnalytics(
                user_id=owner.id,
                device_fingerprint=None,
                action=action,
                resource_type=PORTFOLIO_RESOURCE_TYPE,
                event_metadata=metadata,
                ip_address=None,
                user_agent=None,
            )
        )
        await db.commit()
    except Exception:
        await db.rollback()
        return {"recorded": False, "reason": "unavailable"}
    return {"recorded": True, "action": action}


async def claim_portfolio_signup(
    db: AsyncSession,
    *,
    user_id: str,
    request: Any,
    analytics_consent: bool,
) -> dict[str, Any]:
    """Match a new account to its consent-gated portfolio visit.

    The match uses the same short viewer key as the public capture. Only the
    owner id and public username are copied, never a visitor identifier, IP,
    user-agent, email, or name. The claim is one row per account.
    """

    if not analytics_consent:
        return {"recorded": False, "reason": "consent_required"}

    user_row = (
        await db.execute(
            select(User.id, User.created_at).where(User.id == user_id)
        )
    ).first()
    if user_row is None:
        return {"recorded": False, "reason": "no_user"}
    now = datetime.now(timezone.utc)
    created_at = user_row[1]
    if created_at is not None:
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        if now - created_at > timedelta(days=SIGNUP_CLAIM_WINDOW_DAYS):
            return {"recorded": False, "reason": "outside_signup_window"}

    viewer_key = request_viewer_key(request)
    cutoff = now - timedelta(days=PORTFOLIO_ATTRIBUTION_LOOKBACK_DAYS)

    # Serialize duplicate claims for one account without a new table or unique
    # index. The lock is released with this transaction.
    try:
        from sqlalchemy import text

        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"portfolio-signup:{user_id}"},
        )
    except Exception:
        await db.rollback()

    existing = (
        await db.execute(
            select(UsageAnalytics.id)
            .where(
                UsageAnalytics.action == PORTFOLIO_SIGNUP_ACTION,
                UsageAnalytics.user_id == user_id,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return {"recorded": False, "reason": "already_attributed"}

    view_stmt = select(UsageAnalytics.event_metadata).where(
        UsageAnalytics.action == PORTFOLIO_VIEW_ACTION,
        UsageAnalytics.created_at >= cutoff,
        UsageAnalytics.event_metadata["viewer_key"].as_string() == viewer_key,
    )
    if created_at is not None:
        # Only a visit before account creation can explain the signup; a later
        # portfolio visit must not retroactively attribute an existing account.
        view_stmt = view_stmt.where(UsageAnalytics.created_at <= created_at)
    view = (
        await db.execute(
            view_stmt.order_by(UsageAnalytics.created_at.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if not isinstance(view, Mapping):
        return {"recorded": False, "reason": "no_portfolio_view"}

    owner_id = view.get("portfolio_owner_id")
    owner_username = view.get("portfolio_username")
    if not isinstance(owner_id, str) or _UUID_PATTERN.fullmatch(owner_id) is None:
        return {"recorded": False, "reason": "no_portfolio_view"}
    if not isinstance(owner_username, str) or _USERNAME_PATTERN.fullmatch(
        owner_username
    ) is None:
        return {"recorded": False, "reason": "no_portfolio_view"}

    metadata = {
        "source": PORTFOLIO_SOURCE,
        "portfolio_username": owner_username,
        "portfolio_owner_id": owner_id,
        "viewer_key": viewer_key,
    }
    try:
        db.add(
            UsageAnalytics(
                user_id=user_id,
                device_fingerprint=None,
                action=PORTFOLIO_SIGNUP_ACTION,
                resource_type=PORTFOLIO_RESOURCE_TYPE,
                event_metadata=metadata,
                ip_address=None,
                user_agent=None,
            )
        )
        await db.commit()
    except Exception:
        await db.rollback()
        return {"recorded": False, "reason": "unavailable"}
    return {"recorded": True, "reason": "attributed"}


async def _load_share_rows(
    db: AsyncSession,
    *,
    start_at: datetime,
    end_at: datetime,
    plan: str | None,
    portfolio_owner_id: str | None,
    resume_id: str | None,
) -> list[Any]:
    stmt = (
        select(
            ResumeView.id,
            ResumeView.resume_id,
            ResumeView.country_code,
            ResumeView.referrer,
            ResumeView.session_id,
            Resume.user_id,
        )
        .join(Resume, Resume.id == ResumeView.resume_id)
        .join(User, User.id == Resume.user_id)
        .where(
            ResumeView.viewed_at >= start_at,
            ResumeView.viewed_at < end_at,
        )
    )
    if plan:
        stmt = stmt.where(User.subscription_plan == plan)
    if portfolio_owner_id:
        stmt = stmt.where(Resume.user_id == portfolio_owner_id)
    if resume_id:
        stmt = stmt.where(ResumeView.resume_id == resume_id)
    stmt = stmt.order_by(ResumeView.viewed_at.asc()).limit(MAX_SHARE_VIEW_ROWS)
    return (await db.execute(stmt)).all()


async def _active_share_links(
    db: AsyncSession,
    *,
    start_at: datetime,
    end_at: datetime,
    plan: str | None,
    portfolio_owner_id: str | None,
    resume_id: str | None,
) -> int:
    stmt = (
        select(func.count(Resume.id))
        .join(User, User.id == Resume.user_id)
        .where(
            Resume.share_token.is_not(None),
            Resume.share_token_created_at >= start_at,
            Resume.share_token_created_at < end_at,
        )
    )
    if plan:
        stmt = stmt.where(User.subscription_plan == plan)
    if portfolio_owner_id:
        stmt = stmt.where(Resume.user_id == portfolio_owner_id)
    if resume_id:
        stmt = stmt.where(Resume.id == resume_id)
    return int((await db.execute(stmt)).scalar_one() or 0)


def _group_rows(
    buckets: Mapping[str, _GroupBucket],
    *,
    label_key: str,
) -> tuple[list[dict[str, Any]], int, int]:
    rows: list[dict[str, Any]] = []
    suppressed = 0
    ordered = sorted(
        buckets.items(),
        key=lambda item: (-item[1].views, -len(item[1].viewers), item[0]),
    )
    for label, bucket in ordered:
        viewers = len(bucket.viewers)
        if viewers < MIN_COHORT_SIZE:
            suppressed += 1
            continue
        rows.append(
            {
                label_key: label,
                "views": bucket.views,
                "unique_viewers": viewers,
            }
        )
    truncated = max(0, len(rows) - MAX_GROUPS)
    return rows[:MAX_GROUPS], suppressed, truncated


def _share_payload(
    rows: list[Any],
    *,
    active_share_links: int,
) -> dict[str, Any]:
    total_views = 0
    total_viewers: set[str] = set()
    by_resume: dict[str, _GroupBucket] = defaultdict(_GroupBucket)
    by_country: dict[str, _GroupBucket] = defaultdict(_GroupBucket)
    by_referrer: dict[str, _GroupBucket] = defaultdict(_GroupBucket)
    truncated_events = len(rows) >= MAX_SHARE_VIEW_ROWS

    for row in rows:
        row_id, resume_id, country_code, referrer, session_id, _owner_id = row
        viewer = f"s:{session_id}" if session_id else f"e:{row_id}"
        country = _country_label(country_code)
        referrer_label = _referrer_label(referrer)

        total_views += 1
        total_viewers.add(viewer)
        for bucket in (
            by_resume[str(resume_id)],
            by_country[country],
            by_referrer[referrer_label],
        ):
            bucket.views += 1
            bucket.viewers.add(viewer)

    unique_viewers = len(total_viewers)
    viewed_share_links = len(by_resume)
    summary_suppressed = 0 < unique_viewers < MIN_COHORT_SIZE
    suppressed_cells: list[str] = []

    if summary_suppressed:
        visible_views = None
        visible_viewers = None
        visible_viewed_links = None
        suppressed_cells.extend(
            ("views", "unique_viewers", "viewed_share_links", "repeat_views")
        )
    else:
        visible_views = total_views
        visible_viewers = unique_viewers
        visible_viewed_links = viewed_share_links

    repeat_views = total_views - unique_viewers
    repeat_view_rate = _pct(repeat_views, total_views)
    if summary_suppressed:
        repeat_view_rate = None
    share_link_rate = _pct(viewed_share_links, active_share_links)
    if summary_suppressed:
        share_link_rate = None
        suppressed_cells.extend(("share_link_rate",))

    resume_rows, resume_suppressed, resume_truncated = _group_rows(
        by_resume, label_key="resume_id"
    )
    country_rows, country_suppressed, country_truncated = _group_rows(
        by_country, label_key="country_code"
    )
    referrer_rows, referrer_suppressed, referrer_truncated = _group_rows(
        by_referrer, label_key="referrer"
    )

    return {
        "summary": {
            "active_share_links": active_share_links,
            "viewed_share_links": visible_viewed_links,
            "views": visible_views,
            "unique_viewers": visible_viewers,
            "repeat_views": None if summary_suppressed else repeat_views,
            "repeat_view_rate_pct": repeat_view_rate,
            "share_link_view_rate_pct": share_link_rate,
            "views_per_viewed_link": (
                None
                if summary_suppressed or viewed_share_links == 0
                else round(total_views / viewed_share_links, 2)
            ),
            "suppressed": summary_suppressed,
            "suppressed_cells": sorted(set(suppressed_cells)),
        },
        "conversion": {
            "definition": (
                "Share links with at least one view divided by share links created "
                "during the selected period and still active."
            ),
            "numerator": None if summary_suppressed else viewed_share_links,
            "denominator": active_share_links,
            "rate_pct": share_link_rate,
            "suppressed": summary_suppressed,
        },
        "by_referrer": referrer_rows,
        "by_country": country_rows,
        "by_resume": resume_rows,
        "suppressed_groups": {
            "referrer": referrer_suppressed,
            "country": country_suppressed,
            "resume": resume_suppressed,
        },
        "truncated_groups": {
            "referrer": referrer_truncated,
            "country": country_truncated,
            "resume": resume_truncated,
        },
        "truncated_events": truncated_events,
    }


def _portfolio_payload(
    rows: list[Any],
    *,
    owner_map: Mapping[str, dict[str, Any]],
    plan: str | None,
    portfolio_owner_id: str | None,
) -> dict[str, Any]:
    total = _EventBucket()
    by_owner: dict[str, _EventBucket] = defaultdict(_EventBucket)
    by_country: dict[str, _GroupBucket] = defaultdict(_GroupBucket)
    by_referrer: dict[str, _GroupBucket] = defaultdict(_GroupBucket)
    truncated_events = len(rows) >= MAX_PORTFOLIO_EVENT_ROWS

    for row_id, user_id, action, _created_at, metadata in rows:
        owner_id = _event_owner_id(row_id, action, user_id, metadata)
        if not owner_id:
            continue
        owner = owner_map.get(owner_id)
        if plan and (owner is None or owner.get("plan") != plan):
            continue
        if portfolio_owner_id and owner_id != portfolio_owner_id:
            continue
        if owner is None:
            continue

        viewer = _viewer_key_for_row(metadata, row_id)
        owner_bucket = by_owner[owner_id]
        if action == PORTFOLIO_VIEW_ACTION:
            total.views += 1
            total.view_viewers.add(viewer)
            owner_bucket.views += 1
            owner_bucket.view_viewers.add(viewer)
            safe_metadata = metadata if isinstance(metadata, Mapping) else {}
            country = _country_label(safe_metadata.get("country"))
            referrer = _referrer_label(safe_metadata.get("referrer_host"))
            by_country[country].views += 1
            by_country[country].viewers.add(viewer)
            by_referrer[referrer].views += 1
            by_referrer[referrer].viewers.add(viewer)
        elif action == PORTFOLIO_CONTACT_ACTION:
            total.contacts += 1
            total.contact_viewers.add(viewer)
            owner_bucket.contacts += 1
            owner_bucket.contact_viewers.add(viewer)
        elif action == PORTFOLIO_SIGNUP_ACTION:
            total.signups += 1
            total.signup_viewers.add(viewer)
            owner_bucket.signups += 1
            owner_bucket.signup_viewers.add(viewer)

    unique_viewers = len(total.view_viewers)
    contacters = total.contact_viewers & total.view_viewers
    signupers = total.signup_viewers & contacters
    unique_contacts = len(contacters)
    unique_signups = len(signupers)

    summary_suppressed = 0 < unique_viewers < MIN_COHORT_SIZE
    suppressed_cells: list[str] = []
    if summary_suppressed:
        suppressed_cells.extend(
            ("views", "unique_viewers", "contact_events", "signups")
        )

    contact_suppressed = summary_suppressed or (
        0 < unique_contacts < MIN_COHORT_SIZE
    )
    if contact_suppressed and not summary_suppressed:
        suppressed_cells.extend(
            ("contact_events", "unique_contact_viewers", "contact_rate")
        )
    signup_suppressed = contact_suppressed or (
        0 < unique_signups < MIN_COHORT_SIZE
    )
    if signup_suppressed:
        suppressed_cells.extend(
            ("signups", "unique_signup_viewers", "signup_rate")
        )

    def _visible(value: int, hidden: bool) -> int | None:
        return None if hidden else value

    visible_views = _visible(total.views, summary_suppressed)
    visible_unique = _visible(unique_viewers, summary_suppressed)
    visible_contacts = _visible(len(contacters), contact_suppressed)
    visible_contact_events = _visible(total.contacts, contact_suppressed)
    visible_signups = _visible(unique_signups, signup_suppressed)
    visible_signup_events = _visible(total.signups, signup_suppressed)

    contact_rate = (
        None if contact_suppressed else _pct(len(contacters), unique_viewers)
    )
    signup_rate = (
        None if signup_suppressed else _pct(len(signupers), unique_contacts)
    )
    view_to_signup_rate = (
        None if signup_suppressed else _pct(len(signupers), unique_viewers)
    )

    funnel_steps = [
        {
            "step": "portfolio_views",
            "label": "Portfolio views",
            "count": visible_views,
            "unique_viewers": visible_unique,
            "denominator": "portfolio page views",
            "denominator_value": visible_views,
            "conversion_from_previous_pct": None,
            "conversion_from_start_pct": None if summary_suppressed else 100.0,
            "suppressed": summary_suppressed,
        },
        {
            "step": "contact",
            "label": "Contact",
            "count": visible_contact_events,
            "unique_viewers": visible_contacts,
            "denominator": "unique portfolio viewers",
            "denominator_value": visible_unique,
            "conversion_from_previous_pct": contact_rate,
            "conversion_from_start_pct": contact_rate,
            "suppressed": contact_suppressed,
        },
        {
            "step": "signup",
            "label": "Signup",
            "count": visible_signup_events,
            "unique_viewers": visible_signups,
            "denominator": "unique contact viewers",
            "denominator_value": visible_contacts,
            "conversion_from_previous_pct": signup_rate,
            "conversion_from_start_pct": view_to_signup_rate,
            "suppressed": signup_suppressed,
        },
    ]

    owner_rows: list[dict[str, Any]] = []
    suppressed_owners = 0
    ordered_owners = sorted(
        by_owner.items(),
        key=lambda item: (
            -item[1].views,
            -len(item[1].view_viewers),
            owner_map.get(item[0], {}).get("username") or item[0],
        ),
    )
    for owner_id, bucket in ordered_owners:
        owner_viewers = len(bucket.view_viewers)
        if owner_viewers < MIN_COHORT_SIZE:
            suppressed_owners += 1
            continue
        owner_contacts = bucket.contact_viewers & bucket.view_viewers
        owner_signups = bucket.signup_viewers & owner_contacts
        owner_contact_suppressed = 0 < len(owner_contacts) < MIN_COHORT_SIZE
        owner_signup_suppressed = owner_contact_suppressed or (
            0 < len(owner_signups) < MIN_COHORT_SIZE
        )
        owner_cells: list[str] = []
        if owner_contact_suppressed:
            owner_cells.extend(("contact_events", "unique_contact_viewers"))
        if owner_signup_suppressed:
            owner_cells.extend(("signups", "unique_signup_viewers"))
        owner = owner_map.get(owner_id, {})
        owner_rows.append(
            {
                "portfolio_username": owner.get("username") or UNKNOWN,
                "views": bucket.views,
                "unique_viewers": owner_viewers,
                "contact_events": (
                    None
                    if owner_contact_suppressed
                    else bucket.contacts
                ),
                "unique_contact_viewers": (
                    None if owner_contact_suppressed else len(owner_contacts)
                ),
                "signups": None if owner_signup_suppressed else len(owner_signups),
                "unique_signup_viewers": (
                    None if owner_signup_suppressed else len(owner_signups)
                ),
                "contact_rate_pct": (
                    None
                    if owner_contact_suppressed
                    else _pct(len(owner_contacts), owner_viewers)
                ),
                "signup_rate_pct": (
                    None
                    if owner_signup_suppressed
                    else _pct(len(owner_signups), len(owner_contacts))
                ),
                "suppressed_cells": sorted(set(owner_cells)),
            }
        )
    truncated_owners = max(0, len(owner_rows) - MAX_GROUPS)
    owner_rows = owner_rows[:MAX_GROUPS]

    country_rows, country_suppressed, country_truncated = _group_rows(
        by_country, label_key="country_code"
    )
    referrer_rows, referrer_suppressed, referrer_truncated = _group_rows(
        by_referrer, label_key="referrer"
    )

    return {
        "summary": {
            "views": visible_views,
            "unique_viewers": visible_unique,
            "contact_events": visible_contact_events,
            "unique_contact_viewers": visible_contacts,
            "signups": visible_signup_events,
            "unique_signup_viewers": visible_signups,
            "contact_rate_pct": contact_rate,
            "signup_rate_pct": signup_rate,
            "view_to_signup_rate_pct": view_to_signup_rate,
            "suppressed": summary_suppressed,
            "suppressed_cells": sorted(set(suppressed_cells)),
        },
        "funnel": {
            "steps": funnel_steps,
            "denominators": {
                "views": {
                    "label": "Portfolio page views",
                    "value": visible_views,
                },
                "unique_viewers": {
                    "label": "Distinct hashed portfolio viewers",
                    "value": visible_unique,
                },
                "contact_viewers": {
                    "label": "Distinct viewers who contacted after viewing",
                    "value": visible_contacts,
                },
                "signup_viewers": {
                    "label": "Distinct contacted viewers who signed up",
                    "value": visible_signups,
                },
            },
            "definition": (
                "Strictly ordered unique-viewer funnel: a contact must follow a "
                "portfolio view, and a signup must follow the contact. Counts are "
                "event counts; conversions use the stated unique-viewer denominator."
            ),
        },
        "by_referrer": referrer_rows,
        "by_country": country_rows,
        "by_portfolio": owner_rows,
        "suppressed_groups": {
            "referrer": referrer_suppressed,
            "country": country_suppressed,
            "portfolio": suppressed_owners,
        },
        "truncated_groups": {
            "referrer": referrer_truncated,
            "country": country_truncated,
            "portfolio": truncated_owners,
        },
        "truncated_events": truncated_events,
    }


async def _owner_map(
    db: AsyncSession, owner_ids: set[str]
) -> dict[str, dict[str, Any]]:
    if not owner_ids:
        return {}
    rows = (
        await db.execute(
            select(User.id, User.public_username, User.subscription_plan).where(
                User.id.in_(list(owner_ids))
            )
        )
    ).all()
    return {
        str(user_id): {
            "username": username,
            "plan": plan,
        }
        for user_id, username, plan in rows
    }


async def aggregate(
    db: AsyncSession,
    *,
    days: int = 30,
    start_date: date | None = None,
    end_date: date | None = None,
    plan: str | None = None,
    portfolio: str | None = None,
    resume_id: str | None = None,
    include_portfolio: bool = True,
) -> dict[str, Any]:
    """Return aggregate share and portfolio performance for the admin report."""

    start_at, end_at = _resolve_period(
        days=days, start_date=start_date, end_date=end_date
    )
    canonical_plan = normalize_plan(plan)
    canonical_portfolio = normalize_portfolio_username(portfolio)
    canonical_resume_id = normalize_resume_id(resume_id)

    portfolio_owner_id: str | None = None
    portfolio_owner: PortfolioOwner | None = None
    if canonical_portfolio is not None:
        portfolio_owner = await resolve_portfolio_owner(db, canonical_portfolio)
        if portfolio_owner is None:
            raise LookupError("portfolio not found")
        portfolio_owner_id = str(portfolio_owner.id)

    share_rows = await _load_share_rows(
        db,
        start_at=start_at,
        end_at=end_at,
        plan=canonical_plan,
        portfolio_owner_id=portfolio_owner_id,
        resume_id=canonical_resume_id,
    )
    active_links = await _active_share_links(
        db,
        start_at=start_at,
        end_at=end_at,
        plan=canonical_plan,
        portfolio_owner_id=portfolio_owner_id,
        resume_id=canonical_resume_id,
    )
    share_payload = _share_payload(share_rows, active_share_links=active_links)

    if include_portfolio and canonical_resume_id is None:
        event_rows = (
            await db.execute(
                select(
                    UsageAnalytics.id,
                    UsageAnalytics.user_id,
                    UsageAnalytics.action,
                    UsageAnalytics.created_at,
                    UsageAnalytics.event_metadata,
                )
                .where(
                    UsageAnalytics.action.in_(PORTFOLIO_ACTIONS),
                    UsageAnalytics.created_at >= start_at,
                    UsageAnalytics.created_at < end_at,
                )
                .order_by(UsageAnalytics.created_at.asc())
                .limit(MAX_PORTFOLIO_EVENT_ROWS)
            )
        ).all()
        owner_ids: set[str] = set()
        for row_id, user_id, action, _created_at, metadata in event_rows:
            owner_id = _event_owner_id(row_id, action, user_id, metadata)
            if owner_id:
                owner_ids.add(owner_id)
        owners = await _owner_map(db, owner_ids)
        portfolio_payload: dict[str, Any] | None = _portfolio_payload(
            event_rows,
            owner_map=owners,
            plan=canonical_plan,
            portfolio_owner_id=portfolio_owner_id,
        )
    else:
        portfolio_payload = None

    return {
        "period": {
            "start": start_at.isoformat(),
            "end": end_at.isoformat(),
            "days": round((end_at - start_at).total_seconds() / 86_400, 2),
            "timezone": "UTC",
        },
        "filters": {
            "plan": canonical_plan,
            "portfolio": canonical_portfolio,
            "resume_id": canonical_resume_id,
        },
        "minimum_cohort_size": MIN_COHORT_SIZE,
        "share": share_payload,
        "portfolio": portfolio_payload,
        "notes": {
            "share_source": (
                "resume_views rows joined to their resume and owner; the stored "
                "viewer key is a truncated SHA-256 of IP and user-agent and is "
                "never returned."
            ),
            "portfolio_source": (
                "Consent-gated first-party portfolio_view, portfolio_contact and "
                "portfolio_signup rows in usage_analytics. No raw IP, user-agent, "
                "viewer identifier, email, name, or document content is stored or "
                "returned."
            ),
            "geography": (
                "Country is an ISO 3166-1 alpha-2 code or 'unknown'. No city, "
                "region, or raw IP is stored or returned."
            ),
            "plan": (
                "The plan filter matches the owning account's current "
                "subscription plan at report time."
            ),
            "suppression": (
                "Groups with fewer than 5 distinct hashed viewers are omitted. "
                "Counts of 1-4 in a funnel or conversion cell are hidden and named "
                "in suppressed_cells. Zero is always visible."
            ),
            "consent": (
                "Portfolio capture is written only after the visitor grants "
                "analytics consent; denial or withdrawal leaves no new analytics row."
            ),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


async def resume_breakdown(
    db: AsyncSession,
    *,
    resume_id: str,
    days: int = 30,
    start_date: date | None = None,
    end_date: date | None = None,
    plan: str | None = None,
) -> dict[str, Any]:
    """Return one resume's share breakdown with the same suppression rules."""

    result = await aggregate(
        db,
        days=days,
        start_date=start_date,
        end_date=end_date,
        plan=plan,
        resume_id=normalize_resume_id(resume_id),
        include_portfolio=False,
    )
    return {
        "period": result["period"],
        "filters": result["filters"],
        "minimum_cohort_size": result["minimum_cohort_size"],
        "resume_id": result["filters"]["resume_id"],
        "share": result["share"],
        "notes": result["notes"],
        "generated_at": result["generated_at"],
    }


async def portfolio_breakdown(
    db: AsyncSession,
    *,
    username: str,
    days: int = 30,
    start_date: date | None = None,
    end_date: date | None = None,
    plan: str | None = None,
) -> dict[str, Any]:
    """Return one portfolio's share and portfolio breakdown."""

    result = await aggregate(
        db,
        days=days,
        start_date=start_date,
        end_date=end_date,
        plan=plan,
        portfolio=username,
        include_portfolio=True,
    )
    return {
        "period": result["period"],
        "filters": result["filters"],
        "minimum_cohort_size": result["minimum_cohort_size"],
        "portfolio_username": normalize_portfolio_username(username),
        "share": result["share"],
        "portfolio": result["portfolio"],
        "notes": result["notes"],
        "generated_at": result["generated_at"],
    }
