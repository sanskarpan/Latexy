"""Onboarding step completion and drop-off analytics (issue #2074).

Data boundary
-------------
Onboarding events are stored in the existing ``usage_analytics`` JSONB column
with the dedicated ``onboarding_step_*`` actions. A row may contain only the
bounded step key, flow version, a clamped duration, a bounded completion source,
an opaque client event id, and the authenticated account id. No form contents,
name, email, document text, IP address, user-agent string, or free-form client
metadata is accepted.

Consent
-------
Ingestion requires a prior first-party ``consent_granted`` record for the
visitor's opaque browser id. A later denial or withdrawal supersedes that grant,
so opt-out stops onboarding capture immediately. The browser client also checks
the shared analytics consent gate before calling the endpoint.

Completion reconciliation
-------------------------
A terminal flow event is either completion of the final ``get-started`` step or
a skip on any step. Receiving one marks ``preferences.has_onboarded`` true on the
same authenticated account, so the analytics outcome and the cross-device
preference cannot disagree. The admin report also cross-checks the two and
publishes an aggregate reconciliation block.

Suppression
-----------
Counts in the admin report are account cohorts, not raw event totals. A row with
one to four accounts in any published cell is hidden rather than rounded. A
segment or reconciliation block with a hidden component is hidden as a whole so
a small cohort cannot be recovered by subtraction.
"""

from __future__ import annotations

import math
import re
import statistics
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import models
from .consent_analytics_service import CONSENT_ACTIONS, DECISION_BY_ACTION

UsageAnalytics = models.UsageAnalytics
User = models.User

ONBOARDING_VIEWED = "onboarding_step_viewed"
ONBOARDING_COMPLETED = "onboarding_step_completed"
ONBOARDING_SKIPPED = "onboarding_step_skipped"
ONBOARDING_ACTIONS: tuple[str, ...] = (
    ONBOARDING_VIEWED,
    ONBOARDING_COMPLETED,
    ONBOARDING_SKIPPED,
)
ONBOARDING_RESOURCE_TYPE = "onboarding"

STEP_KEYS: tuple[str, ...] = ("welcome", "how-it-works", "features", "get-started")
STEP_LABELS: dict[str, str] = {
    "welcome": "Welcome",
    "how-it-works": "How it works",
    "features": "What you get",
    "get-started": "Get started",
}
UNKNOWN_STEP = "unknown"
UNKNOWN_LABEL = "Unknown step"

DEFAULT_FLOW_VERSION = "v1"
UNKNOWN_FLOW_VERSION = "unknown"
FLOW_VERSION_PATTERN = re.compile(r"^v[0-9]{1,3}(?:\.[0-9]{1,3})?$")

COMPLETION_SOURCES: frozenset[str] = frozenset(
    {
        "next",
        "cta",
        "link",
        "skip",
        "escape",
        "backdrop",
        "close",
        "unknown",
    }
)
DEFAULT_COMPLETION_SOURCE = "unknown"

SIGNUP_PROVIDERS: frozenset[str] = frozenset(
    {"email", "google", "github", "oidc", "passkey", "unknown"}
)
PROVIDER_LABELS: dict[str, str] = {
    "email": "Email",
    "google": "Google",
    "github": "GitHub",
    "oidc": "OIDC",
    "passkey": "Passkey",
    "unknown": "Unknown",
}
PLAN_LABELS: dict[str, str] = {
    "free": "Free",
    "basic": "Basic",
    "pro": "Pro",
    "byok": "BYOK",
    "team": "Team",
    "student": "Student",
    "unknown": "Unknown",
}

MIN_COHORT_SIZE = 5
MAX_RANGE_DAYS = 366
MAX_EVENT_ROWS = 200_000
MAX_SEGMENTS = 50
MAX_DURATION_MS = 24 * 60 * 60 * 1000
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class ConsentRequiredError(ValueError):
    """Raised when no current first-party analytics grant covers the visitor."""


