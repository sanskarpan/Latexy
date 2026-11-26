"""Aggregate trial-health and trial-abuse signals for the admin Growth view.

Only aggregate counts leave this module. Device fingerprints and IP addresses
are hashed inside PostgreSQL (``md5(fingerprint)`` and ``md5(host(ip))``); no
raw fingerprint or IP is selected, returned to the browser, or written to a
log. The report is read-only: it never blocks a device, changes a trial, or
performs an enforcement action. Every ``rejection_reasons`` item is a
persisted-state signal that still requires human review.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from sqlalchemy import String, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..database import models
from .trial_service import TRIAL_LIMIT

MIN_COHORT_SIZE = 5
WINDOWS = (7, 30, 90)
LONGEST_WINDOW_DAYS = max(WINDOWS)
MAX_SCANNED_ROWS = 100_000
MAX_REJECTION_REASONS = 8
REPEAT_DEVICE_CLUSTER_THRESHOLD = 5

DeviceTrial = models.DeviceTrial
DeepAnalysisTrial = models.DeepAnalysisTrial
TrialAttribution = models.TrialAttribution

# Fixed, bounded histograms. A new value range requires a code change, not an
# unbounded GROUP BY over attacker-controlled usage counters.
USAGE_BUCKETS: tuple[tuple[str, int, int | None], ...] = (
    ("0", 0, 0),
    ("1", 1, 1),
    ("2", 2, 2),
    ("3", 3, 3),
    ("4-5", 4, 5),
    ("6-10", 6, 10),
    ("11-25", 11, 25),
    ("26+", 26, None),
)

REPEAT_DEVICE_BUCKETS: tuple[tuple[str, int, int | None], ...] = (
    ("1 device", 1, 1),
    ("2 devices", 2, 2),
    ("3 devices", 3, 3),
    ("4 devices", 4, 4),
    ("5-9 devices", 5, 9),
    ("10-24 devices", 10, 24),
    ("25+ devices", 25, None),
)

REASON_DEFINITIONS: tuple[tuple[str, str, str], ...] = (
    (
        "blocked_device",
        "Blocked device",
        "DeviceTrial.blocked is set, either by trial_service at the limit or by an operator.",
    ),
    (
        "trial_limit_reached",
        "Trial limit reached",
        f"usage_count is at or above the current {TRIAL_LIMIT}-use trial limit.",
    ),
    (
        "repeat_device_cluster",
        "Repeat-device cluster",
        "Device shares a hashed IP with at least "
        f"{REPEAT_DEVICE_CLUSTER_THRESHOLD} distinct device keys in the window.",
    ),
    (
        "deep_analysis_limit_reached",
        "Deep-analysis limit reached",
        "deep_analysis_trials.usage_count is at or above the configured free limit "
        f"({settings.DEEP_ANALYSIS_TRIAL_LIMIT}).",
    ),
)


@dataclass(frozen=True)
class TrialSignalRow:
    """One hashed trial row. It carries no raw fingerprint or IP."""

    device_key: str
    ip_key: str | None
    usage_count: int
    blocked: bool
    created_at: datetime


@dataclass(frozen=True)
class DeepAnalysisSignalRow:
    """One hashed deep-analysis trial row."""

    device_key: str
    usage_count: int
    last_used: datetime | None


@dataclass(frozen=True)
class AttributionSignalRow:
    """One consented trial-attribution row, keyed only by hashed device."""

    device_key: str
    trial_created_at: datetime
    user_linked: bool
    paid: bool


def _pct(value: int, total: int) -> float:
    return round((value / total) * 100, 2) if total else 0.0


def _publishable(count: int) -> int | None:
    """Zero is a harmless aggregate; 1-4 is a person-sized cell."""

    if count == 0 or count >= MIN_COHORT_SIZE:
        return count
    return None


def _bucket_counts(
    values: Iterable[int],
    buckets: tuple[tuple[str, int, int | None], ...],
) -> dict[str, int]:
    counts = {label: 0 for label, _lower, _upper in buckets}
    for raw in values:
        value = max(0, int(raw))
        for label, lower, upper in buckets:
            if value >= lower and (upper is None or value <= upper):
                counts[label] += 1
                break
    return counts


def build_usage_distribution(usage_counts: Iterable[int]) -> dict[str, Any]:
    """Return a bounded, suppressed histogram of per-device trial usage."""

    values = list(usage_counts)
    total = len(values)
    counts = _bucket_counts(values, USAGE_BUCKETS)
    hidden = 0 < total < MIN_COHORT_SIZE
    buckets: list[dict[str, Any]] = []
    suppressed_buckets = 0
    for label, lower, upper in USAGE_BUCKETS:
        raw = counts[label]
        published: int | None = raw
        if raw > 0 and (hidden or raw < MIN_COHORT_SIZE):
            published = None
            suppressed_buckets += 1
        buckets.append(
            {
                "label": label,
                "min": lower,
                "max": upper,
                "devices": published,
                "suppressed": published is None,
            }
        )
    return {
        "total_devices": total,
        "hidden": hidden,
        "buckets": buckets,
        "suppressed_buckets": suppressed_buckets,
    }


def build_repeat_distribution(
    cluster_sizes: Mapping[str, int],
    *,
    devices_with_ip: int,
    total_devices: int | None = None,
) -> dict[str, Any]:
    """Return the distribution of distinct devices sharing a hashed IP."""

    sizes = list(cluster_sizes.values())
    total_clusters = len(sizes)
    hidden = 0 < total_clusters < MIN_COHORT_SIZE
    counts = _bucket_counts(
        (size for size in sizes),
        REPEAT_DEVICE_BUCKETS,
    )
    buckets: list[dict[str, Any]] = []
    suppressed_buckets = 0
    for label, lower, upper in REPEAT_DEVICE_BUCKETS:
        raw = counts[label]
        published: int | None = raw
        if raw > 0 and (hidden or raw < MIN_COHORT_SIZE):
            published = None
            suppressed_buckets += 1
        buckets.append(
            {
                "label": label,
                "min": lower,
                "max": upper,
                "clusters": published,
                "suppressed": published is None,
            }
        )

    repeat_clusters = sum(1 for size in sizes if size >= 2)
    repeat_devices = sum(size for size in sizes if size >= 2)
    abuse_clusters = sum(1 for size in sizes if size >= REPEAT_DEVICE_CLUSTER_THRESHOLD)
    abuse_devices = sum(size for size in sizes if size >= REPEAT_DEVICE_CLUSTER_THRESHOLD)

    def _cluster_value(value: int) -> int | None:
        if hidden and value > 0:
            return None
        return _publishable(value)

    return {
        "basis": "hashed_ip_cluster",
        "devices_with_ip": devices_with_ip,
        "devices_without_ip": max(
            0,
            (devices_with_ip if total_devices is None else total_devices) - devices_with_ip,
        ),
        "clusters": 0 if total_clusters == 0 else _cluster_value(total_clusters),
        "repeat_clusters": _cluster_value(repeat_clusters),
        "devices_in_repeat_clusters": _cluster_value(repeat_devices),
        "abuse_threshold_devices": REPEAT_DEVICE_CLUSTER_THRESHOLD,
        "abuse_clusters": _cluster_value(abuse_clusters),
        "abuse_devices": _cluster_value(abuse_devices),
        "hidden": hidden,
        "buckets": buckets,
        "suppressed_buckets": suppressed_buckets,
    }


def build_reason_items(
    rows: Iterable[TrialSignalRow],
    *,
    cluster_sizes_by_ip: Mapping[str, int],
    deep_usage_by_device: Mapping[str, int],
) -> dict[str, Any]:
    """Return a fixed, bounded set of non-exclusive persisted-state signals."""

    counts = {key: 0 for key, _label, _definition in REASON_DEFINITIONS}
    deep_limit = int(settings.DEEP_ANALYSIS_TRIAL_LIMIT)
    for row in rows:
        if row.blocked:
            counts["blocked_device"] += 1
        if row.usage_count >= TRIAL_LIMIT:
            counts["trial_limit_reached"] += 1
        if row.ip_key and cluster_sizes_by_ip.get(row.ip_key, 0) >= REPEAT_DEVICE_CLUSTER_THRESHOLD:
            counts["repeat_device_cluster"] += 1
        if deep_usage_by_device.get(row.device_key, 0) >= deep_limit:
            counts["deep_analysis_limit_reached"] += 1

    ordered = sorted(
        counts.items(),
        key=lambda item: (-item[1], item[0]),
    )
    items: list[dict[str, Any]] = []
    suppressed = 0
    for key, raw in ordered[:MAX_REJECTION_REASONS]:
        label, definition = next(
            (item_label, item_definition)
            for item_key, item_label, item_definition in REASON_DEFINITIONS
            if item_key == key
        )
        published = _publishable(raw)
        if published is None:
            suppressed += 1
        items.append(
            {
                "key": key,
                "label": label,
                "definition": definition,
                "devices": published,
                "suppressed": published is None,
            }
        )
    return {
        "items": items,
        "suppressed": suppressed,
        "truncated": len(ordered) > MAX_REJECTION_REASONS,
        "overlap": True,
    }


def _cluster_sizes(rows: Iterable[TrialSignalRow]) -> dict[str, int]:
    clusters: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        if row.ip_key:
            clusters[row.ip_key].add(row.device_key)
    return {ip_key: len(device_keys) for ip_key, device_keys in clusters.items()}


def build_window(
    *,
    days: int,
    now: datetime,
    rows: Iterable[TrialSignalRow],
    deep_rows: Iterable[DeepAnalysisSignalRow],
    attribution_rows: Iterable[AttributionSignalRow],
) -> dict[str, Any]:
    """Build one rolling window from already-hashed signal rows."""

    start = now - timedelta(days=days)
    window_rows = [row for row in rows if start <= row.created_at < now]
    window_deep = [row for row in deep_rows if row.last_used is not None and start <= row.last_used < now]
    window_attribution = [row for row in attribution_rows if start <= row.trial_created_at < now]

    clusters = _cluster_sizes(window_rows)
    usage_distribution = build_usage_distribution(row.usage_count for row in window_rows)
    repeat_distribution = build_repeat_distribution(
        clusters,
        devices_with_ip=sum(1 for row in window_rows if row.ip_key),
        total_devices=len(window_rows),
    )
    reasons = build_reason_items(
        window_rows,
        cluster_sizes_by_ip=clusters,
        deep_usage_by_device={row.device_key: row.usage_count for row in window_deep},
    )

    attributed = sum(1 for row in window_attribution if row.user_linked)
    paid = sum(1 for row in window_attribution if row.user_linked and row.paid)
    show_attributed = attributed == 0 or attributed >= MIN_COHORT_SIZE
    show_paid = paid == 0 or paid >= MIN_COHORT_SIZE
    attributed_value = attributed if show_attributed else None
    paid_value = paid if show_attributed and show_paid else None
    conversion_suppressed = attributed_value is None or paid_value is None
    trial_starts = len(window_rows)
    blocked = sum(1 for row in window_rows if row.blocked)

    return {
        "days": days,
        "start": start.isoformat(),
        "end": now.isoformat(),
        "trial_starts": trial_starts,
        "unique_devices": len({row.device_key for row in window_rows}),
        "blocked_devices": blocked,
        "blocked_pct": _pct(blocked, trial_starts),
        "devices_with_usage": sum(1 for row in window_rows if row.usage_count > 0),
        "devices_at_or_above_limit": sum(1 for row in window_rows if row.usage_count >= TRIAL_LIMIT),
        "conversion": {
            "basis": "consented_trial_attribution",
            "attributed_trials": attributed_value,
            "paid_trials": paid_value,
            "trial_to_paid_pct": (
                _pct(paid, trial_starts)
                if paid_value is not None and trial_starts > 0
                else (0.0 if paid_value is not None else None)
            ),
            "suppressed": conversion_suppressed,
        },
        "usage_distribution": usage_distribution,
        "repeat_device_distribution": repeat_distribution,
        "rejection_reasons": reasons,
    }


def build_snapshot(
    *,
    rows: Iterable[TrialSignalRow],
    deep_rows: Iterable[DeepAnalysisSignalRow],
    attribution_rows: Iterable[AttributionSignalRow],
    now: datetime | None = None,
    trial_rows_truncated: bool = False,
    deep_rows_truncated: bool = False,
) -> dict[str, Any]:
    """Assemble the aggregate-only response from hashed rows."""

    generated_at = now or datetime.now(timezone.utc)
    rows = list(rows)
    deep_rows = list(deep_rows)
    attribution_rows = list(attribution_rows)
    windows = [
        build_window(
            days=days,
            now=generated_at,
            rows=rows,
            deep_rows=deep_rows,
            attribution_rows=attribution_rows,
        )
        for days in WINDOWS
    ]
    by_days = {window["days"]: window for window in windows}
    starts_7d = by_days[7]["trial_starts"]
    starts_30d = by_days[30]["trial_starts"]
    starts_90d = by_days[90]["trial_starts"]
    conversion_90d = by_days[90]["conversion"]
    attributed_90d = conversion_90d["attributed_trials"]

    return {
        "generated_at": generated_at.isoformat(),
        "windows_days": list(WINDOWS),
        "minimum_cohort_size": MIN_COHORT_SIZE,
        "trial_limit": TRIAL_LIMIT,
        "deep_analysis_trial_limit": int(settings.DEEP_ANALYSIS_TRIAL_LIMIT),
        "repeat_device_cluster_threshold": REPEAT_DEVICE_CLUSTER_THRESHOLD,
        "max_scanned_rows": MAX_SCANNED_ROWS,
        "windows": windows,
        "reconciliation": {
            "trial_starts_7d": starts_7d,
            "trial_starts_30d": starts_30d,
            "trial_starts_90d": starts_90d,
            "trial_starts_8_to_30d": max(0, starts_30d - starts_7d),
            "trial_starts_31_to_90d": max(0, starts_90d - starts_30d),
            "window_sum_equals_90d": (
                starts_7d + max(0, starts_30d - starts_7d) + max(0, starts_90d - starts_30d) == starts_90d
            ),
            "scanned_rows": len(rows),
            "rows_truncated": trial_rows_truncated,
            "deep_analysis_rows_scanned": len(deep_rows),
            "deep_analysis_rows_truncated": deep_rows_truncated,
            "devices_with_ip_90d": by_days[90]["repeat_device_distribution"]["devices_with_ip"],
            "devices_without_ip_90d": by_days[90]["repeat_device_distribution"]["devices_without_ip"],
            "attributed_trials_90d": attributed_90d,
            "paid_trials_90d": conversion_90d["paid_trials"],
            "unattributed_trials_90d": (max(0, starts_90d - attributed_90d) if attributed_90d is not None else None),
        },
        "notes": [
            (
                "Device fingerprints and IPs are hashed inside PostgreSQL. No raw "
                "fingerprint, IP, account id, email, token or document is selected "
                "by this report or written to logs."
            ),
            (
                f"Windows are rolling {WINDOWS[0]}/{WINDOWS[1]}/{WINDOWS[2]} days "
                "ending at generated_at. Trial starts include anonymous and linked "
                "device trials."
            ),
            (
                f"Histogram buckets are fixed and bounded. A bucket with 1-"
                f"{MIN_COHORT_SIZE - 1} devices and every nonzero bucket in a window "
                f"with fewer than {MIN_COHORT_SIZE} devices is suppressed."
            ),
            (
                "Reasons overlap and describe persisted state, not request-time "
                f"rejections. trial_service auto-blocks at {TRIAL_LIMIT} uses; this "
                "view never blocks, resets or otherwise mutates a trial."
            ),
            (
                "Repeat-device clusters group distinct hashed device keys by hashed "
                "IP inside the window. Shared NAT and office IPs can create false "
                "positives; use this only as a review signal."
            ),
        ],
    }


async def _fetch_trial_rows(
    db: AsyncSession,
    *,
    cutoff: datetime,
    now: datetime,
) -> tuple[list[TrialSignalRow], bool]:
    # The hash is computed in SQL so the raw fingerprint never enters the
    # application process or a query log parameter.
    stmt = (
        select(
            func.md5(cast(DeviceTrial.device_fingerprint, String)).label("device_key"),
            func.md5(func.host(DeviceTrial.ip_address)).label("ip_key"),
            DeviceTrial.usage_count.label("usage_count"),
            DeviceTrial.blocked.label("blocked"),
            DeviceTrial.created_at.label("created_at"),
        )
        .where(
            DeviceTrial.created_at >= cutoff,
            DeviceTrial.created_at < now,
        )
        .order_by(DeviceTrial.created_at.asc())
        .limit(MAX_SCANNED_ROWS + 1)
    )
    fetched = (await db.execute(stmt)).all()
    truncated = len(fetched) > MAX_SCANNED_ROWS
    rows = [
        TrialSignalRow(
            device_key=row.device_key,
            ip_key=row.ip_key,
            usage_count=int(row.usage_count or 0),
            blocked=bool(row.blocked),
            created_at=row.created_at,
        )
        for row in fetched[:MAX_SCANNED_ROWS]
    ]
    return rows, truncated


async def _fetch_deep_rows(
    db: AsyncSession,
    *,
    cutoff: datetime,
) -> tuple[list[DeepAnalysisSignalRow], bool]:
    stmt = (
        select(
            func.md5(cast(DeepAnalysisTrial.device_fingerprint, String)).label("device_key"),
            DeepAnalysisTrial.usage_count.label("usage_count"),
            DeepAnalysisTrial.last_used.label("last_used"),
        )
        .where(
            DeepAnalysisTrial.last_used.is_not(None),
            DeepAnalysisTrial.last_used >= cutoff,
        )
        .order_by(DeepAnalysisTrial.last_used.asc())
        .limit(MAX_SCANNED_ROWS + 1)
    )
    fetched = (await db.execute(stmt)).all()
    truncated = len(fetched) > MAX_SCANNED_ROWS
    rows = [
        DeepAnalysisSignalRow(
            device_key=row.device_key,
            usage_count=int(row.usage_count or 0),
            last_used=row.last_used,
        )
        for row in fetched[:MAX_SCANNED_ROWS]
    ]
    return rows, truncated


async def _fetch_attribution_rows(
    db: AsyncSession,
    *,
    cutoff: datetime,
    now: datetime,
) -> list[AttributionSignalRow]:
    stmt = (
        select(
            func.md5(cast(DeviceTrial.device_fingerprint, String)).label("device_key"),
            DeviceTrial.created_at.label("trial_created_at"),
            TrialAttribution.user_id.label("user_id"),
            TrialAttribution.paid_at.label("paid_at"),
        )
        .join(DeviceTrial, DeviceTrial.id == TrialAttribution.trial_id)
        .where(
            TrialAttribution.consent_granted.is_(True),
            DeviceTrial.created_at >= cutoff,
            DeviceTrial.created_at < now,
        )
        .limit(MAX_SCANNED_ROWS)
    )
    fetched = (await db.execute(stmt)).all()
    return [
        AttributionSignalRow(
            device_key=row.device_key,
            trial_created_at=row.trial_created_at,
            user_linked=row.user_id is not None,
            paid=row.paid_at is not None,
        )
        for row in fetched
    ]


async def snapshot(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return aggregate trial health for 7, 30 and 90 rolling days."""

    generated_at = now or datetime.now(timezone.utc)
    cutoff = generated_at - timedelta(days=LONGEST_WINDOW_DAYS)
    rows, trial_rows_truncated = await _fetch_trial_rows(db, cutoff=cutoff, now=generated_at)
    deep_rows, deep_rows_truncated = await _fetch_deep_rows(db, cutoff=cutoff)
    attribution_rows = await _fetch_attribution_rows(db, cutoff=cutoff, now=generated_at)
    return build_snapshot(
        rows=rows,
        deep_rows=deep_rows,
        attribution_rows=attribution_rows,
        now=generated_at,
        trial_rows_truncated=trial_rows_truncated,
        deep_rows_truncated=deep_rows_truncated,
    )
