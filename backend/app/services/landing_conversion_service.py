"""Landing conversion by page, experiment/variant, and device class.

Data boundary
-------------
Everything here is first-party and aggregate. The only columns read from
``usage_analytics`` are the action, the safe landing metadata (page key,
experiment, variant, device class), the opaque device-local fingerprint used by
the anonymous trial, an optional account id, and timestamps. Full paths, query
strings, share tokens, IP addresses, emails, document content, and raw
fingerprints never leave this module.

Attribution model
-----------------
Visits are raw first-party ``page_view`` events for ``page = landing``. Trial
starts and registrations are credited with **same-device first-touch**
attribution:

* the first landing view on a device is the only view that can earn credit;
* a trial start is counted only for that same device fingerprint;
* a registration is counted only when the same device also produced an
  authenticated page view for that account after the landing view; and
* each account is credited at most once, to its earliest qualifying device
  view. A user seen on two devices is never merged into a cross-device funnel.

Accounts with no same-device link stay in the overall summary and are reported
as unattributed. A missing variant is labelled as missing; it is never imputed
as a control group. Cohort cells below :data:`MIN_SEGMENT_SIZE` visits are
omitted.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import models

User = models.User
UsageAnalytics = models.UsageAnalytics
DeviceTrial = models.DeviceTrial
Subscription = models.Subscription

MIN_SEGMENT_SIZE = 5
MAX_BREAKDOWN_ROWS = 200

LANDING_PAGE_KEYS = (
    "home",
    "try",
    "pricing",
    "templates",
    "resources",
    "platform",
    "faq",
    "updates",
    "developer",
    "other",
)
PAGE_LABELS = {
    "home": "Home",
    "try": "Try studio",
    "pricing": "Pricing",
    "templates": "Templates",
    "resources": "Resources",
    "platform": "Platform",
    "faq": "FAQ",
    "updates": "Updates",
    "developer": "Developer",
    "other": "Other landing page",
}
DEVICE_CLASSES = ("mobile", "tablet", "desktop", "unknown")
DEVICE_LABELS = {
    "mobile": "Mobile",
    "tablet": "Tablet",
    "desktop": "Desktop",
    "unknown": "Unknown device",
}
MISSING_VARIANT_LABEL = "Variant not recorded"
MISSING_EXPERIMENT_LABEL = "No experiment"
MISSING_PAGE_LABEL = "Unattributed page"
NO_DEVICE_LABEL = "Unknown device"
SUBSCRIPTION_STATUSES = ("active", "cancel_scheduled", "past_due")

_LABEL_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_TABLET_MARKERS = ("ipad", "tablet", "kindle", "silk", "playbook", "nexus 7", "nexus 9")
_MOBILE_MARKERS = (
    "mobi",
    "iphone",
    "ipod",
    "android",
    "windows phone",
    "blackberry",
    "opera mini",
    "opera mobi",
)


def _normalize_label(value: Any) -> str | None:
    """Bound an untrusted experiment/variant label.

    Invalid or oversized values are treated as missing rather than persisted or
    echoed. The ingestion route rejects these up front; this is defence in depth
    for rows written by tests, migrations, or older clients.
    """

    if value is None:
        return None
    raw = str(value).strip().lower()
    if not raw or _LABEL_PATTERN.fullmatch(raw) is None:
        return None
    return raw


def normalize_page_key(value: Any) -> str | None:
    """Map a page key onto the bounded landing-page allowlist."""

    if value is None:
        return None
    raw = str(value).strip().lower()
    if not raw:
        return None
    if raw in PAGE_LABELS:
        return raw
    return "other"


def normalize_experiment(value: Any) -> str | None:
    return _normalize_label(value)


def normalize_variant(value: Any) -> str | None:
    return _normalize_label(value)


def classify_device_class(user_agent: str | None) -> str:
    """Coarse server-side mobile/tablet/desktop class from a user agent.

    User-agent parsing is deliberately simple and low-cardinality. It only
    decides a comparison bucket; it never becomes an identity signal.
    """

    if not user_agent:
        return "unknown"
    ua = user_agent.lower()
    if not ua.strip():
        return "unknown"
    if "ipad" in ua or any(marker in ua for marker in _TABLET_MARKERS):
        return "tablet"
    if any(marker in ua for marker in _MOBILE_MARKERS):
        return "mobile"
    return "desktop"


def normalize_device_class(value: Any, user_agent: str | None = None) -> str:
    if value is None:
        return classify_device_class(user_agent)
    raw = str(value).strip().lower()
    if raw in DEVICE_CLASSES:
        return raw
    return classify_device_class(user_agent)


def _pct(value: int, total: int) -> float:
    return round((value / total) * 100, 2) if total else 0.0


def _conversion(value: int, total: int) -> float:
    # Attribution is capped at the visit denominator so a malformed or
    # duplicated source row can never produce an impossible rate.
    return min(100.0, _pct(value, total))


def _page_label(page_key: str | None) -> str:
    if page_key is None:
        return MISSING_PAGE_LABEL
    return PAGE_LABELS.get(page_key, "Other landing page")


def _variant_label(variant: str | None) -> str:
    return variant if variant is not None else MISSING_VARIANT_LABEL


def _experiment_label(experiment: str | None) -> str:
    return experiment if experiment is not None else MISSING_EXPERIMENT_LABEL


def _cell_key(
    page_key: Any, experiment: Any, variant: Any, device_class: Any
) -> tuple[str | None, str | None, str | None, str]:
    return (
        normalize_page_key(page_key),
        normalize_experiment(experiment),
        normalize_variant(variant),
        normalize_device_class(device_class),
    )


def _fields(*, page_key: str | None, experiment: str | None, variant: str | None, device_class: str) -> dict[str, Any]:
    return {
        "page_key": page_key,
        "page_label": _page_label(page_key),
        "missing_page_key": page_key is None,
        "experiment": experiment,
        "experiment_label": _experiment_label(experiment),
        "missing_experiment": experiment is None,
        "variant": variant,
        "variant_label": _variant_label(variant),
        "missing_variant": variant is None,
        "device_class": device_class,
        "device_label": DEVICE_LABELS.get(device_class, NO_DEVICE_LABEL),
    }


def _cell_row(fields: Mapping[str, Any], counts: Mapping[str, int]) -> dict[str, Any]:
    visits = int(counts.get("visits", 0))
    trials = int(counts.get("trial_starts", 0))
    registrations = int(counts.get("registrations", 0))
    subscriptions = int(counts.get("subscriptions", 0))
    return {
        **dict(fields),
        "visits": visits,
        "trial_starts": trials,
        "registrations": registrations,
        "subscriptions": subscriptions,
        "sample_size": visits,
        "conversion_rate": _conversion(registrations, visits),
        "trial_conversion_rate": _conversion(trials, visits),
        "subscription_conversion_rate": _conversion(subscriptions, visits),
    }


def _aggregate(cells: Iterable[dict[str, Any]], group_keys: tuple[str, ...]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], dict[str, Any]] = {}
    for cell in cells:
        key = tuple(cell[group] for group in group_keys)
        accumulator = grouped.get(key)
        if accumulator is None:
            fields = {group: cell[group] for group in group_keys}
            # Keep the display labels attached to every grouped row.
            if "page_key" in group_keys:
                fields["page_label"] = cell["page_label"]
                fields["missing_page_key"] = cell["missing_page_key"]
            if "experiment" in group_keys:
                fields["experiment_label"] = cell["experiment_label"]
                fields["missing_experiment"] = cell["missing_experiment"]
            if "variant" in group_keys:
                fields["variant_label"] = cell["variant_label"]
                fields["missing_variant"] = cell["missing_variant"]
            if "device_class" in group_keys:
                fields["device_label"] = cell["device_label"]
            accumulator = {**fields, "visits": 0, "trial_starts": 0, "registrations": 0, "subscriptions": 0}
            grouped[key] = accumulator
        accumulator["visits"] += cell["visits"]
        accumulator["trial_starts"] += cell["trial_starts"]
        accumulator["registrations"] += cell["registrations"]
        accumulator["subscriptions"] += cell["subscriptions"]

    count_keys = {"visits", "trial_starts", "registrations", "subscriptions"}
    rows = [_cell_row({k: v for k, v in row.items() if k not in count_keys}, row) for row in grouped.values()]
    rows.sort(
        key=lambda row: (
            -row["visits"],
            str(row.get("page_key") or ""),
            str(row.get("variant") or ""),
            str(row.get("device_class") or ""),
        )
    )
    return rows[:MAX_BREAKDOWN_ROWS]


async def _overall_summary(db: AsyncSession, start: datetime, end: datetime) -> dict[str, Any]:
    """The existing landing -> trial -> registration -> subscription funnel.

    Definitions intentionally match ``analytics_service.get_conversion_funnel``
    so the Growth summary and the Analytics tab cannot disagree about the
    selected period.
    """

    landing_visits = int(
        (
            await db.execute(
                select(func.count(UsageAnalytics.id)).where(
                    UsageAnalytics.action == "page_view",
                    UsageAnalytics.created_at >= start,
                    UsageAnalytics.created_at <= end,
                    UsageAnalytics.event_metadata["page"].as_string() == "landing",
                )
            )
        ).scalar()
        or 0
    )
    trial_starts = int(
        (
            await db.execute(
                select(func.count(DeviceTrial.id)).where(
                    DeviceTrial.created_at >= start,
                    DeviceTrial.created_at <= end,
                )
            )
        ).scalar()
        or 0
    )
    registrations = int(
        (
            await db.execute(
                select(func.count(User.id)).where(
                    User.created_at >= start,
                    User.created_at <= end,
                )
            )
        ).scalar()
        or 0
    )
    subscriptions = int(
        (
            await db.execute(
                select(func.count(func.distinct(Subscription.user_id))).where(
                    Subscription.created_at >= start,
                    Subscription.created_at <= end,
                    Subscription.status.in_(SUBSCRIPTION_STATUSES),
                )
            )
        ).scalar()
        or 0
    )

    return {
        "period_days": None,
        "funnel_steps": {
            "landing_visits": landing_visits,
            "trial_starts": trial_starts,
            "registrations": registrations,
            "subscriptions": subscriptions,
        },
        "conversion_rates": {
            "landing_to_trial": _conversion(trial_starts, landing_visits),
            "trial_to_registration": _conversion(registrations, trial_starts),
            "registration_to_subscription": _conversion(subscriptions, registrations),
            "overall_conversion": _conversion(subscriptions, landing_visits),
        },
        "sample_sizes": {
            "landing_visits": landing_visits,
            "trial_starts": trial_starts,
            "registrations": registrations,
            "subscriptions": subscriptions,
        },
    }


class LandingConversionService:
    async def snapshot(self, db: AsyncSession, *, days: int = 30) -> dict[str, Any]:
        days = max(1, min(int(days), 365))
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=days)

        metadata = UsageAnalytics.event_metadata
        page_expr = metadata["page_key"].as_string()
        experiment_expr = metadata["experiment"].as_string()
        variant_expr = metadata["variant"].as_string()
        device_expr = metadata["device_class"].as_string()

        visit_rows = (
            await db.execute(
                select(
                    page_expr,
                    experiment_expr,
                    variant_expr,
                    device_expr,
                    func.count(UsageAnalytics.id).label("visits"),
                )
                .where(
                    UsageAnalytics.action == "page_view",
                    UsageAnalytics.created_at >= start,
                    UsageAnalytics.created_at <= now,
                    metadata["page"].as_string() == "landing",
                )
                .group_by(page_expr, experiment_expr, variant_expr, device_expr)
            )
        ).all()

        visits: dict[tuple[str | None, str | None, str | None, str], int] = defaultdict(int)
        for page_key, experiment, variant, device_class, count in visit_rows:
            visits[_cell_key(page_key, experiment, variant, device_class)] += int(count or 0)

        # First landing view per device. DISTINCT ON is PostgreSQL-specific and
        # keeps this bounded even for a month of marketing traffic.
        device_first_rows = (
            await db.execute(
                select(
                    UsageAnalytics.device_fingerprint,
                    UsageAnalytics.created_at,
                    metadata["page_key"].as_string(),
                    metadata["experiment"].as_string(),
                    metadata["variant"].as_string(),
                    metadata["device_class"].as_string(),
                )
                .where(
                    UsageAnalytics.action == "page_view",
                    UsageAnalytics.created_at >= start,
                    UsageAnalytics.created_at <= now,
                    metadata["page"].as_string() == "landing",
                    UsageAnalytics.device_fingerprint.is_not(None),
                )
                .distinct(UsageAnalytics.device_fingerprint)
                .order_by(
                    UsageAnalytics.device_fingerprint,
                    UsageAnalytics.created_at,
                    UsageAnalytics.id,
                )
            )
        ).all()

        user_first_rows = (
            await db.execute(
                select(
                    UsageAnalytics.user_id,
                    UsageAnalytics.created_at,
                    metadata["page_key"].as_string(),
                    metadata["experiment"].as_string(),
                    metadata["variant"].as_string(),
                    metadata["device_class"].as_string(),
                )
                .where(
                    UsageAnalytics.action == "page_view",
                    UsageAnalytics.created_at >= start,
                    UsageAnalytics.created_at <= now,
                    metadata["page"].as_string() == "landing",
                    UsageAnalytics.device_fingerprint.is_(None),
                    UsageAnalytics.user_id.is_not(None),
                )
                .distinct(UsageAnalytics.user_id)
                .order_by(
                    UsageAnalytics.user_id,
                    UsageAnalytics.created_at,
                    UsageAnalytics.id,
                )
            )
        ).all()

        # Same-device account links. These may come from any pageview (for
        # example the dashboard after signup); the path itself is never stored.
        link_rows = (
            await db.execute(
                select(UsageAnalytics.device_fingerprint, UsageAnalytics.user_id)
                .where(
                    UsageAnalytics.action == "page_view",
                    UsageAnalytics.created_at >= start,
                    UsageAnalytics.created_at <= now,
                    UsageAnalytics.device_fingerprint.is_not(None),
                    UsageAnalytics.user_id.is_not(None),
                )
                .distinct()
            )
        ).all()
        device_users: dict[str, set[str]] = defaultdict(set)
        for fingerprint, user_id in link_rows:
            if fingerprint and user_id:
                device_users[str(fingerprint)].add(str(user_id))

        user_rows = (
            await db.execute(
                select(User.id, User.created_at).where(
                    User.created_at >= start,
                    User.created_at <= now,
                )
            )
        ).all()
        user_signup = {str(user_id): created_at for user_id, created_at in user_rows if user_id}

        trial_rows = (
            await db.execute(
                select(DeviceTrial.device_fingerprint, DeviceTrial.created_at).where(
                    DeviceTrial.created_at >= start,
                    DeviceTrial.created_at <= now,
                )
            )
        ).all()
        trial_by_device = {
            str(fingerprint): created_at
            for fingerprint, created_at in trial_rows
            if fingerprint is not None and created_at is not None
        }

        device_first: dict[str, dict[str, Any]] = {}
        for fingerprint, created_at, page_key, experiment, variant, device_class in device_first_rows:
            if fingerprint is None or created_at is None:
                continue
            device_first[str(fingerprint)] = {
                "created_at": created_at,
                "cell": _cell_key(page_key, experiment, variant, device_class),
            }

        user_first: dict[str, dict[str, Any]] = {}
        for user_id, created_at, page_key, experiment, variant, device_class in user_first_rows:
            if user_id is None or created_at is None:
                continue
            user_first[str(user_id)] = {
                "created_at": created_at,
                "cell": _cell_key(page_key, experiment, variant, device_class),
            }

        # Credit each registration once, to its earliest same-device landing
        # view. The account is never merged across devices.
        attributed_users: dict[str, tuple[datetime, tuple[str | None, str | None, str | None, str]]] = {}

        def _consider(user_id: str, view_at: datetime, cell: tuple[str | None, str | None, str | None, str]) -> None:
            signup_at = user_signup.get(user_id)
            if signup_at is None or signup_at < view_at:
                return
            current = attributed_users.get(user_id)
            if current is None or view_at < current[0]:
                attributed_users[user_id] = (view_at, cell)

        for fingerprint, first in device_first.items():
            for user_id in device_users.get(fingerprint, ()):
                _consider(user_id, first["created_at"], first["cell"])
        for user_id, first in user_first.items():
            _consider(user_id, first["created_at"], first["cell"])

        registrations: dict[tuple[str | None, str | None, str | None, str], int] = defaultdict(int)
        for _view_at, cell in attributed_users.values():
            registrations[cell] += 1

        trial_starts: dict[tuple[str | None, str | None, str | None, str], int] = defaultdict(int)
        for fingerprint, first in device_first.items():
            trial_at = trial_by_device.get(fingerprint)
            if trial_at is not None and trial_at >= first["created_at"]:
                trial_starts[first["cell"]] += 1

        subscriptions: dict[tuple[str | None, str | None, str | None, str], int] = defaultdict(int)
        if attributed_users:
            subscription_rows = (
                await db.execute(
                    select(Subscription.user_id)
                    .where(
                        Subscription.created_at >= start,
                        Subscription.created_at <= now,
                        Subscription.status.in_(SUBSCRIPTION_STATUSES),
                        Subscription.user_id.in_(list(attributed_users)),
                    )
                    .distinct()
                )
            ).all()
            for (user_id,) in subscription_rows:
                attributed = attributed_users.get(str(user_id))
                if attributed is not None:
                    subscriptions[attributed[1]] += 1

        all_cells = set(visits) | set(trial_starts) | set(registrations) | set(subscriptions)
        visible_cells: list[dict[str, Any]] = []
        suppressed_cells = 0
        for cell in all_cells:
            counts = {
                "visits": visits.get(cell, 0),
                "trial_starts": trial_starts.get(cell, 0),
                "registrations": registrations.get(cell, 0),
                "subscriptions": subscriptions.get(cell, 0),
            }
            if counts["visits"] < MIN_SEGMENT_SIZE:
                suppressed_cells += 1
                continue
            page_key, experiment, variant, device_class = cell
            fields = _fields(
                page_key=page_key,
                experiment=experiment,
                variant=variant,
                device_class=device_class,
            )
            visible_cells.append(_cell_row(fields, counts))

        visible_cells.sort(
            key=lambda row: (
                -row["visits"],
                str(row.get("page_key") or ""),
                str(row.get("variant") or ""),
                row["device_class"],
            )
        )

        by_page = _aggregate(visible_cells, ("page_key",))
        by_page_variant = _aggregate(visible_cells, ("page_key", "experiment", "variant"))
        by_device = _aggregate(visible_cells, ("device_class",))
        by_page_variant_device = visible_cells[:MAX_BREAKDOWN_ROWS]

        summary = await _overall_summary(db, start, now)
        summary["period_days"] = days
        attributed_trials = sum(trial_starts.values())
        attributed_registrations = len(attributed_users)
        summary["attribution"] = {
            "model": "same_device_first_touch",
            "attributed_trial_starts": attributed_trials,
            "attributed_registrations": attributed_registrations,
            "unattributed_trial_starts": max(0, summary["funnel_steps"]["trial_starts"] - attributed_trials),
            "unattributed_registrations": max(0, summary["funnel_steps"]["registrations"] - attributed_registrations),
            "registration_coverage_pct": _conversion(
                attributed_registrations, summary["funnel_steps"]["registrations"]
            ),
            "description": (
                "Trials and registrations are credited only to the earliest landing view "
                "on the same device. Accounts seen on multiple devices are credited once "
                "to the earliest qualifying view; no cross-device funnel is constructed."
            ),
        }

        return {
            "days": days,
            "period": {
                "start": start.isoformat(),
                "end": now.isoformat(),
                "timezone": "UTC",
            },
            "minimum_segment_size": MIN_SEGMENT_SIZE,
            "summary": summary,
            "by_device": by_device,
            "by_page": by_page,
            "by_page_variant": by_page_variant,
            "by_page_variant_device": by_page_variant_device,
            "suppressed_cells": suppressed_cells,
            "truncated_cells": max(0, len(visible_cells) - MAX_BREAKDOWN_ROWS),
            "supported_page_keys": list(LANDING_PAGE_KEYS),
            "variant_labels": {
                "missing": MISSING_VARIANT_LABEL,
                "missing_experiment": MISSING_EXPERIMENT_LABEL,
                "missing_page": MISSING_PAGE_LABEL,
                "unknown_device": NO_DEVICE_LABEL,
            },
            "notes": [
                "Visits are first-party page_view events for landing pages only; "
                "paths, query strings, share tokens, and document content are never stored.",
                "Variant values are recorded only when supplied by the page. Missing "
                "variant data is labelled, never imputed as a control group.",
                "Cells below five visits are omitted; rates use visits as the sample size.",
            ],
            "generated_at": now.isoformat(),
        }


landing_conversion_service = LandingConversionService()
