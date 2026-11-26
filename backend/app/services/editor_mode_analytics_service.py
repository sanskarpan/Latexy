"""Privacy-safe editor mode, auto-compile and SyncTeX analytics (issue #2077).

Data boundary
-------------
The browser reports only a bounded event type, the editor mode enum, a
canonical route label, an optional boolean/direction, a random retry id and a
SHA-256 hash of the document id. The raw document id, LaTeX source, prompts,
filenames, text, ``user_agent`` and IP address are never stored for this event
family. The server re-derives the plan family from the authenticated account and
re-buckets the route, so a client cannot spoof either dimension.

Storage reuses the existing ``usage_analytics`` JSONB column. No migration is
required.

Compile correlation
-------------------
``editor_mode_selected`` events form a per-document timeline. Each compilation
is attributed to the latest mode selected for the same document hash at or
before the compile timestamp, within a bounded lookback. Unattributed compiles
are reported as ``unknown`` so mode buckets reconcile to the raw compile rows.
The join is aggregate-only: document hashes and account ids are never returned.

Suppression
-----------
A report with fewer than five distinct users is fully suppressed. Individual
mode/plan/day buckets below five users are hidden, and the related totals are
withheld so a hidden small cohort cannot be recovered by subtraction.
"""

from __future__ import annotations

import hashlib
import math
import re
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Mapping, Sequence

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import PLAN_FAMILY_ALIASES, resolve_plan_family
from ..database import models

UsageAnalytics = models.UsageAnalytics
User = models.User
Compilation = models.Compilation

EDITOR_MODE_SELECTED = "editor_mode_selected"
AUTO_COMPILE_TOGGLED = "auto_compile_toggled"
SYNCTEX_USED = "synctex_used"
EDITOR_ACTIONS: tuple[str, ...] = (
    EDITOR_MODE_SELECTED,
    AUTO_COMPILE_TOGGLED,
    SYNCTEX_USED,
)
EDITOR_RESOURCE_TYPE = "editor"

EDITOR_MODES: tuple[str, ...] = ("source", "wysiwyg", "pdf")
MODE_LABELS: dict[str, str] = {
    "source": "Source",
    "wysiwyg": "Visual editor",
    "pdf": "PDF editor",
    "unknown": "Not attributed",
}
SYNCTEX_DIRECTIONS: tuple[str, ...] = ("source_to_pdf", "pdf_to_source")
DIRECTION_LABELS: dict[str, str] = {
    "source_to_pdf": "Source to PDF",
    "pdf_to_source": "PDF to source",
}

MIN_GROUP_SIZE = 5
MAX_RANGE_DAYS = 366
MAX_EVENTS_PER_REQUEST = 50
MAX_EVENT_ROWS = 200_000
MAX_COMPILATION_ROWS = 100_000
TOGGLE_DEDUPE_SECONDS = 30
MODE_ATTRIBUTION_LOOKBACK = timedelta(hours=12)
SPARSE_COMPILE_SAMPLES = 20

UNKNOWN_ROUTE = "/other"
UNKNOWN_MODE = "unknown"

_STATIC_ROUTES = frozenset(
    {
        "/",
        "/try",
        "/templates",
        "/dashboard",
        "/workspace",
        "/workspaces",
        "/login",
        "/signup",
        "/billing",
        "/byok",
        "/settings",
        "/tracker",
    }
)
_ROUTE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^/workspace/[^/]+/edit/?$"), "/workspace/:resumeId/edit"),
    (re.compile(r"^/workspace/[^/]+/optimize/?$"), "/workspace/:resumeId/optimize"),
    (re.compile(r"^/workspace/[^/]+/cover-letter/?$"), "/workspace/:resumeId/cover-letter"),
    (re.compile(r"^/workspace/[^/]+/career/?$"), "/workspace/:resumeId/career"),
    (re.compile(r"^/workspace/[^/]+/batch-tailor/?$"), "/workspace/:resumeId/batch-tailor"),
    (re.compile(r"^/workspaces/[^/]+/recruiter/?$"), "/workspaces/:workspaceId/recruiter"),
    (re.compile(r"^/workspaces/[^/]+/?$"), "/workspaces/:workspaceId"),
    (re.compile(r"^/workspace/[^/]+/?$"), "/workspace/:resumeId"),
)
_CANONICAL_DYNAMIC_ROUTES = frozenset(label for _pattern, label in _ROUTE_PATTERNS)

