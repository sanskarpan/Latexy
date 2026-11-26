"""Privacy-safe device, browser, OS and country breakdowns (issue #2069).

Data boundary
-------------
The report reads only first-party, server-owned data:

* ``usage_analytics`` page-view rows for the selected period, using the stored
  user agent solely as input to the bounded parser in
  :mod:`app.services.client_environment`; and
* ``users.created_at`` for signups, with each signup's earliest event used to
  choose an aggregate bucket.

Only fixed device/browser/OS labels and validated ISO alpha-2 country codes
leave this module. Raw IP addresses, full user-agent strings, cities, regions,
account ids and per-user location histories are never returned. Signup
attribution is computed transiently and is not persisted as a profile.

Suppression
-----------
A page-view/session cell with 1-4 distinct sessions is hidden, and a signup
cell with 1-4 users is hidden. A row whose every cell is hidden is omitted
entirely. The response reports only how many rows/cells were suppressed.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Mapping

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import models
from .client_environment import (
    BROWSER_FAMILIES,
    BROWSER_LABELS,
    COUNTRY_LABEL,
    DEVICE_CLASSES,
    DEVICE_LABELS,
    OS_FAMILIES,
    OS_LABELS,
    UNKNOWN_COUNTRY,
    country_from_metadata,
    parse_user_agent,
)

UsageAnalytics = models.UsageAnalytics
User = models.User

PAGE_VIEW_ACTION = "page_view"
MIN_COHORT_SIZE = 5
MAX_GROUPS = 50
MAX_PAGE_VIEW_ROWS = 100_000
MAX_RANGE_DAYS = 366
SIGNUP_LOOKBACK_DAYS = 30
UNKNOWN = "unknown"

# (response key, human label, bounded supported values)
DIMENSIONS: tuple[tuple[str, str, tuple[str, ...] | None], ...] = (
    ("device", "Device class", DEVICE_CLASSES),
    ("browser", "Browser family", BROWSER_FAMILIES),
    ("os", "OS family", OS_FAMILIES),
    ("country", COUNTRY_LABEL, None),
)


def _resolve_period(
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
    if end_at - start_at > timedelta(days=MAX_RANGE_DAYS):
        raise ValueError("date range cannot exceed 366 days")
    return start_at, end_at


def _session_key(event_id: Any, device_fingerprint: str | None, metadata: Any) -> str:
    """An opaque grouping key for sessions; never returned to a caller."""

    if isinstance(metadata, Mapping):
        session_id = metadata.get("session_id")
        if isinstance(session_id, str) and session_id:
            return f"s:{session_id}"
    if device_fingerprint:
        return f"d:{device_fingerprint}"
    return f"e:{event_id}"


def _labels_for(user_agent: str | None, metadata: Any) -> dict[str, str]:
    environment = parse_user_agent(user_agent)
    return {
        "device": environment["device_class"],
        "browser": environment["browser_family"],
        "os": environment["os_family"],
        "country": country_from_metadata(metadata) or UNKNOWN_COUNTRY,
    }


def _new_bucket() -> dict[str, Any]:
    return {"page_views": 0, "sessions": set(), "signups": 0}


def _row(value: str, label: str, bucket: Mapping[str, Any]) -> tuple[dict[str, Any] | None, int]:
    """Build one suppressed row; return ``(row, hidden_cell_count)``."""

    page_views = int(bucket.get("page_views", 0))
    sessions = len(bucket.get("sessions") or ())
    signups = int(bucket.get("signups", 0))
    suppressed_cells: list[str] = []

    if sessions > 0 and sessions < MIN_COHORT_SIZE:
        visible_page_views: int | None = None
        visible_sessions: int | None = None
        suppressed_cells.extend(("page_views", "sessions"))
    else:
        visible_page_views = page_views
        visible_sessions = sessions

    if signups > 0 and signups < MIN_COHORT_SIZE:
        visible_signups: int | None = None
        suppressed_cells.append("signups")
    else:
        visible_signups = signups

    if visible_page_views is None and not visible_signups:
        return None, len(suppressed_cells)

    conversion: float | None = None
    if visible_signups is not None and visible_sessions is not None and visible_sessions > 0:
        # Attribution is capped at the session denominator so a historical
        # first event outside the period can never produce an impossible rate.
        conversion = min(100.0, round((visible_signups / visible_sessions) * 100, 2))

    return (
        {
            "value": value,
            "label": label,
            "page_views": visible_page_views,
            "sessions": visible_sessions,
            "signups": visible_signups,
            "signup_conversion": conversion,
            "suppressed_cells": suppressed_cells,
        },
        len(suppressed_cells),
    )


def _dimension_payload(
    key: str,
    title: str,
    supported: tuple[str, ...] | None,
    buckets: Mapping[str, Mapping[str, Any]],
    labels: Mapping[str, str],
) -> tuple[dict[str, Any], int, int]:
    rows: list[dict[str, Any]] = []
    suppressed_rows = 0
    suppressed_cells = 0

    ordered = sorted(
        buckets.items(),
        key=lambda item: (
            item[0] == UNKNOWN or item[0] == UNKNOWN_COUNTRY,
            -max(int(item[1].get("page_views", 0)), int(item[1].get("signups", 0))),
            item[0],
        ),
    )
    for value, bucket in ordered:
        label = labels.get(value, value if value != UNKNOWN else "Unknown")
        if value == UNKNOWN_COUNTRY:
            label = "Unknown country"
        row, hidden_cells = _row(value, label, bucket)
        if row is None:
            suppressed_rows += 1
            suppressed_cells += hidden_cells
            continue
        suppressed_cells += hidden_cells
        rows.append(row)

    truncated = max(0, len(rows) - MAX_GROUPS)
    return (
        {
            "key": key,
            "label": title,
            "supported_values": list(supported) if supported else None,
            "rows": rows[:MAX_GROUPS],
            "suppressed_rows": suppressed_rows,
            "truncated_rows": truncated,
            "unknown_label": "Unknown country" if key == "country" else labels.get(UNKNOWN, "Unknown"),
        },
        suppressed_rows,
        suppressed_cells,
    )


class AdminPrivacyBreakdownService:
    """Aggregate-only device/browser/OS/country report for the Growth view."""

    async def snapshot(
        self,
        db: AsyncSession,
        *,
        days: int = 30,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, Any]:
        start_at, end_at = _resolve_period(days=days, start_date=start_date, end_date=end_date)

        buckets: dict[str, dict[str, dict[str, Any]]] = {
            key: defaultdict(_new_bucket) for key, _title, _supported in DIMENSIONS
        }
        all_sessions: set[str] = set()

        page_view_rows = (
            await db.execute(
                select(
                    UsageAnalytics.id,
                    UsageAnalytics.device_fingerprint,
                    UsageAnalytics.user_agent,
                    UsageAnalytics.event_metadata,
                )
                .where(
                    UsageAnalytics.action == PAGE_VIEW_ACTION,
                    UsageAnalytics.created_at >= start_at,
                    UsageAnalytics.created_at < end_at,
                )
                .order_by(UsageAnalytics.created_at.asc())
                .limit(MAX_PAGE_VIEW_ROWS + 1)
            )
        ).all()
        truncated_page_views = len(page_view_rows) > MAX_PAGE_VIEW_ROWS
        page_view_rows = page_view_rows[:MAX_PAGE_VIEW_ROWS]

        for row_id, device_fingerprint, user_agent, metadata in page_view_rows:
            session_key = _session_key(row_id, device_fingerprint, metadata)
            all_sessions.add(session_key)
            for key, value in _labels_for(user_agent, metadata).items():
                bucket = buckets[key][value]
                bucket["page_views"] += 1
                bucket["sessions"].add(session_key)

        signup_filter = (
            User.created_at >= start_at,
            User.created_at < end_at,
        )
        signup_total = (await db.execute(select(func.count(User.id)).where(*signup_filter))).scalar_one()

        # One earliest event per signup decides its aggregate bucket. The
        # event's user id stays inside this query; only labels and counts are
        # aggregated below.
        ranked_events = (
            select(
                UsageAnalytics.user_agent,
                UsageAnalytics.event_metadata,
                func.row_number()
                .over(
                    partition_by=UsageAnalytics.user_id,
                    order_by=(UsageAnalytics.created_at.asc(), UsageAnalytics.id.asc()),
                )
                .label("rank"),
            )
            .where(
                UsageAnalytics.user_id.in_(select(User.id).where(*signup_filter)),
                UsageAnalytics.created_at >= start_at - timedelta(days=SIGNUP_LOOKBACK_DAYS),
                UsageAnalytics.created_at < end_at,
            )
            .subquery()
        )
        first_event_rows = (
            await db.execute(
                select(ranked_events.c.user_agent, ranked_events.c.event_metadata).where(ranked_events.c.rank == 1)
            )
        ).all()

        attributed_signups = len(first_event_rows)
        for user_agent, metadata in first_event_rows:
            for key, value in _labels_for(user_agent, metadata).items():
                buckets[key][value]["signups"] += 1

        # Signups with no event in the lookback window are still counted and
        # bucketed as unknown rather than silently dropped.
        unattributed_signups = max(0, signup_total - attributed_signups)
        if unattributed_signups:
            for key, _title, _supported in DIMENSIONS:
                buckets[key][UNKNOWN if key != "country" else UNKNOWN_COUNTRY]["signups"] += unattributed_signups

        dimension_payloads: dict[str, Any] = {}
        suppressed_rows = 0
        suppressed_cells = 0
        for key, title, supported in DIMENSIONS:
            labels = {
                "device": DEVICE_LABELS,
                "browser": BROWSER_LABELS,
                "os": OS_LABELS,
                "country": {},
            }[key]
            payload, hidden_rows, hidden_cells = _dimension_payload(key, title, supported, buckets[key], labels)
            dimension_payloads[key] = payload
            suppressed_rows += hidden_rows
            suppressed_cells += hidden_cells

        summary_suppressed_cells: list[str] = []
        if 0 < signup_total < MIN_COHORT_SIZE:
            visible_signup_total: int | None = None
            summary_suppressed_cells.append("signups")
        else:
            visible_signup_total = signup_total

        total_sessions = len(all_sessions)
        signup_conversion: float | None = None
        if visible_signup_total is not None and total_sessions > 0:
            signup_conversion = min(100.0, round((visible_signup_total / total_sessions) * 100, 2))

        attributed_display: int | None = attributed_signups
        unattributed_display: int | None = unattributed_signups
        if 0 < attributed_signups < MIN_COHORT_SIZE:
            attributed_display = None
            summary_suppressed_cells.append("attributed_signups")
        if 0 < unattributed_signups < MIN_COHORT_SIZE:
            unattributed_display = None
            summary_suppressed_cells.append("unattributed_signups")
        if summary_suppressed_cells:
            suppressed_cells += len(summary_suppressed_cells)

        return {
            "days": days,
            "period": {
                "start": start_at.isoformat(),
                "end": end_at.isoformat(),
                "timezone": "UTC",
            },
            "minimum_cohort_size": MIN_COHORT_SIZE,
            "summary": {
                "page_views": len(page_view_rows),
                "sessions": total_sessions,
                "signups": visible_signup_total,
                "signup_conversion": signup_conversion,
                "suppressed_cells": summary_suppressed_cells,
            },
            "signup_attribution": {
                "attributed": attributed_display,
                "unattributed": unattributed_display,
                "description": (
                    "Signup dimensions use each account's earliest stored event in "
                    "the lookback window. Accounts without one are counted in the "
                    "unknown bucket."
                ),
            },
            "dimensions": dimension_payloads,
            "suppressed_rows": suppressed_rows,
            "suppressed_cells": suppressed_cells,
            "truncated_rows": sum(payload["truncated_rows"] for payload in dimension_payloads.values()),
            "truncated_page_views": truncated_page_views,
            "notes": [
                "Aggregated from first-party usage_analytics page views and users.created_at.",
                "Device, browser and OS are parsed at read time into fixed labels; raw user agents are never returned.",
                "Country comes only from a validated ISO 3166-1 alpha-2 edge header; no sub-country geography is read.",
                "Raw IP addresses, account ids and per-user location histories are never returned.",
                "Page-view/session cells and signup cells below 5 are suppressed.",
            ],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }


admin_privacy_breakdown_service = AdminPrivacyBreakdownService()