def normalize_identifier(value: Any) -> str | None:
    """Keep an opaque client identifier only when it is a bounded safe token."""

    if value is None:
        return None
    raw = str(value).strip()
    if not raw or _IDENTIFIER_PATTERN.fullmatch(raw) is None:
        return None
    return raw


def normalize_step_key(value: Any) -> str | None:
    """Map a client step key onto the fixed onboarding vocabulary."""

    if not isinstance(value, str):
        return None
    raw = value.strip().lower()
    if raw in STEP_LABELS:
        return raw
    return None


def normalize_flow_version(value: Any) -> str:
    """Bound a flow version to a short ``vN``/``vN.N`` label."""

    if value is None:
        return DEFAULT_FLOW_VERSION
    raw = str(value).strip().lower()
    if not raw:
        return DEFAULT_FLOW_VERSION
    if FLOW_VERSION_PATTERN.fullmatch(raw) is not None:
        return raw
    return UNKNOWN_FLOW_VERSION


def normalize_completion_source(value: Any) -> str:
    if value is None:
        return DEFAULT_COMPLETION_SOURCE
    raw = str(value).strip().lower()
    if not raw:
        return DEFAULT_COMPLETION_SOURCE
    return raw if raw in COMPLETION_SOURCES else DEFAULT_COMPLETION_SOURCE


def coerce_duration_ms(value: Any) -> int | None:
    """Clamp a client duration; bool, negative and non-finite values are invalid."""

    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0:
        return None
    return min(int(numeric), MAX_DURATION_MS)


def _normalize_provider(value: Any) -> str:
    raw = str(value or "").strip().lower()
    return raw if raw in SIGNUP_PROVIDERS else "unknown"


def _normalize_plan(value: Any) -> str:
    raw = str(value or "").strip().lower()
    return raw[:50] or "unknown"


def _segment_label(dimension: str, key: str) -> str:
    labels = PROVIDER_LABELS if dimension == "provider" else PLAN_LABELS
    return labels.get(key, key.replace("_", " ").title())


def _preference_on(metadata: Any) -> bool:
    if not isinstance(metadata, Mapping):
        return False
    preferences = metadata.get("preferences")
    if not isinstance(preferences, Mapping):
        return False
    return preferences.get("has_onboarded") is True


def _is_terminal_event(action: str, step_key: str) -> bool:
    return action == ONBOARDING_SKIPPED or (
        action == ONBOARDING_COMPLETED and step_key == "get-started"
    )


