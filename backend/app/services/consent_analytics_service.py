"""Privacy-safe analytics consent decision capture and aggregate reporting.

Data boundary
-------------
Consent choices (granted, denied, withdrawn) are stored as first-party
``usage_analytics`` rows so no schema migration is required. Each row records
only the canonical decision, a bounded surface label, a server timestamp, and an
opaque browser/session identifier supplied by the consent UI. Consent rows never
store an account id, email, name, IP address, user-agent string, résumé text,
LaTeX source, replay payload, or any free-form client metadata.

Why this is processed
---------------------
Recording the choice is necessary to honour it and to evidence that the visitor
was offered a free choice. The legal basis is the applicable legal obligation to
demonstrate consent plus, where no obligation applies, Latexy's legitimate
interest in auditing its own privacy controls. These records are used only for
aggregate compliance reporting; they are never used for advertising, profiling,
or re-identification. PostHog capture and session replay remain disabled until
the visitor grants consent, and a withdrawal stops them immediately.

Suppression
-----------
Every published count with a value of 1-4 is replaced with ``null`` and named in
``suppressed_cells``. A row's total is hidden whenever any component cell is
hidden so a small cohort cannot be recovered by subtraction. Rows whose every
cell is hidden are reported only as a suppressed-row count.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Mapping

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import models

UsageAnalytics = models.UsageAnalytics

MIN_COHORT_SIZE = 5
MAX_RANGE_DAYS = 366
MAX_SURFACE_ROWS = 50
MAX_EVENT_ROWS = 200_000

GRANTED = "granted"
DENIED = "denied"
WITHDRAWN = "withdrawn"
CONSENT_DECISIONS: tuple[str, ...] = (GRANTED, DENIED, WITHDRAWN)

CONSENT_ACTIONS: dict[str, str] = {
    GRANTED: "consent_granted",
    DENIED: "consent_denied",
    WITHDRAWN: "consent_withdrawn",
}
DECISION_BY_ACTION = {action: decision for decision, action in CONSENT_ACTIONS.items()}
CONSENT_EVENT_ACTIONS = tuple(CONSENT_ACTIONS.values())

SURFACE_LABELS: dict[str, str] = {
    "banner": "Consent banner",
    "privacy_choices": "Privacy choices",
    "privacy_page": "Privacy policy",
    "settings": "Privacy settings",
    "footer": "Footer",
    "other": "Other surface",
    "unknown": "Surface not recorded",
}
DEFAULT_SURFACE = "unknown"

_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def normalize_surface(value: Any) -> str:
    """Map an untrusted surface onto the bounded reporting vocabulary."""

    if value is None:
        return DEFAULT_SURFACE
    raw = str(value).strip().lower()
    if not raw:
        return DEFAULT_SURFACE
    return raw if raw in SURFACE_LABELS else "other"


def normalize_identifier(value: Any) -> str | None:
    """Keep an opaque client identifier only when it is a bounded safe token."""

    if value is None:
        return None
    raw = str(value).strip()
    if not raw or _IDENTIFIER_PATTERN.fullmatch(raw) is None:
        return None
    return raw


def normalize_decision(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw not in CONSENT_DECISIONS:
        raise ValueError("decision must be granted, denied or withdrawn")
    return raw


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
        end_at = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=timezone.utc)
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


def _empty_counts() -> dict[str, Any]:
    return {
        GRANTED: 0,
        DENIED: 0,
        WITHDRAWN: 0,
        "total": 0,
        "identities": set(),
    }


def _identity_key(event_id: Any, metadata: Mapping[str, Any] | None) -> str:
    """Stable opaque grouping key; never returned to a caller."""

    if isinstance(metadata, Mapping):
        session_id = normalize_identifier(metadata.get("session_id"))
        if session_id:
            return f"s:{session_id}"
        anonymous_id = normalize_identifier(metadata.get("anonymous_id"))
        if anonymous_id:
            return f"a:{anonymous_id}"
    return f"e:{event_id}"


def _latest_decisions(rows: list[tuple[Any, datetime, str, Any]]) -> dict[str, str]:
    latest: dict[str, tuple[datetime, str, str]] = {}
    for event_id, created_at, action, metadata in rows:
        decision = DECISION_BY_ACTION.get(action)
        if decision is None:
            continue
        key = _identity_key(event_id, metadata if isinstance(metadata, Mapping) else None)
        current = latest.get(key)
        sort_id = str(event_id or "")
        if current is None or (created_at, sort_id) >= (current[0], current[1]):
            latest[key] = (created_at, sort_id, decision)
    return {key: value[2] for key, value in latest.items()}


def _suppress_values(values: Mapping[str, int]) -> tuple[dict[str, int | None], list[str]]:
    """Hide 1-4 counts and the total when subtraction could recover one."""

    output: dict[str, int | None] = {}
    suppressed: list[str] = []
    for key in (GRANTED, DENIED, WITHDRAWN):
        value = int(values.get(key, 0) or 0)
        if 0 < value < MIN_COHORT_SIZE:
            output[key] = None
            suppressed.append(key)
        else:
            output[key] = value

    total = int(values.get("total", 0) or 0)
    if 0 < total < MIN_COHORT_SIZE or suppressed:
        output["total"] = None
        if total > 0 or suppressed:
            suppressed.append("total")
    else:
        output["total"] = total
    return output, suppressed


def _row_payload(
    base: Mapping[str, Any],
    counts: Mapping[str, Any],
) -> tuple[dict[str, Any], int]:
    values, suppressed = _suppress_values(counts)
    identities = int(counts.get("identities_count", len(counts.get("identities") or ())) or 0)
    if 0 < identities < MIN_COHORT_SIZE:
        unique_sessions: int | None = None
        suppressed.append("unique_sessions")
    else:
        unique_sessions = identities

    row = {
        **dict(base),
        GRANTED: values[GRANTED],
        DENIED: values[DENIED],
        WITHDRAWN: values[WITHDRAWN],
        "total": values["total"],
        "unique_sessions": unique_sessions,
        "suppressed_cells": sorted(set(suppressed)),
    }
    hidden_cells = len(row["suppressed_cells"])
    return row, hidden_cells


class ConsentAnalyticsService:
    """Record consent choices and publish only suppressed aggregate counts."""

    async def record_event(
        self,
        db: AsyncSession,
        *,
        decision: str,
        surface: Any = None,
        anonymous_id: Any = None,
        session_id: Any = None,
        event_id: Any = None,
    ) -> dict[str, Any]:
        """Persist one privacy-safe consent choice.

        The endpoint already validates the decision and forbids unknown fields;
        normalization here is defence in depth for callers and internal jobs.
        """

        canonical_decision = normalize_decision(decision)
        action = CONSENT_ACTIONS[canonical_decision]
        canonical_event_id = normalize_identifier(event_id)
        metadata: dict[str, Any] = {
            "decision": canonical_decision,
            "surface": normalize_surface(surface),
            "source": "first_party_consent",
        }
        anonymous = normalize_identifier(anonymous_id)
        session = normalize_identifier(session_id)
        if anonymous:
            metadata["anonymous_id"] = anonymous
        if session:
            metadata["session_id"] = session
        if canonical_event_id:
            metadata["event_id"] = canonical_event_id

        if canonical_event_id:
            # Serialize retries for one client event without a new table or
            # unique index. The lock is released with this transaction.
            await db.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"consent-event:{canonical_event_id}"},
            )
            existing = (
                await db.execute(
                    select(UsageAnalytics.id)
                    .where(
                        UsageAnalytics.action == action,
                        UsageAnalytics.event_metadata["event_id"].as_string()
                        == canonical_event_id,
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if existing is not None:
                return {
                    "accepted": True,
                    "recorded": False,
                    "duplicate": True,
                    "decision": canonical_decision,
                }

        db.add(
            UsageAnalytics(
                user_id=None,
                device_fingerprint=None,
                action=action,
                resource_type="consent",
                event_metadata=metadata,
                ip_address=None,
                user_agent=None,
            )
        )
        await db.commit()
        return {
            "accepted": True,
            "recorded": True,
            "duplicate": False,
            "decision": canonical_decision,
        }

    async def snapshot(
        self,
        db: AsyncSession,
        *,
        days: int = 30,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, Any]:
        start_at, end_at = _resolve_period(
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        span = end_at - start_at
        previous_start = start_at - span

        rows = (
            await db.execute(
                select(
                    UsageAnalytics.id,
                    UsageAnalytics.created_at,
                    UsageAnalytics.action,
                    UsageAnalytics.event_metadata,
                )
                .where(
                    UsageAnalytics.action.in_(CONSENT_EVENT_ACTIONS),
                    UsageAnalytics.created_at >= previous_start,
                    UsageAnalytics.created_at < end_at,
                )
                .order_by(UsageAnalytics.created_at, UsageAnalytics.id)
                .limit(MAX_EVENT_ROWS)
            )
        ).all()

        current_rows: list[tuple[Any, datetime, str, Any]] = []
        previous_withdrawals = 0
        for event_id, created_at, action, metadata in rows:
            if created_at is None:
                continue
            if created_at < start_at:
                if action == CONSENT_ACTIONS[WITHDRAWN]:
                    previous_withdrawals += 1
                continue
            current_rows.append((event_id, created_at, action, metadata))

        by_day: dict[str, dict[str, Any]] = {}
        by_surface: dict[str, dict[str, Any]] = {}
        summary = _empty_counts()
        current_withdrawals = 0

        for event_id, created_at, action, metadata in current_rows:
            decision = DECISION_BY_ACTION.get(action)
            if decision is None:
                continue
            safe_metadata = metadata if isinstance(metadata, Mapping) else None
            surface = normalize_surface(
                safe_metadata.get("surface") if safe_metadata is not None else None
            )
            identity = _identity_key(event_id, safe_metadata)
            day_key = created_at.date().isoformat()

            day = by_day.setdefault(day_key, {**_empty_counts(), "date": day_key})
            day[decision] += 1
            day["total"] += 1
            day["identities"].add(identity)

            surface_bucket = by_surface.setdefault(
                surface,
                {
                    **_empty_counts(),
                    "surface": surface,
                    "label": SURFACE_LABELS.get(surface, SURFACE_LABELS["other"]),
                },
            )
            surface_bucket[decision] += 1
            surface_bucket["total"] += 1
            surface_bucket["identities"].add(identity)

            summary[decision] += 1
            summary["total"] += 1
            summary["identities"].add(identity)
            if decision == WITHDRAWN:
                current_withdrawals += 1

        first_day = start_at.date()
        last_day = (end_at - timedelta(microseconds=1)).date()
        day_rows: list[dict[str, Any]] = []
        suppressed_rows = 0
        suppressed_cells = 0
        cursor = first_day
        while cursor <= last_day:
            key = cursor.isoformat()
            bucket = by_day.get(key) or {**_empty_counts(), "date": key}
            row, hidden = _row_payload({"date": key}, bucket)
            if hidden and all(row[item] is None for item in (*CONSENT_DECISIONS, "total")):
                suppressed_rows += 1
            suppressed_cells += hidden
            day_rows.append(row)
            cursor += timedelta(days=1)

        surface_rows: list[dict[str, Any]] = []
        for surface, bucket in by_surface.items():
            row, hidden = _row_payload(
                {
                    "surface": surface,
                    "label": bucket["label"],
                },
                bucket,
            )
            if hidden and all(row[item] is None for item in (*CONSENT_DECISIONS, "total")):
                suppressed_rows += 1
            suppressed_cells += hidden
            surface_rows.append(row)
        surface_rows.sort(key=lambda item: (-(item["total"] or 0), item["surface"]))

        latest = _latest_decisions(current_rows)
        eligible_sessions = sum(1 for decision in latest.values() if decision == GRANTED)
        consent_sessions = len(latest)
        replay_suppressed = (
            0 < consent_sessions < MIN_COHORT_SIZE
            or 0 < eligible_sessions < MIN_COHORT_SIZE
        )
        if 0 < consent_sessions < MIN_COHORT_SIZE:
            suppressed_cells += 1
        if 0 < eligible_sessions < MIN_COHORT_SIZE:
            suppressed_cells += 1
        replay_coverage_pct = (
            None
            if replay_suppressed or consent_sessions == 0
            else round((eligible_sessions / consent_sessions) * 100, 2)
        )
        replay_coverage = {
            "eligible_sessions": None if replay_suppressed else eligible_sessions,
            "sessions_with_consent": None
            if 0 < consent_sessions < MIN_COHORT_SIZE
            else consent_sessions,
            "coverage_pct": replay_coverage_pct,
            "suppressed": replay_suppressed,
            "definition": (
                "Share of sessions with a consent decision whose latest recorded "
                "state is granted. Withdrawal makes a session ineligible immediately."
            ),
            "posthog_capture": (
                "PostHog browser analytics and replay start only after a grant and "
                "remain off for denied or withdrawn sessions."
            ),
        }

        summary_values, summary_suppressed = _suppress_values(summary)
        summary_sessions = len(summary["identities"])
        summary_session_suppressed = 0 < summary_sessions < MIN_COHORT_SIZE
        if summary_session_suppressed:
            summary_suppressed.append("unique_sessions")
        summary_payload = {
            **summary_values,
            "unique_sessions": None if summary_session_suppressed else summary_sessions,
            "suppressed_cells": sorted(set(summary_suppressed)),
        }
        consent_coverage_pct = (
            None
            if summary_suppressed or summary["total"] == 0
            else round((summary[GRANTED] / summary["total"]) * 100, 2)
        )
        summary_payload["consent_coverage_pct"] = consent_coverage_pct
        suppressed_cells += len(summary_suppressed)
        if summary_suppressed:
            suppressed_rows += 1

        withdrawal_suppressed = (
            0 < current_withdrawals < MIN_COHORT_SIZE
            or 0 < previous_withdrawals < MIN_COHORT_SIZE
        )
        if withdrawal_suppressed:
            suppressed_cells += 2
        if current_withdrawals == 0 and previous_withdrawals == 0:
            percent_delta: float | None = 0.0
            baseline_zero = False
        elif previous_withdrawals == 0:
            percent_delta = None
            baseline_zero = True
        else:
            percent_delta = round(
                ((current_withdrawals - previous_withdrawals) / previous_withdrawals) * 100,
                2,
            )
            baseline_zero = False
        withdrawal_trend = {
            "current": None if withdrawal_suppressed else current_withdrawals,
            "previous": None if withdrawal_suppressed else previous_withdrawals,
            "absolute_delta": None
            if withdrawal_suppressed
            else current_withdrawals - previous_withdrawals,
            "percent_delta": None if withdrawal_suppressed else percent_delta,
            "baseline_zero": False if withdrawal_suppressed else baseline_zero,
            "suppressed": withdrawal_suppressed,
            "current_days": max(1, (end_at.date() - start_at.date()).days),
            "previous_days": max(1, (start_at.date() - previous_start.date()).days),
            "description": (
                "Consent withdrawals recorded in the selected period compared with "
                "the immediately preceding period of the same length."
            ),
        }

        truncated_surfaces = max(0, len(surface_rows) - MAX_SURFACE_ROWS)
        surface_rows = surface_rows[:MAX_SURFACE_ROWS]

        return {
            "days": max(1, (end_at.date() - start_at.date()).days),
            "period": {
                "start": start_at.isoformat(),
                "end": end_at.isoformat(),
                "timezone": "UTC",
            },
            "minimum_cohort_size": MIN_COHORT_SIZE,
            "summary": summary_payload,
            "by_day": day_rows,
            "by_surface": surface_rows,
            "counts_by_day": day_rows,
            "counts_by_surface": surface_rows,
            "withdrawal_trend": withdrawal_trend,
            "replay_coverage": replay_coverage,
            "suppressed_rows": suppressed_rows,
            "suppressed_cells": suppressed_cells,
            "truncated_surfaces": truncated_surfaces,
            "truncated_events": len(rows) >= MAX_EVENT_ROWS,
            "notes": [
                "Consent choices are first-party records containing only the decision, "
                "surface, server timestamp and an opaque session/browser identifier.",
                "No email, name, account id, résumé text, LaTeX source, IP address, "
                "user-agent string, or replay payload is stored or returned.",
                "Counts of 1-4 are suppressed and a total is hidden when subtraction "
                "could recover a suppressed cell; rows with no visible cell are omitted.",
                "PostHog analytics and session replay start only after a grant; denial "
                "and withdrawal stop them immediately.",
                "Legal basis: evidence of the visitor's choice and compliance with "
                "applicable consent rules; records are used only for aggregate reporting.",
            ],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }


consent_analytics_service = ConsentAnalyticsService()