_ROUTE_SQL_PATTERN = re.compile(r"^/?[A-Za-z0-9_.:/~-]{0,127}$")
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DOCUMENT_HASH = re.compile(r"^[a-f0-9]{64}$")


def sanitize_editor_route(value: Any) -> str:
    """Return a fixed route label, never a raw client path with identifiers."""

    if not isinstance(value, str):
        return UNKNOWN_ROUTE
    route = value.strip().split("?", 1)[0].split("#", 1)[0][:128]
    if not route or not _ROUTE_SQL_PATTERN.fullmatch(route):
        return UNKNOWN_ROUTE
    if not route.startswith("/"):
        route = f"/{route}"
    if route in _STATIC_ROUTES or route in _CANONICAL_DYNAMIC_ROUTES:
        return route
    for pattern, label in _ROUTE_PATTERNS:
        if pattern.fullmatch(route):
            return label
    return UNKNOWN_ROUTE


def normalize_plan(value: Any) -> str:
    """Map an account plan/SKU onto the stable plan family names."""

    if not isinstance(value, str):
        return "free"
    normalized = value.strip().lower()
    if not normalized:
        return "free"
    if normalized in PLAN_FAMILY_ALIASES:
        return resolve_plan_family(normalized)
    return normalized[:32]


def hash_document_identifier(value: Any) -> str | None:
    """Hash an opaque document identifier; the raw value is never returned."""

    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if not normalized or _SAFE_IDENTIFIER.fullmatch(normalized) is None:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def normalize_document_hash(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized if _DOCUMENT_HASH.fullmatch(normalized) else None


def _safe_event_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized if _SAFE_IDENTIFIER.fullmatch(normalized) else None


def normalize_editor_event(
    *,
    event_type: Any,
    mode: Any,
    route: Any,
    document_hash: Any = None,
    document_id: Any = None,
    enabled: Any = None,
    direction: Any = None,
    event_id: Any = None,
    plan: Any = None,
) -> dict[str, Any] | None:
    """Build the exact allowlisted storage payload, or return ``None``.

    ``document_id`` is accepted only as a convenience for first-party callers
    and is immediately replaced with its SHA-256 hash. The raw identifier never
    enters the returned payload.
    """

    if not isinstance(event_type, str) or event_type not in EDITOR_ACTIONS:
        return None
    if not isinstance(mode, str) or mode not in EDITOR_MODES:
        return None

    digest = normalize_document_hash(document_hash)
    if digest is None:
        digest = hash_document_identifier(document_id)
    if digest is None:
        return None

    payload: dict[str, Any] = {
        "mode": mode,
        "plan": normalize_plan(plan),
        "route": sanitize_editor_route(route),
        "document_hash": digest,
    }
    canonical_event_id = _safe_event_id(event_id)
    if canonical_event_id is not None:
        payload["event_id"] = canonical_event_id

    if event_type == AUTO_COMPILE_TOGGLED:
        if not isinstance(enabled, bool):
            return None
        payload["enabled"] = enabled
    elif event_type == SYNCTEX_USED:
        if not isinstance(direction, str) or direction not in SYNCTEX_DIRECTIONS:
            return None
        payload["direction"] = direction

    return payload


async def resolve_editor_plan(db: AsyncSession, user_id: str | None) -> str:
    """Server-derived plan family; never trust a client-supplied plan."""

    if not user_id:
        return "free"
    row = await db.execute(select(User.subscription_plan).where(User.id == user_id))
    raw = row.scalar_one_or_none()
    return normalize_plan(raw)


async def _latest_toggle(
    db: AsyncSession,
    *,
    user_id: str,
    document_hash: str,
    mode: str,
    action: str,
) -> tuple[datetime, bool] | None:
    row = (
        await db.execute(
            select(UsageAnalytics.created_at, UsageAnalytics.event_metadata)
            .where(
                UsageAnalytics.action == action,
                UsageAnalytics.user_id == user_id,
                UsageAnalytics.event_metadata["document_hash"].as_string()
                == document_hash,
                UsageAnalytics.event_metadata["mode"].as_string() == mode,
            )
            .order_by(UsageAnalytics.created_at.desc())
            .limit(1)
        )
    ).first()
    if row is None or not isinstance(row.created_at, datetime):
        return None
    metadata = row.event_metadata if isinstance(row.event_metadata, Mapping) else {}
    enabled = metadata.get("enabled")
    if not isinstance(enabled, bool):
        return None
    return row.created_at, enabled


async def record_editor_events(
    db: AsyncSession,
    events: Sequence[Mapping[str, Any]],
    *,
    user_id: str,
    plan: str,
) -> dict[str, int]:
    """Validate, deduplicate and append editor events to ``usage_analytics``."""

    now = datetime.now(timezone.utc)
    normalized: list[tuple[str, dict[str, Any]]] = []
    rejected = 0
    for raw in events:
        event_type = raw.get("event_type")
        metadata = normalize_editor_event(
            event_type=event_type,
            mode=raw.get("mode"),
            route=raw.get("route"),
            document_hash=raw.get("document_hash"),
            document_id=raw.get("document_id"),
            enabled=raw.get("enabled"),
            direction=raw.get("direction"),
            event_id=raw.get("event_id"),
            plan=plan,
        )
        if metadata is None:
            rejected += 1
            continue
        normalized.append((str(event_type), metadata))

    fresh: list[tuple[str, dict[str, Any]]] = []
    duplicates = 0
    seen_event_ids: set[str] = set()
    batch_toggles: dict[str, tuple[bool, datetime]] = {}

    for action, metadata in normalized:
        event_id = metadata.get("event_id")
        if isinstance(event_id, str):
            if event_id in seen_event_ids:
                duplicates += 1
                continue
            await db.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"editor-event:{user_id}:{event_id}"},
            )
            existing = (
                await db.execute(
                    select(UsageAnalytics.id)
                    .where(
                        UsageAnalytics.user_id == user_id,
                        UsageAnalytics.action.in_(EDITOR_ACTIONS),
                        UsageAnalytics.event_metadata["event_id"].as_string()
                        == event_id,
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if existing is not None:
                duplicates += 1
                continue
            seen_event_ids.add(event_id)

        if action == AUTO_COMPILE_TOGGLED:
            document_hash = str(metadata["document_hash"])
            mode = str(metadata["mode"])
            enabled = bool(metadata["enabled"])
            key = f"{document_hash}:{mode}"
            previous = batch_toggles.get(key)
            if previous is not None:
                previous_enabled, previous_at = previous
                if (
                    previous_enabled is enabled
                    and now - previous_at <= timedelta(seconds=TOGGLE_DEDUPE_SECONDS)
                ):
                    duplicates += 1
                    continue
                batch_toggles[key] = (enabled, now)
            else:
                await db.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                    {"key": f"editor-toggle:{user_id}:{key}"},
                )
                latest = await _latest_toggle(
                    db,
                    user_id=user_id,
                    document_hash=document_hash,
                    mode=mode,
                    action=action,
                )
                if (
                    latest is not None
                    and latest[1] is enabled
                    and now - latest[0] <= timedelta(seconds=TOGGLE_DEDUPE_SECONDS)
                ):
                    duplicates += 1
                    continue
                batch_toggles[key] = (enabled, now)

        fresh.append((action, metadata))

    if fresh:
        for action, metadata in fresh:
            db.add(
                UsageAnalytics(
                    user_id=user_id,
                    device_fingerprint=None,
                    action=action,
                    resource_type=EDITOR_RESOURCE_TYPE,
                    event_metadata=metadata,
                    ip_address=None,
                    user_agent=None,
                    created_at=now,
                )
            )
    # Commit even when every event was deduplicated so advisory locks acquired
    # during the checks are released with the request transaction.
    await db.commit()

    return {
        "accepted": len(fresh),
        "rejected": rejected,
        "deduplicated": duplicates,
    }


# --------------------------------------------------------------------------- #
#  Aggregate reporting                                                        #
# --------------------------------------------------------------------------- #


def _resolve_period(
    *,
    days: int,
    start_date: date | None,
    end_date: date | None,
    now: datetime | None = None,
) -> tuple[datetime, datetime]:
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


def _identity(user_id: Any, document_hash: Any) -> str | None:
    if isinstance(user_id, str) and user_id:
        return f"u:{user_id}"
    if isinstance(document_hash, str) and document_hash:
        return f"d:{document_hash}"
    return None


def _mode_order(mode: str) -> int:
    try:
        return EDITOR_MODES.index(mode)
    except ValueError:
        return len(EDITOR_MODES)


def _percentile(values: Sequence[float], quantile: float) -> float | None:
    samples = sorted(value for value in values if math.isfinite(value))
    if not samples:
        return None
    if len(samples) == 1:
        return round(samples[0], 3)
    position = (len(samples) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(samples[lower], 3)
    weight = position - lower
    return round(samples[lower] * (1.0 - weight) + samples[upper] * weight, 3)


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator * 100, 2)


def _share(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(count / total * 100, 2)


def _plan_label(plan: str) -> str:
    return " ".join(part.capitalize() for part in plan.replace("_", " ").split())


@dataclass
class _AdoptionBucket:
    selections: int = 0
    users: set[str] = field(default_factory=set)
    documents: set[str] = field(default_factory=set)

    def add(self, identity: str | None, document_hash: str) -> None:
        self.selections += 1
        if identity is not None:
            self.users.add(identity)
        self.documents.add(document_hash)


@dataclass
class _CompileBucket:
    compilations: int = 0
    completed: int = 0
    failed: int = 0
    cancelled: int = 0
    other: int = 0
    durations: list[float] = field(default_factory=list)
    users: set[str] = field(default_factory=set)
    documents: set[str] = field(default_factory=set)

    def add(self, status: str, duration: Any, identity: str | None, doc: str | None) -> None:
        self.compilations += 1
        if status == "completed":
            self.completed += 1
            if isinstance(duration, (int, float)) and math.isfinite(float(duration)) and float(duration) >= 0:
                self.durations.append(float(duration))
        elif status == "failed":
            self.failed += 1
        elif status == "cancelled":
            self.cancelled += 1
        else:
            self.other += 1
        if identity is not None:
            self.users.add(identity)
        if doc is not None:
            self.documents.add(doc)


def _compile_summary(bucket: _CompileBucket, *, sparse_threshold: int) -> dict[str, Any]:
    terminal = bucket.completed + bucket.failed
    samples = len(bucket.durations)
    return {
        "compilations": bucket.compilations,
        "completed": bucket.completed,
        "failed": bucket.failed,
        "cancelled": bucket.cancelled,
        "other": bucket.other,
        "success_rate_pct": _rate(bucket.completed, terminal),
        "p50_seconds": _percentile(bucket.durations, 0.5),
        "p95_seconds": _percentile(bucket.durations, 0.95),
        "mean_seconds": (
            round(sum(bucket.durations) / samples, 3) if samples else None
        ),
        "samples": samples,
        "sparse": samples < sparse_threshold,
        "users": len(bucket.users),
        "documents": len(bucket.documents),
    }


def _hidden_compile_summary() -> dict[str, Any]:
    return {
        "compilations": None,
        "completed": None,
        "failed": None,
        "cancelled": None,
        "other": None,
        "success_rate_pct": None,
        "p50_seconds": None,
        "p95_seconds": None,
        "mean_seconds": None,
        "samples": None,
        "sparse": True,
        "users": None,
        "documents": None,
        "suppressed": True,
    }


class EditorModeAnalyticsService:
    """Record privacy-safe editor events and publish an aggregate-only report."""

    async def snapshot(
        self,
        db: AsyncSession,
        *,
        days: int = 30,
        start_date: date | None = None,
        end_date: date | None = None,
        plan: str | None = None,
    ) -> dict[str, Any]:
        start_at, end_at = _resolve_period(
            days=days, start_date=start_date, end_date=end_date
        )
        plan_filter = (
            normalize_plan(plan) if isinstance(plan, str) and plan.strip() else None
        )

        event_filters = [
            UsageAnalytics.action.in_(EDITOR_ACTIONS),
            UsageAnalytics.created_at >= start_at - MODE_ATTRIBUTION_LOOKBACK,
            UsageAnalytics.created_at < end_at,
        ]
        if plan_filter is not None:
            event_filters.append(
                UsageAnalytics.event_metadata["plan"].as_string() == plan_filter
            )
        event_rows = (
            await db.execute(
                select(
                    UsageAnalytics.user_id,
                    UsageAnalytics.action,
                    UsageAnalytics.event_metadata,
                    UsageAnalytics.created_at,
                )
                .where(*event_filters)
                .order_by(UsageAnalytics.created_at, UsageAnalytics.id)
                .limit(MAX_EVENT_ROWS + 1)
            )
        ).all()
        truncated_events = len(event_rows) > MAX_EVENT_ROWS
        event_rows = event_rows[:MAX_EVENT_ROWS]

        adoption_by_mode: dict[str, _AdoptionBucket] = {}
        adoption_by_plan: dict[str, _AdoptionBucket] = {}
        adoption_by_plan_mode: dict[tuple[str, str], _AdoptionBucket] = {}
        adoption_by_day: dict[str, _AdoptionBucket] = {}
        auto_users: set[str] = set()
        auto_documents: set[str] = set()
        auto_enabled = 0
        auto_disabled = 0
        auto_events = 0
        sync_users: set[str] = set()
        sync_documents: set[str] = set()
        sync_events = 0
        sync_by_direction: Counter[str] = Counter()
        mode_users: set[str] = set()
        mode_documents: set[str] = set()
        mode_events = 0
        invalid_rows = 0
        events_in_period = 0
        document_modes: dict[str, list[tuple[datetime, str]]] = {}

        for user_id, action, metadata, created_at in event_rows:
            if not isinstance(metadata, Mapping) or not isinstance(created_at, datetime):
                invalid_rows += 1
                continue
            event = normalize_editor_event(
                event_type=action,
                mode=metadata.get("mode"),
                route=metadata.get("route"),
                document_hash=metadata.get("document_hash"),
                enabled=metadata.get("enabled"),
                direction=metadata.get("direction"),
                event_id=metadata.get("event_id"),
                plan=metadata.get("plan"),
            )
            if event is None:
                invalid_rows += 1
                continue

            document_hash = str(event["document_hash"])
            mode = str(event["mode"])
            event_plan = str(event["plan"])
            if action == EDITOR_MODE_SELECTED:
                timeline = document_modes.setdefault(document_hash, [])
                timeline.append((created_at, mode))

            if created_at < start_at:
                continue

            identity = _identity(user_id, document_hash)
            events_in_period += 1
            if action == EDITOR_MODE_SELECTED:
                mode_events += 1
                if identity is not None:
                    mode_users.add(identity)
                mode_documents.add(document_hash)
                adoption_by_mode.setdefault(mode, _AdoptionBucket()).add(
                    identity, document_hash
                )
                adoption_by_plan.setdefault(event_plan, _AdoptionBucket()).add(
                    identity, document_hash
                )
                adoption_by_plan_mode.setdefault(
                    (event_plan, mode), _AdoptionBucket()
                ).add(identity, document_hash)
                adoption_by_day.setdefault(
                    created_at.date().isoformat(), _AdoptionBucket()
                ).add(identity, document_hash)
            elif action == AUTO_COMPILE_TOGGLED:
                auto_events += 1
                if identity is not None:
                    auto_users.add(identity)
                auto_documents.add(document_hash)
                if event.get("enabled") is True:
                    auto_enabled += 1
                else:
                    auto_disabled += 1
            elif action == SYNCTEX_USED:
                sync_events += 1
                if identity is not None:
                    sync_users.add(identity)
                sync_documents.add(document_hash)
                sync_by_direction[str(event.get("direction"))] += 1

        for timeline in document_modes.values():
            timeline.sort(key=lambda item: item[0])

        compile_filters = [
            Compilation.created_at >= start_at,
            Compilation.created_at < end_at,
        ]
        if plan_filter is not None:
            compile_filters.append(Compilation.plan_family == plan_filter)
        compile_rows = (
            await db.execute(
                select(
                    Compilation.user_id,
                    Compilation.resume_id,
                    Compilation.status,
                    Compilation.compilation_time,
                    Compilation.created_at,
                )
                .where(*compile_filters)
                .order_by(Compilation.created_at)
                .limit(MAX_COMPILATION_ROWS + 1)
            )
        ).all()
        truncated_compilations = len(compile_rows) > MAX_COMPILATION_ROWS
        compile_rows = compile_rows[:MAX_COMPILATION_ROWS]

        compile_by_mode: dict[str, _CompileBucket] = {
            mode: _CompileBucket() for mode in (*EDITOR_MODES, UNKNOWN_MODE)
        }
        compile_users: set[str] = set()
        compile_documents: set[str] = set()
        total_compilations = 0
        unknown_compilations = 0

        for user_id, resume_id, status, duration, created_at in compile_rows:
            if not isinstance(created_at, datetime):
                continue
            total_compilations += 1
            doc_hash = (
                hash_document_identifier(str(resume_id)) if resume_id is not None else None
            )
            mode = UNKNOWN_MODE
            if doc_hash is not None:
                timeline = document_modes.get(doc_hash, [])
                if timeline:
                    times = [item[0] for item in timeline]
                    index = bisect_right(times, created_at) - 1
                    if index >= 0:
                        selected_at, selected_mode = timeline[index]
                        if created_at - selected_at <= MODE_ATTRIBUTION_LOOKBACK:
                            mode = selected_mode
            if mode == UNKNOWN_MODE:
                unknown_compilations += 1
            identity = _identity(user_id, doc_hash)
            if identity is not None:
                compile_users.add(identity)
            if doc_hash is not None:
                compile_documents.add(doc_hash)
            compile_by_mode.setdefault(mode, _CompileBucket()).add(
                str(status or ""), duration, identity, doc_hash
            )

        all_users = mode_users | auto_users | sync_users | compile_users
        suppressed = 0 < len(all_users) < MIN_GROUP_SIZE

        suppressed_plan_rows = sum(
            1 for bucket in adoption_by_plan.values() if len(bucket.users) < MIN_GROUP_SIZE
        )
        suppressed_mode_rows = sum(
            1 for bucket in adoption_by_mode.values() if len(bucket.users) < MIN_GROUP_SIZE
        )
        suppressed_plan_mode_rows = sum(
            1
            for bucket in adoption_by_plan_mode.values()
            if len(bucket.users) < MIN_GROUP_SIZE
        )
        suppressed_day_rows = sum(
            1 for bucket in adoption_by_day.values() if len(bucket.users) < MIN_GROUP_SIZE
        )
        suppressed_compile_modes = sum(
            1
            for bucket in compile_by_mode.values()
            if bucket.compilations > 0 and len(bucket.users) < MIN_GROUP_SIZE
        )
        compile_suppressed = suppressed_compile_modes > 0
        auto_suppressed = 0 < len(auto_users) < MIN_GROUP_SIZE
        sync_suppressed = 0 < len(sync_users) < MIN_GROUP_SIZE

        mode_selection_total = sum(
            bucket.selections for bucket in adoption_by_mode.values()
        )
        # Bucket rows below the cohort floor are hidden, but the top-level total
        # is a whole-population count and remains useful. Hidden plan slices do
        # not let a viewer recover an exact 1-4 count.
        adoption_totals_visible = not suppressed

        if suppressed:
            summary: dict[str, Any] = {
                "mode_selections": None,
                "mode_users": None,
                "documents": None,
                "auto_compile_toggles": None,
                "auto_compile_users": None,
                "synctex_events": None,
                "synctex_users": None,
                "compilations": None,
                "attributed_compilations": None,
                "unknown_mode_compilations": None,
                "completed_compilations": None,
                "failed_compilations": None,
                "success_rate_pct": None,
                "p50_seconds": None,
                "p95_seconds": None,
                "auto_compile_enabled_toggles": None,
                "auto_compile_disabled_toggles": None,
                "synctex_source_to_pdf": None,
                "synctex_pdf_to_source": None,
            }
        else:
            total_completed = sum(bucket.completed for bucket in compile_by_mode.values())
            total_failed = sum(bucket.failed for bucket in compile_by_mode.values())
            all_durations = [
                duration
                for bucket in compile_by_mode.values()
                for duration in bucket.durations
            ]
            summary = {
                "mode_selections": mode_selection_total if adoption_totals_visible else None,
                "mode_users": len(mode_users) if adoption_totals_visible else None,
                "documents": len(mode_documents) if adoption_totals_visible else None,
                "auto_compile_toggles": None if auto_suppressed else auto_events,
                "auto_compile_users": None if auto_suppressed else len(auto_users),
                "synctex_events": None if sync_suppressed else sync_events,
                "synctex_users": None if sync_suppressed else len(sync_users),
                "compilations": None if compile_suppressed else total_compilations,
                "attributed_compilations": None
                if compile_suppressed
                else total_compilations - unknown_compilations,
                "unknown_mode_compilations": None
                if compile_suppressed
                else unknown_compilations,
                "completed_compilations": None if compile_suppressed else total_completed,
                "failed_compilations": None if compile_suppressed else total_failed,
                "success_rate_pct": None
                if compile_suppressed
                else _rate(total_completed, total_completed + total_failed),
                "p50_seconds": None
                if compile_suppressed
                else _percentile(all_durations, 0.5),
                "p95_seconds": None
                if compile_suppressed
                else _percentile(all_durations, 0.95),
                "auto_compile_enabled_toggles": None
                if auto_suppressed
                else auto_enabled,
                "auto_compile_disabled_toggles": None
                if auto_suppressed
                else auto_disabled,
                "synctex_source_to_pdf": None
                if sync_suppressed
                else sync_by_direction.get("source_to_pdf", 0),
                "synctex_pdf_to_source": None
                if sync_suppressed
                else sync_by_direction.get("pdf_to_source", 0),
            }

        if suppressed:
            adoption_rows: list[dict[str, Any]] = []
            plan_rows: list[dict[str, Any]] = []
            plan_mode_rows: list[dict[str, Any]] = []
            trend_rows: list[dict[str, Any]] = []
            compile_rows_payload: list[dict[str, Any]] = []
        else:
            adoption_rows = []
            for mode in (*EDITOR_MODES,):
                bucket = adoption_by_mode.get(mode)
                if bucket is None or len(bucket.users) < MIN_GROUP_SIZE:
                    continue
                adoption_rows.append(
                    {
                        "mode": mode,
                        "label": MODE_LABELS[mode],
                        "selections": bucket.selections,
                        "users": len(bucket.users),
                        "documents": len(bucket.documents),
                        "share_pct": _share(bucket.selections, mode_selection_total),
                        "by_plan": [
                            {
                                "plan": plan_key,
                                "label": _plan_label(plan_key),
                                "selections": plan_bucket.selections,
                                "users": len(plan_bucket.users),
                            }
                            for (plan_key, mode_key), plan_bucket in sorted(
                                adoption_by_plan_mode.items()
                            )
                            if mode_key == mode and len(plan_bucket.users) >= MIN_GROUP_SIZE
                        ],
                    }
                )
            adoption_rows.sort(
                key=lambda row: (-row["selections"], _mode_order(row["mode"]))
            )

            plan_rows = []
            for plan_key, bucket in adoption_by_plan.items():
                if len(bucket.users) < MIN_GROUP_SIZE:
                    continue
                plan_rows.append(
                    {
                        "plan": plan_key,
                        "label": _plan_label(plan_key),
                        "selections": bucket.selections,
                        "users": len(bucket.users),
                        "documents": len(bucket.documents),
                        "share_pct": _share(bucket.selections, mode_selection_total),
                        "by_mode": [
                            {
                                "mode": mode_key,
                                "label": MODE_LABELS[mode_key],
                                "selections": mode_bucket.selections,
                                "users": len(mode_bucket.users),
                            }
                            for (plan_key_iter, mode_key), mode_bucket in sorted(
                                adoption_by_plan_mode.items()
                            )
                            if plan_key_iter == plan_key
                            and len(mode_bucket.users) >= MIN_GROUP_SIZE
                        ],
                    }
                )
            plan_rows.sort(key=lambda row: (-row["selections"], row["plan"]))

            plan_mode_rows = []
            for (plan_key, mode), bucket in adoption_by_plan_mode.items():
                if len(bucket.users) < MIN_GROUP_SIZE:
                    continue
                plan_mode_rows.append(
                    {
                        "plan": plan_key,
                        "plan_label": _plan_label(plan_key),
                        "mode": mode,
                        "mode_label": MODE_LABELS[mode],
                        "selections": bucket.selections,
                        "users": len(bucket.users),
                        "documents": len(bucket.documents),
                        "share_pct": _share(bucket.selections, mode_selection_total),
                    }
                )
            plan_mode_rows.sort(
                key=lambda row: (
                    row["plan"],
                    _mode_order(row["mode"]),
                )
            )

            trend_rows = []
            for day, bucket in sorted(adoption_by_day.items()):
                if len(bucket.users) < MIN_GROUP_SIZE:
                    continue
                trend_rows.append(
                    {
                        "date": day,
                        "mode_selections": bucket.selections,
                        "users": len(bucket.users),
                    }
                )

            compile_rows_payload = []
            for mode in (*EDITOR_MODES, UNKNOWN_MODE):
                bucket = compile_by_mode.get(mode)
                if bucket is None or bucket.compilations == 0:
                    continue
                if len(bucket.users) < MIN_GROUP_SIZE:
                    compile_rows_payload.append(
                        {
                            "mode": mode,
                            "label": MODE_LABELS[mode],
                            **_hidden_compile_summary(),
                        }
                    )
                    continue
                compile_rows_payload.append(
                    {
                        "mode": mode,
                        "label": MODE_LABELS[mode],
                        **_compile_summary(
                            bucket, sparse_threshold=SPARSE_COMPILE_SAMPLES
                        ),
                        "suppressed": False,
                    }
                )

        if suppressed:
            auto_payload = {
                "toggles": None,
                "enabled": None,
                "disabled": None,
                "users": None,
                "documents": None,
                "suppressed": True,
            }
            sync_payload = {
                "events": None,
                "users": None,
                "documents": None,
                "by_direction": [],
                "suppressed": True,
            }
        else:
            auto_payload = {
                "toggles": None if auto_suppressed else auto_events,
                "enabled": None if auto_suppressed else auto_enabled,
                "disabled": None if auto_suppressed else auto_disabled,
                "users": None if auto_suppressed else len(auto_users),
                "documents": None if auto_suppressed else len(auto_documents),
                "suppressed": auto_suppressed,
            }
            sync_payload = {
                "events": None if sync_suppressed else sync_events,
                "users": None if sync_suppressed else len(sync_users),
                "documents": None if sync_suppressed else len(sync_documents),
                "by_direction": []
                if sync_suppressed
                else [
                    {
                        "direction": direction,
                        "label": DIRECTION_LABELS[direction],
                        "count": sync_by_direction.get(direction, 0),
                    }
                    for direction in SYNCTEX_DIRECTIONS
                ],
                "suppressed": sync_suppressed,
            }

        reconciliation = {
            "editor_events": None if suppressed else events_in_period,
            "mode_selections": None
            if suppressed or not adoption_totals_visible
            else mode_events,
            "auto_compile_toggles": None if suppressed or auto_suppressed else auto_events,
            "synctex_events": None if suppressed or sync_suppressed else sync_events,
            "compilations": None if suppressed or compile_suppressed else total_compilations,
            "attributed_compilations": None
            if suppressed or compile_suppressed
            else total_compilations - unknown_compilations,
            "unattributed_compilations": None
            if suppressed or compile_suppressed
            else unknown_compilations,
            "invalid_rows": invalid_rows,
            "truncated_events": truncated_events,
            "truncated_compilations": truncated_compilations,
            "max_event_rows": MAX_EVENT_ROWS,
            "max_compilation_rows": MAX_COMPILATION_ROWS,
        }

        return {
            "days": max(1, (end_at.date() - start_at.date()).days),
            "period": {
                "start": start_at.isoformat(),
                "end": end_at.isoformat(),
                "timezone": "UTC",
            },
            "filters": {"plan": plan_filter},
            "minimum_cohort_size": MIN_GROUP_SIZE,
            "suppressed": suppressed,
            "suppression": {
                "minimum_users": MIN_GROUP_SIZE,
                "suppressed_mode_rows": suppressed_mode_rows,
                "suppressed_plan_rows": suppressed_plan_rows,
                "suppressed_plan_mode_rows": suppressed_plan_mode_rows,
                "suppressed_day_rows": suppressed_day_rows,
                "suppressed_compile_modes": suppressed_compile_modes,
                "adoption_totals_visible": adoption_totals_visible,
                "compile_totals_visible": not compile_suppressed,
                "auto_compile_visible": not auto_suppressed,
                "synctex_visible": not sync_suppressed,
                "rule": "Hide a bucket with fewer than 5 distinct users.",
            },
            "summary": summary,
            "adoption_by_mode": adoption_rows,
            "adoption_by_plan": plan_rows,
            "adoption_by_plan_mode": plan_mode_rows,
            "mode_adoption": adoption_rows,
            "mode_adoption_by_plan": plan_rows,
            "compile_by_mode": compile_rows_payload,
            "compile_outcomes_by_mode": compile_rows_payload,
            "auto_compile": auto_payload,
            "auto_compile_usage": auto_payload,
            "synctex": sync_payload,
            "synctex_usage": sync_payload,
            "trend": trend_rows,
            "reconciliation": reconciliation,
            "privacy": {
                "aggregate_only": True,
                "per_user_rows": False,
                "stored_event_fields": [
                    "mode",
                    "plan",
                    "route",
                    "document_hash",
                    "enabled",
                    "direction",
                    "event_id",
                ],
                "document_identifier": (
                    "SHA-256 hash of the document id only; the raw id is never "
                    "stored or returned."
                ),
                "consent_gate": (
                    "The browser emits these events only after analytics consent "
                    "is granted; withdrawal stops emission immediately."
                ),
                "content_fields_excluded": [
                    "LaTeX source or document content",
                    "prompts",
                    "filenames",
                    "document or resume ids",
                    "account identity in responses",
                    "IP address and user-agent",
                ],
            },
            "notes": [
                "Mode adoption counts editor mode selections in the selected period, by plan and mode.",
                "Compiles are attributed to the latest mode selected for the same document hash within 12 hours before the compile.",
                "Success rate is completed ÷ (completed + failed); cancelled compiles are excluded from the denominator.",
                "p50/p95 latency uses completed compiles with a finite non-negative duration.",
                "Auto-compile toggle retries are deduplicated server-side and in the client.",
                "Counts with fewer than 5 distinct users are hidden; hidden totals are withheld so small cohorts cannot be recovered.",
                "No document content, source, prompts, filenames, per-user rows or raw document ids are stored or returned.",
            ],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }


editor_mode_analytics_service = EditorModeAnalyticsService()