async def _latest_consent_decision(db: AsyncSession, anonymous_id: str) -> str | None:
    """Latest first-party consent choice for this opaque browser id."""

    action = (
        await db.execute(
            select(UsageAnalytics.action)
            .where(
                UsageAnalytics.action.in_(tuple(CONSENT_ACTIONS.values())),
                UsageAnalytics.event_metadata["anonymous_id"].as_string() == anonymous_id,
            )
            .order_by(UsageAnalytics.created_at.desc(), UsageAnalytics.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return DECISION_BY_ACTION.get(action) if action else None


async def _reconcile_completion(db: AsyncSession, user: User) -> bool:
    """Set ``has_onboarded`` true without disturbing other account preferences."""

    metadata = dict(user.user_metadata or {})
    preferences = dict(metadata.get("preferences") or {})
    if preferences.get("has_onboarded") is True:
        return False
    preferences["has_onboarded"] = True
    metadata["preferences"] = preferences
    user.user_metadata = metadata
    return True


class OnboardingAnalyticsService:
    """Record step events and publish suppressed, aggregate-only reporting."""

    async def record_event(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        action: str,
        step_key: Any,
        flow_version: Any = None,
        duration_ms: Any = None,
        completion_source: Any = None,
        event_id: Any,
        anonymous_id: Any,
    ) -> dict[str, Any]:
        canonical_action = str(action or "").strip().lower()
        if canonical_action not in ONBOARDING_ACTIONS:
            raise ValueError("action must be an onboarding step event")
        canonical_step = normalize_step_key(step_key)
        if canonical_step is None:
            raise ValueError("step_key is not a known onboarding step")
        canonical_event_id = normalize_identifier(event_id)
        if canonical_event_id is None:
            raise ValueError("event_id must be a bounded opaque identifier")
        canonical_anonymous_id = normalize_identifier(anonymous_id)
        if canonical_anonymous_id is None:
            raise ValueError("anonymous_id must be a bounded opaque identifier")

        decision = await _latest_consent_decision(db, canonical_anonymous_id)
        if decision != "granted":
            raise ConsentRequiredError("analytics consent is required")

        user = (
            await db.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if user is None:
            raise ValueError("authenticated account was not found")

        # Serialize retries for one client event without a schema change.
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"onboarding-event:{canonical_event_id}"},
        )
        existing = (
            await db.execute(
                select(UsageAnalytics.id)
                .where(
                    UsageAnalytics.action == canonical_action,
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
                "action": canonical_action,
                "completion_reconciled": False,
            }

        metadata: dict[str, Any] = {
            "event_id": canonical_event_id,
            "step_key": canonical_step,
            "flow_version": normalize_flow_version(flow_version),
        }
        duration = coerce_duration_ms(duration_ms)
        if duration is not None:
            metadata["duration_ms"] = duration
        if canonical_action in (ONBOARDING_COMPLETED, ONBOARDING_SKIPPED):
            metadata["completion_source"] = normalize_completion_source(
                completion_source
            )

        db.add(
            UsageAnalytics(
                user_id=user_id,
                device_fingerprint=None,
                action=canonical_action,
                resource_type=ONBOARDING_RESOURCE_TYPE,
                event_metadata=metadata,
                ip_address=None,
                user_agent=None,
            )
        )

        reconciled = False
        if _is_terminal_event(canonical_action, canonical_step):
            reconciled = await _reconcile_completion(db, user)

        await db.commit()
        return {
            "accepted": True,
            "recorded": True,
            "duplicate": False,
            "action": canonical_action,
            "completion_reconciled": reconciled,
        }

    async def snapshot(
        self,
        db: AsyncSession,
        *,
        days: int = 30,
        start_date: date | None = None,
        end_date: date | None = None,
        flow_version: str | None = None,
    ) -> dict[str, Any]:
        start_at, end_at = _resolve_period(
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        requested_version = (
            normalize_flow_version(flow_version) if flow_version is not None else None
        )

        rows = (
            await db.execute(
                select(
                    UsageAnalytics.id,
                    UsageAnalytics.user_id,
                    UsageAnalytics.action,
                    UsageAnalytics.event_metadata,
                    UsageAnalytics.created_at,
                    User.subscription_plan,
                    User.auth_provider,
                    User.user_metadata,
                )
                .join(User, User.id == UsageAnalytics.user_id, isouter=True)
                .where(
                    UsageAnalytics.action.in_(ONBOARDING_ACTIONS),
                    UsageAnalytics.created_at >= start_at,
                    UsageAnalytics.created_at < end_at,
                )
                .order_by(UsageAnalytics.created_at, UsageAnalytics.id)
                .limit(MAX_EVENT_ROWS)
            )
        ).all()

        events: list[dict[str, Any]] = []
        versions: dict[str, int] = defaultdict(int)
        for (
            event_id,
            user_id,
            action,
            metadata,
            created_at,
            plan,
            provider,
            user_metadata,
        ) in rows:
            if action not in ONBOARDING_ACTIONS or created_at is None:
                continue
            safe_metadata = metadata if isinstance(metadata, Mapping) else {}
            version = normalize_flow_version(safe_metadata.get("flow_version"))
            versions[version] += 1
            if requested_version is not None and version != requested_version:
                continue
            step = normalize_step_key(safe_metadata.get("step_key")) or UNKNOWN_STEP
            duration = coerce_duration_ms(safe_metadata.get("duration_ms"))
            events.append(
                {
                    "event_id": str(event_id),
                    "account": str(user_id) if user_id else None,
                    "action": action,
                    "step_key": step,
                    "flow_version": version,
                    "duration_ms": duration,
                    "plan": _normalize_plan(plan),
                    "provider": _normalize_provider(provider),
                    "preference_on": _preference_on(user_metadata),
                }
            )

        step_keys = list(STEP_KEYS)
        if any(event["step_key"] == UNKNOWN_STEP for event in events):
            step_keys.append(UNKNOWN_STEP)
        if requested_version is not None:
            step_keys = list(STEP_KEYS)

        steps = _step_rows(events, step_keys)
        summary = _summary(events)
        reconciliation = _reconciliation(events)
        by_plan, suppressed_plan, truncated_plan = _segment_rows(events, "plan")
        by_provider, suppressed_provider, truncated_provider = _segment_rows(
            events, "provider"
        )

        suppressed_rows = sum(1 for row in steps if row["suppressed"])
        suppressed_rows += sum(1 for row in by_plan if row["suppressed"])
        suppressed_rows += sum(1 for row in by_provider if row["suppressed"])
        suppressed_cells = sum(len(row["suppressed_cells"]) for row in steps)
        suppressed_cells += sum(len(row["suppressed_cells"]) for row in by_plan)
        suppressed_cells += sum(len(row["suppressed_cells"]) for row in by_provider)
        suppressed_cells += len(summary["suppressed_cells"])
        suppressed_cells += len(reconciliation["suppressed_cells"])

        notes = [
            "Only onboarding step, flow version, clamped duration, completion "
            "source, and an opaque event id are stored. No form contents, name, "
            "email, document text, IP address, or user-agent string is accepted.",
            "Ingestion requires a current first-party analytics grant; a later "
            "denial or withdrawal blocks new onboarding events immediately.",
            "Terminal completion of get-started or a skip marks the account "
            "preference has_onboarded true, and the report cross-checks it.",
            f"Rows with 1-{MIN_COHORT_SIZE - 1} accounts in any published cell are "
            f"hidden; {MIN_COHORT_SIZE} accounts is the minimum cohort size.",
            "Plan and signup provider are bounded server-owned labels joined from "
            "the account row; they are never accepted from the event payload.",
        ]

        return {
            "days": max(1, (end_at.date() - start_at.date()).days),
            "period": {
                "start": start_at.isoformat(),
                "end": end_at.isoformat(),
                "timezone": "UTC",
            },
            "minimum_cohort_size": MIN_COHORT_SIZE,
            "flow_version": requested_version,
            "available_flow_versions": [
                {"flow_version": version, "events": count}
                for version, count in sorted(versions.items())
            ],
            "summary": summary,
            "steps": steps,
            "completion_reconciliation": reconciliation,
            "by_plan": by_plan,
            "by_provider": by_provider,
            "suppressed_segments": {
                "plan": suppressed_plan,
                "provider": suppressed_provider,
            },
            "suppressed_rows": suppressed_rows,
            "suppressed_cells": suppressed_cells,
            "truncated_segments": {
                "plan": truncated_plan,
                "provider": truncated_provider,
            },
            "truncated_events": len(rows) >= MAX_EVENT_ROWS,
            "notes": notes,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }


def _resolve_period(
    *,
    days: int,
    start_date: date | None,
    end_date: date | None,
    now: datetime | None = None,
) -> tuple[datetime, datetime]:
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


def _rate(value: int, total: int) -> float:
    return round((value / total) * 100, 2) if total > 0 else 0.0


def _median_seconds(durations: Iterable[int | None]) -> float | None:
    values = [duration / 1000 for duration in durations if duration is not None]
    if not values:
        return None
    return round(float(statistics.median(values)), 2)


def _needs_suppression(values: Iterable[int]) -> bool:
    """True when any published cohort is between one and four accounts."""

    return any(0 < int(value) < MIN_COHORT_SIZE for value in values)


def _hide_row(row: dict[str, Any], keys: Sequence[str]) -> dict[str, Any]:
    for key in keys:
        row[key] = None
    row["suppressed"] = True
    row["suppressed_cells"] = list(keys)
    return row


def _step_row(step_key: str, events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    viewers: set[str] = set()
    completers: set[str] = set()
    skippers: set[str] = set()
    views = completions = skips = 0
    durations: list[int] = []
    for event in events:
        if event["step_key"] != step_key:
            continue
        action = event["action"]
        account = event["account"]
        if action == ONBOARDING_VIEWED:
            views += 1
            if account:
                viewers.add(account)
        elif action == ONBOARDING_COMPLETED:
            completions += 1
            if account:
                completers.add(account)
            if event["duration_ms"] is not None:
                durations.append(int(event["duration_ms"]))
        elif action == ONBOARDING_SKIPPED:
            skips += 1
            if account:
                skippers.add(account)

    acted = completers | skippers
    abandoned = len(viewers - acted)
    row: dict[str, Any] = {
        "step_key": step_key,
        "label": STEP_LABELS.get(step_key, UNKNOWN_LABEL),
        "step_index": STEP_KEYS.index(step_key) if step_key in STEP_KEYS else None,
        "views": views,
        "unique_viewers": len(viewers),
        "completions": completions,
        "unique_completers": len(completers),
        "skips": skips,
        "unique_skippers": len(skippers),
        "abandoned_accounts": abandoned,
        "drop_off_rate": _rate(abandoned, len(viewers)),
        "completion_rate": _rate(len(completers), len(viewers)),
        "skip_rate": _rate(len(skippers), len(viewers)),
        "median_duration_seconds": _median_seconds(durations),
        "suppressed": False,
        "suppressed_cells": [],
    }

    cohorts = (
        views,
        len(viewers),
        completions,
        len(completers),
        skips,
        len(skippers),
        abandoned,
    )
    if _needs_suppression(cohorts):
        _hide_row(
            row,
            (
                "views",
                "unique_viewers",
                "completions",
                "unique_completers",
                "skips",
                "unique_skippers",
                "abandoned_accounts",
                "drop_off_rate",
                "completion_rate",
                "skip_rate",
                "median_duration_seconds",
            ),
        )
    return row


def _step_rows(
    events: Sequence[Mapping[str, Any]], step_keys: Sequence[str]
) -> list[dict[str, Any]]:
    return [_step_row(step_key, events) for step_key in step_keys]


def _summary(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    accounts: set[str] = set()
    terminal: set[str] = set()
    completed: set[str] = set()
    skipped: set[str] = set()
    views = step_completions = skips = 0
    durations: list[int] = []
    for event in events:
        account = event["account"]
        if account:
            accounts.add(account)
        action = event["action"]
        if action == ONBOARDING_VIEWED:
            views += 1
        elif action == ONBOARDING_COMPLETED:
            step_completions += 1
            if event["duration_ms"] is not None:
                durations.append(int(event["duration_ms"]))
            if event["step_key"] == "get-started" and account:
                completed.add(account)
                terminal.add(account)
        elif action == ONBOARDING_SKIPPED:
            skips += 1
            if account:
                skipped.add(account)
                terminal.add(account)

    abandoned = len(accounts - terminal)
    row: dict[str, Any] = {
        "accounts": len(accounts),
        "views": views,
        "step_completions": step_completions,
        "completions": len(completed),
        "skips": len(skipped),
        "terminal_accounts": len(terminal),
        "abandoned_accounts": abandoned,
        "completion_rate": _rate(len(completed), len(accounts)),
        "skip_rate": _rate(len(skipped), len(accounts)),
        "drop_off_rate": _rate(abandoned, len(accounts)),
        "median_duration_seconds": _median_seconds(durations),
        "suppressed": False,
        "suppressed_cells": [],
    }
    cohorts = (
        len(accounts),
        views,
        step_completions,
        len(completed),
        len(skipped),
        len(terminal),
        abandoned,
    )
    if _needs_suppression(cohorts):
        _hide_row(
            row,
            (
                "accounts",
                "views",
                "step_completions",
                "completions",
                "skips",
                "terminal_accounts",
                "abandoned_accounts",
                "completion_rate",
                "skip_rate",
                "drop_off_rate",
                "median_duration_seconds",
            ),
        )
    return row


def _reconciliation(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    terminal_accounts: set[str] = set()
    completed_accounts: set[str] = set()
    skipped_accounts: set[str] = set()
    preference_by_account: dict[str, bool] = {}
    accounts_seen: set[str] = set()
    for event in events:
        account = event["account"]
        if not account:
            continue
        accounts_seen.add(account)
        preference_by_account[account] = event["preference_on"]
        if event["action"] == ONBOARDING_COMPLETED and event["step_key"] == "get-started":
            completed_accounts.add(account)
            terminal_accounts.add(account)
        elif event["action"] == ONBOARDING_SKIPPED:
            skipped_accounts.add(account)
            terminal_accounts.add(account)

    preference_on = {account for account in terminal_accounts if preference_by_account.get(account)}
    missing_preference = terminal_accounts - preference_on
    preference_without_terminal = {
        account
        for account in accounts_seen - terminal_accounts
        if preference_by_account.get(account)
    }
    values = {
        "completed_accounts": len(completed_accounts),
        "skipped_accounts": len(skipped_accounts),
        "terminal_accounts": len(terminal_accounts),
        "preference_on_accounts": len(preference_on),
        "reconciled_accounts": len(preference_on),
        "missing_preference_accounts": len(missing_preference),
        "preference_without_terminal_accounts": len(preference_without_terminal),
    }
    suppressed = any(0 < value < MIN_COHORT_SIZE for value in values.values())
    rate = (
        None
        if suppressed or not terminal_accounts
        else round((len(preference_on) / len(terminal_accounts)) * 100, 2)
    )
    payload: dict[str, Any] = {
        **values,
        "reconciled_rate": rate,
        "suppressed": suppressed,
        "suppressed_cells": sorted(values) if suppressed else [],
        "definition": (
            "Terminal events are completion of the get-started step or a skip on "
            "any step. Reconciled means the same account has has_onboarded=true. "
            "Missing preference counts terminal events whose account flag is not "
            "yet true; preference without terminal counts flagged accounts with "
            "no terminal event in this period."
        ),
    }
    if suppressed:
        for key in values:
            payload[key] = None
        payload["reconciled_rate"] = None
    return payload


def _segment_rows(
    events: Sequence[Mapping[str, Any]], dimension: str
) -> tuple[list[dict[str, Any]], int, int]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for event in events:
        grouped[str(event[dimension])].append(event)

    rows: list[dict[str, Any]] = []
    suppressed = 0
    for key, segment_events in grouped.items():
        summary = _summary(segment_events)
        row: dict[str, Any] = {
            "dimension": dimension,
            "key": key,
            "label": _segment_label(dimension, key),
            "accounts": summary["accounts"],
            "views": summary["views"],
            "completions": summary["completions"],
            "skips": summary["skips"],
            "drop_off_rate": summary["drop_off_rate"],
            "completion_rate": summary["completion_rate"],
            "skip_rate": summary["skip_rate"],
            "median_duration_seconds": summary["median_duration_seconds"],
            "suppressed": summary["suppressed"],
            "suppressed_cells": summary["suppressed_cells"],
            "steps": [] if summary["suppressed"] else _step_rows(segment_events, STEP_KEYS),
        }
        if summary["suppressed"]:
            suppressed += 1
        rows.append(row)

    rows.sort(key=lambda item: (-(item["accounts"] or 0), item["key"]))
    truncated = max(0, len(rows) - MAX_SEGMENTS)
    return rows[:MAX_SEGMENTS], suppressed, truncated


onboarding_analytics_service = OnboardingAnalyticsService()
