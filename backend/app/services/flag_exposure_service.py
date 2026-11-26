"""Feature-flag exposure capture and first-party outcome joins (issue #2157).

Data boundary
-------------
An exposure row lives in the existing ``usage_analytics`` JSONB column, so no
schema migration is required. A row contains only the operational flag key, the
server-derived treatment/control variant, the evaluated boolean, the UTC
evaluation-window label, a fixed source label, the authenticated account id and
a server timestamp. The opaque browser consent id is used only to verify a
current first-party analytics grant and is never stored. No email, name,
document text, prompt, token, IP address, user agent, provider payload, or
free-form client metadata is accepted or returned.

Consent
-------
The capture route is authenticated and also requires the latest first-party
consent decision for the supplied opaque browser id to be ``granted``. A denial
or withdrawal therefore stops exposure capture server-side even if a caller
bypasses the browser gate. The browser client checks the same shared gate before
calling the endpoint.

Dedupe
------
Exposure is recorded at most once per authenticated subject, flag and variant
per UTC evaluation window (one calendar day). A transaction-scoped advisory lock
plus an existence check makes retries and concurrent requests idempotent without
a new unique index.

Reporting
---------
The admin report is aggregate-only. Each operational flag exposes treatment and
control counts, distinct-subject sample sizes, and outcome rates for a 7-day and
a 30-day lookback. Subjects are assigned to the variant of their first exposure
in the selected lookback (intent-to-treat) so a mid-window flag toggle cannot
double-count one account across groups. Outcomes are observed from first
exposure until the earlier of first exposure + 7 days and now; recent exposures
are right-censored and reported as such.

Five-user suppression hides every group with 1-4 distinct subjects, every rate
whose numerator is 1-4, and every rate whose denominator is below five. A
difference is published only when both rates are visible.

Causality
---------
These groups are observational, not randomized. The response publishes a
descriptive-only claim policy and no pre-registered metric, so no causal
conclusion is supported by this surface.
"""

from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import models
from .consent_analytics_service import CONSENT_ACTIONS, DECISION_BY_ACTION, normalize_identifier
from .feature_flag_service import OPERATIONAL_FLAGS

UsageAnalytics = models.UsageAnalytics
Compilation = models.Compilation
Optimization = models.Optimization
Resume = models.Resume
Subscription = models.Subscription
Payment = models.Payment
FeatureFlag = models.FeatureFlag

FLAG_EXPOSED = "flag_exposed"
FLAG_EXPOSURE_RESOURCE_TYPE = "feature_flag"
FLAG_EXPOSURE_SOURCE = "first_party_flag_evaluation"

TREATMENT = "treatment"
CONTROL = "control"
VARIANTS: tuple[str, str] = (TREATMENT, CONTROL)
VARIANT_LABELS = {
    TREATMENT: "Treatment (flag on)",
    CONTROL: "Control (flag off)",
}

OPERATIONAL_FLAG_ORDER: tuple[str, ...] = (
    "trial_limits",
    "deep_analysis_trial",
    "compile_timeouts",
    "task_priority",
    "billing",
    "upgrade_ctas",
)

MIN_GROUP_SIZE = 5
OUTCOME_HORIZON_DAYS = 7
REPORT_WINDOWS: tuple[int, ...] = (7, 30)
MAX_LOOKBACK_DAYS = max(REPORT_WINDOWS)
MAX_EXPOSURE_ROWS = 200_000
MAX_OUTCOME_ROWS = 200_000

PAID_SUBSCRIPTION_STATUSES = frozenset(
    {"active", "cancel_scheduled", "past_due", "on_hold", "paused"}
)
SETTLED_PAYMENT_STATUSES = frozenset(
    {"paid", "captured", "partially_refunded", "refunded", "succeeded"}
)
# Exposure rows are not product activity, and consent decisions are privacy
# bookkeeping rather than activation or retention behaviour.
NON_ACTIVITY_ACTIONS: tuple[str, ...] = (FLAG_EXPOSED, *CONSENT_ACTIONS.values())

# No operational flag currently has a metric that was registered before
# exposure. Do not add a key here without a written hypothesis, a decision rule
# and a registration timestamp: the report only permits causal wording for a
# pre-registered metric.
PREREGISTERED_METRICS: Mapping[str, str] = {}

METRIC_DEFINITIONS: tuple[dict[str, str], ...] = (
    {
        "key": "activation",
        "label": "Activation",
        "kind": "outcome",
        "direction": "up",
        "definition": (
            "Share of subjects with at least one activation event in the outcome "
            "horizon: a r\u00e9sum\u00e9 created, an AI optimization, or another "
            "first-party product event. Exposure and consent-bookkeeping rows are "
            "excluded; completed compilations are measured separately."
        ),
    },
    {
        "key": "compile_success",
        "label": "Compile success",
        "kind": "outcome",
        "direction": "up",
        "definition": (
            "Share of subjects with at least one completed compilation in the "
            "outcome horizon after first exposure."
        ),
    },
    {
        "key": "checkout_started",
        "label": "Checkout started",
        "kind": "outcome",
        "direction": "up",
        "definition": (
            "Share of subjects with a first-party checkout intent (a subscription "
            "row created) in the outcome horizon after first exposure."
        ),
    },
    {
        "key": "retention_7d",
        "label": "7-day return",
        "kind": "outcome",
        "direction": "up",
        "definition": (
            "Share of subjects with a first-party usage event, r\u00e9sum\u00e9 "
            "creation, or AI optimization on a later UTC day than the "
            "first-exposure day and inside the outcome horizon. Compilations are "
            "tracked by compile success."
        ),
    },
    {
        "key": "compile_error_rate",
        "label": "Compile error rate",
        "kind": "guardrail",
        "direction": "down",
        "definition": (
            "Share of subjects with at least one failed compilation among subjects "
            "with any completed or failed compilation in the outcome horizon."
        ),
    },
    {
        "key": "checkout_abandonment_rate",
        "label": "Checkout abandonment",
        "kind": "guardrail",
        "direction": "down",
        "definition": (
            "Share of subjects with a checkout intent but no paid subscription or "
            "settled payment in the outcome horizon, among subjects with a checkout "
            "intent in that horizon."
        ),
    },
)

METRIC_BY_KEY = {definition["key"]: definition for definition in METRIC_DEFINITIONS}
GUARDRAIL_KEYS: tuple[str, ...] = tuple(
    definition["key"] for definition in METRIC_DEFINITIONS if definition["kind"] == "guardrail"
)


class ConsentRequiredError(ValueError):
    """Raised when no current first-party analytics grant covers the visitor."""


def normalize_flag_key(value: Any) -> str | None:
    """Return a canonical operational flag key, or ``None`` for anything else."""

    if not isinstance(value, str):
        return None
    raw = value.strip().lower()
    return raw if raw in OPERATIONAL_FLAGS else None


def variant_for(enabled: bool) -> str:
    """Map the evaluated boolean onto the bounded treatment/control vocabulary."""

    return TREATMENT if bool(enabled) else CONTROL


def evaluation_window(now: datetime | None = None) -> str:
    """One exposure window per subject/flag/variant per UTC calendar day."""

    current = now or datetime.now(timezone.utc)
    return current.astimezone(timezone.utc).date().isoformat()


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


async def record_flag_exposures(
    db: AsyncSession,
    *,
    user_id: str,
    anonymous_id: Any,
    flags: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Persist consent-covered flag evaluations, deduped per evaluation window."""

    canonical_anonymous_id = normalize_identifier(anonymous_id)
    if canonical_anonymous_id is None:
        raise ValueError("anonymous_id must be a bounded opaque identifier")

    decision = await _latest_consent_decision(db, canonical_anonymous_id)
    if decision != "granted":
        raise ConsentRequiredError("analytics consent is required")

    now = datetime.now(timezone.utc)
    window = evaluation_window(now)
    seen: set[tuple[str, str]] = set()
    accepted = 0
    duplicate = 0
    rejected = 0

    for item in flags:
        key = normalize_flag_key(item.get("key"))
        enabled = item.get("enabled")
        if key is None or not isinstance(enabled, bool):
            rejected += 1
            continue
        variant = variant_for(enabled)
        if (key, variant) in seen:
            duplicate += 1
            continue
        seen.add((key, variant))

        # Serialize concurrent retries for one subject/flag/variant/window
        # without a schema change. The lock is released with this transaction.
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"flag-exposure:{user_id}:{key}:{variant}:{window}"},
        )
        existing = (
            await db.execute(
                select(UsageAnalytics.id)
                .where(
                    UsageAnalytics.action == FLAG_EXPOSED,
                    UsageAnalytics.user_id == user_id,
                    UsageAnalytics.event_metadata["flag_key"].as_string() == key,
                    UsageAnalytics.event_metadata["variant"].as_string() == variant,
                    UsageAnalytics.event_metadata["window"].as_string() == window,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            duplicate += 1
            continue

        db.add(
            UsageAnalytics(
                user_id=user_id,
                device_fingerprint=None,
                action=FLAG_EXPOSED,
                resource_type=FLAG_EXPOSURE_RESOURCE_TYPE,
                event_metadata={
                    "flag_key": key,
                    "variant": variant,
                    "enabled": enabled,
                    "window": window,
                    "source": FLAG_EXPOSURE_SOURCE,
                },
                ip_address=None,
                user_agent=None,
                created_at=now,
            )
        )
        accepted += 1

    # Commit even when every item was deduplicated so advisory locks acquired
    # above are released with the request transaction.
    await db.commit()
    return {
        "accepted": accepted,
        "duplicate": duplicate,
        "rejected": rejected,
        "window": window,
    }


def _has_between(values: Sequence[datetime], start: datetime, end: datetime) -> bool:
    """True when a sorted timestamp list has an entry in ``[start, end)``."""

    if not values or start >= end:
        return False
    index = bisect_left(values, start)
    return index < len(values) and values[index] < end


def _suppressed_count(value: int) -> tuple[int | None, bool]:
    """Hide 1-4 counts; zero is safe to publish."""

    if 0 < value < MIN_GROUP_SIZE:
        return None, True
    return value, False


def _suppressed_rate(numerator: int, denominator: int) -> tuple[float | None, bool]:
    """Hide rates whose sample or numerator is below the five-user floor."""

    if denominator == 0:
        return None, False
    if denominator < MIN_GROUP_SIZE:
        return None, True
    if 0 < numerator < MIN_GROUP_SIZE:
        return None, True
    return round((numerator / denominator) * 100, 2), False


def _metric_cell(
    numerator: int,
    denominator: int,
    *,
    group_suppressed: bool,
) -> dict[str, Any]:
    if group_suppressed:
        return {
            "numerator": None,
            "denominator": None,
            "rate_pct": None,
            "suppressed": True,
        }
    visible_numerator, numerator_hidden = _suppressed_count(numerator)
    visible_denominator, denominator_hidden = _suppressed_count(denominator)
    rate, rate_hidden = _suppressed_rate(numerator, denominator)
    suppressed = numerator_hidden or denominator_hidden or rate_hidden
    if suppressed:
        visible_numerator = None
        visible_denominator = None
        rate = None
    return {
        "numerator": visible_numerator,
        "denominator": visible_denominator,
        "rate_pct": rate,
        "suppressed": suppressed,
    }


def _group_suppressed(subjects: int) -> bool:
    return 0 < subjects < MIN_GROUP_SIZE


class FlagExposureService:
    """Record consent-covered exposures and publish aggregate outcome joins."""

    async def record_exposures(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        anonymous_id: Any,
        flags: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        return await record_flag_exposures(
            db,
            user_id=user_id,
            anonymous_id=anonymous_id,
            flags=flags,
        )

    async def report(self, db: AsyncSession, *, now: datetime | None = None) -> dict[str, Any]:
        current = now or datetime.now(timezone.utc)
        window_bounds = {
            days: current - timedelta(days=days) for days in REPORT_WINDOWS
        }
        earliest = min(window_bounds.values())

        exposure_rows = (
            await db.execute(
                select(
                    UsageAnalytics.user_id,
                    UsageAnalytics.created_at,
                    UsageAnalytics.event_metadata,
                )
                .where(
                    UsageAnalytics.action == FLAG_EXPOSED,
                    UsageAnalytics.user_id.is_not(None),
                    UsageAnalytics.created_at >= earliest,
                    UsageAnalytics.created_at < current,
                )
                .order_by(UsageAnalytics.created_at, UsageAnalytics.id)
                .limit(MAX_EXPOSURE_ROWS)
            )
        ).all()

        rows_by_flag: dict[str, list[tuple[datetime, str, str]]] = defaultdict(list)
        for user_id, created_at, metadata in exposure_rows:
            if user_id is None or created_at is None or not isinstance(metadata, Mapping):
                continue
            key = metadata.get("flag_key")
            variant = metadata.get("variant")
            if key not in OPERATIONAL_FLAGS or variant not in VARIANTS:
                continue
            rows_by_flag[str(key)].append((created_at, str(user_id), str(variant)))

        # First exposure in each lookback determines the intent-to-treat group.
        cohorts: dict[str, dict[int, dict[str, dict[str, Any]]]] = {}
        all_subjects: set[str] = set()
        for key in OPERATIONAL_FLAG_ORDER:
            cohorts[key] = {}
            for days in REPORT_WINDOWS:
                start = window_bounds[days]
                cohort: dict[str, dict[str, Any]] = {}
                for created_at, subject, variant in rows_by_flag.get(key, ()):
                    if created_at < start or created_at >= current:
                        continue
                    entry = cohort.get(subject)
                    if entry is None:
                        cohort[subject] = {
                            "first_at": created_at,
                            "variant": variant,
                            "events": 1,
                        }
                    else:
                        entry["events"] += 1
                cohorts[key][days] = cohort
                all_subjects.update(cohort)

        outcome = await _load_outcomes(db, all_subjects, current)

        flag_rows = {
            row.key: row
            for row in (await db.execute(select(FeatureFlag))).scalars().all()
        }

        flags: list[dict[str, Any]] = []
        for key in OPERATIONAL_FLAG_ORDER:
            definition = flag_rows.get(key)
            flag_payload: dict[str, Any] = {
                "key": key,
                "label": definition.label if definition is not None else key.replace("_", " ").title(),
                "description": definition.description if definition is not None else None,
                "enabled": bool(definition.enabled) if definition is not None else True,
                "outcome_horizon_days": OUTCOME_HORIZON_DAYS,
                "minimum_group_size": MIN_GROUP_SIZE,
                "windows": {},
            }
            for days in REPORT_WINDOWS:
                flag_payload["windows"][str(days)] = _window_payload(
                    days=days,
                    start=window_bounds[days],
                    end=current,
                    cohort=cohorts[key][days],
                    outcome=outcome,
                )
            flags.append(flag_payload)

        return {
            "flags": flags,
            "windows": list(REPORT_WINDOWS),
            "minimum_group_size": MIN_GROUP_SIZE,
            "outcome_horizon_days": OUTCOME_HORIZON_DAYS,
            "metric_definitions": [dict(item) for item in METRIC_DEFINITIONS],
            "guardrail_metric_keys": list(GUARDRAIL_KEYS),
            "claim": {
                "causality": "descriptive_only",
                "preregistered_metric": None,
                "preregistered_metrics": dict(PREREGISTERED_METRICS),
                "message": (
                    "Exposure groups are observational, not randomized. These metrics "
                    "describe association only and support no causal claim. Causal "
                    "wording requires a metric, hypothesis and decision rule registered "
                    "before exposure; none is registered for the operational flags."
                ),
            },
            "notes": [
                "Exposure is recorded at most once per subject, flag and variant per "
                "UTC calendar day.",
                "A subject is assigned to the variant of their first exposure in the "
                "lookback so one account cannot be counted in both groups.",
                "Outcomes run from first exposure until the earlier of seven days and "
                "the report time; recent exposures are right-censored.",
                "Groups with 1-4 subjects are hidden, as are rates whose numerator is "
                "1-4 or whose denominator is below five.",
                "Only aggregate counts are returned: no account id, email, document "
                "content, prompt, token, IP address, user agent or provider payload.",
            ],
            "generated_at": current.isoformat(),
        }


def _window_payload(
    *,
    days: int,
    start: datetime,
    end: datetime,
    cohort: Mapping[str, Mapping[str, Any]],
    outcome: Mapping[str, Mapping[str, list[datetime]]],
) -> dict[str, Any]:
    groups: dict[str, dict[str, Any]] = {}
    group_subjects: dict[str, dict[str, Mapping[str, Any]]] = {TREATMENT: {}, CONTROL: {}}
    for subject, entry in cohort.items():
        group_subjects[str(entry["variant"])][subject] = entry

    treated_counts: dict[str, int] = {}
    for variant in VARIANTS:
        subjects = group_subjects[variant]
        suppressed = _group_suppressed(len(subjects))
        events = sum(int(entry["events"]) for entry in subjects.values())
        censored = sum(
            1
            for entry in subjects.values()
            if _horizon_end(entry["first_at"], end) < entry["first_at"] + timedelta(days=OUTCOME_HORIZON_DAYS)
        )
        visible_subjects, _ = _suppressed_count(len(subjects))
        if suppressed:
            visible_subjects = None
        visible_events, events_hidden = _suppressed_count(events)
        visible_censored, censored_hidden = _suppressed_count(censored)
        if suppressed or events_hidden:
            visible_events = None
        if suppressed or censored_hidden:
            visible_censored = None
        groups[variant] = {
            "variant": variant,
            "label": VARIANT_LABELS[variant],
            "exposure_events": visible_events,
            "sample_size": visible_subjects,
            "right_censored_subjects": visible_censored,
            "suppressed": suppressed,
            "suppression_reason": (
                "fewer_than_five_subjects" if suppressed else None
            ),
        }
        treated_counts[variant] = len(subjects)

    metrics: list[dict[str, Any]] = []
    for definition in METRIC_DEFINITIONS:
        key = definition["key"]
        treatment_cell = _metric_cell(
            *_metric_counts(key, group_subjects[TREATMENT], outcome, end),
            group_suppressed=_group_suppressed(treated_counts[TREATMENT]),
        )
        control_cell = _metric_cell(
            *_metric_counts(key, group_subjects[CONTROL], outcome, end),
            group_suppressed=_group_suppressed(treated_counts[CONTROL]),
        )
        treatment_rate = treatment_cell["rate_pct"]
        control_rate = control_cell["rate_pct"]
        comparable = treatment_rate is not None and control_rate is not None
        metrics.append(
            {
                "key": key,
                "label": definition["label"],
                "kind": definition["kind"],
                "direction": definition["direction"],
                "definition": definition["definition"],
                "treatment": treatment_cell,
                "control": control_cell,
                "difference_pp": (
                    round(float(treatment_rate) - float(control_rate), 2)
                    if comparable
                    else None
                ),
                "comparable": comparable,
            }
        )

    any_visible = any(not group["suppressed"] for group in groups.values())
    return {
        "days": days,
        "start_date": start.date().isoformat(),
        "end_date": end.date().isoformat(),
        "groups": groups,
        "metrics": metrics,
        "guardrails": [metric for metric in metrics if metric["kind"] == "guardrail"],
        "suppressed": not any_visible,
    }


def _metric_counts(
    metric_key: str,
    subjects: Mapping[str, Mapping[str, Any]],
    outcome: Mapping[str, Mapping[str, list[datetime]]],
    report_end: datetime,
) -> tuple[int, int]:
    if metric_key == "activation":
        numerator = 0
        denominator = len(subjects)
        for subject, entry in subjects.items():
            first_at = entry["first_at"]
            horizon = _horizon_end(first_at, report_end)
            if _has_between(outcome["activity"].get(subject, ()), first_at, horizon):
                numerator += 1
        return numerator, denominator
    if metric_key == "compile_success":
        numerator = 0
        denominator = len(subjects)
        for subject, entry in subjects.items():
            first_at = entry["first_at"]
            horizon = _horizon_end(first_at, report_end)
            if _has_between(outcome["compiled"].get(subject, ()), first_at, horizon):
                numerator += 1
        return numerator, denominator
    if metric_key == "checkout_started":
        numerator = 0
        denominator = len(subjects)
        for subject, entry in subjects.items():
            first_at = entry["first_at"]
            horizon = _horizon_end(first_at, report_end)
            if _has_between(outcome["checkout_started"].get(subject, ()), first_at, horizon):
                numerator += 1
        return numerator, denominator
    if metric_key == "retention_7d":
        numerator = 0
        denominator = len(subjects)
        for subject, entry in subjects.items():
            first_at = entry["first_at"]
            horizon = _horizon_end(first_at, report_end)
            next_day = _next_utc_day(first_at)
            if _has_between(outcome["activity"].get(subject, ()), next_day, horizon):
                numerator += 1
        return numerator, denominator
    if metric_key == "compile_error_rate":
        numerator = 0
        denominator = 0
        for subject, entry in subjects.items():
            first_at = entry["first_at"]
            horizon = _horizon_end(first_at, report_end)
            completed = _has_between(outcome["compiled"].get(subject, ()), first_at, horizon)
            failed = _has_between(outcome["failed_compile"].get(subject, ()), first_at, horizon)
            if completed or failed:
                denominator += 1
            if failed:
                numerator += 1
        return numerator, denominator
    if metric_key == "checkout_abandonment_rate":
        numerator = 0
        denominator = 0
        for subject, entry in subjects.items():
            first_at = entry["first_at"]
            horizon = _horizon_end(first_at, report_end)
            started = _has_between(outcome["checkout_started"].get(subject, ()), first_at, horizon)
            if not started:
                continue
            denominator += 1
            paid = _has_between(outcome["checkout_paid"].get(subject, ()), first_at, horizon)
            if not paid:
                numerator += 1
        return numerator, denominator
    return 0, 0


def _horizon_end(first_at: datetime, report_end: datetime) -> datetime:
    return min(first_at + timedelta(days=OUTCOME_HORIZON_DAYS), report_end)


def _next_utc_day(value: datetime) -> datetime:
    day = value.astimezone(timezone.utc).date() + timedelta(days=1)
    return datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)


def _append_time(target: dict[str, list[datetime]], user_id: Any, value: Any) -> None:
    if user_id is None or not isinstance(value, datetime):
        return
    target.setdefault(str(user_id), []).append(value)


async def _load_outcomes(
    db: AsyncSession,
    subjects: set[str],
    now: datetime,
) -> dict[str, dict[str, list[datetime]]]:
    """Load the first-party sources once for every subject in the report."""

    empty: dict[str, dict[str, list[datetime]]] = {
        "activity": {},
        "compiled": {},
        "failed_compile": {},
        "checkout_started": {},
        "checkout_paid": {},
    }
    if not subjects:
        return empty

    subject_ids = sorted(subjects)
    # Every exposure is inside the 30-day lookback, so its seven-day outcome
    # horizon ends no later than ``now``.
    outcome_start = now - timedelta(days=MAX_LOOKBACK_DAYS)
    outcome_end = now

    activity: dict[str, list[datetime]] = {}
    activity_rows = (
        await db.execute(
            select(UsageAnalytics.user_id, UsageAnalytics.created_at)
            .where(
                UsageAnalytics.user_id.in_(subject_ids),
                UsageAnalytics.created_at >= outcome_start,
                UsageAnalytics.created_at < outcome_end,
                UsageAnalytics.action.notin_(NON_ACTIVITY_ACTIONS),
            )
            .limit(MAX_OUTCOME_ROWS)
        )
    ).all()
    for user_id, created_at in activity_rows:
        _append_time(activity, user_id, created_at)

    compiled: dict[str, list[datetime]] = {}
    failed_compile: dict[str, list[datetime]] = {}
    compile_rows = (
        await db.execute(
            select(Compilation.user_id, Compilation.created_at, Compilation.status)
            .where(
                Compilation.user_id.in_(subject_ids),
                Compilation.created_at >= outcome_start,
                Compilation.created_at < outcome_end,
                Compilation.status.in_(("completed", "failed")),
            )
            .limit(MAX_OUTCOME_ROWS)
        )
    ).all()
    for user_id, created_at, status in compile_rows:
        if status == "completed":
            _append_time(compiled, user_id, created_at)
        elif status == "failed":
            _append_time(failed_compile, user_id, created_at)

    # A r\u00e9sum\u00e9 or optimization is a first-party activation signal even when
    # the usage-analytics row has not been written yet.
    for model, column in ((Resume, Resume.created_at), (Optimization, Optimization.created_at)):
        rows = (
            await db.execute(
                select(model.user_id, column)
                .where(
                    model.user_id.in_(subject_ids),
                    column >= outcome_start,
                    column < outcome_end,
                )
                .limit(MAX_OUTCOME_ROWS)
            )
        ).all()
        for user_id, created_at in rows:
            _append_time(activity, user_id, created_at)

    checkout_started: dict[str, list[datetime]] = {}
    checkout_paid: dict[str, list[datetime]] = {}
    subscription_rows = (
        await db.execute(
            select(Subscription.user_id, Subscription.created_at, Subscription.status)
            .where(
                Subscription.user_id.in_(subject_ids),
                Subscription.created_at >= outcome_start,
                Subscription.created_at < outcome_end,
            )
            .limit(MAX_OUTCOME_ROWS)
        )
    ).all()
    for user_id, created_at, status in subscription_rows:
        _append_time(checkout_started, user_id, created_at)
        if status in PAID_SUBSCRIPTION_STATUSES:
            _append_time(checkout_paid, user_id, created_at)

    payment_rows = (
        await db.execute(
            select(Payment.user_id, Payment.created_at, Payment.status)
            .where(
                Payment.user_id.in_(subject_ids),
                Payment.created_at >= outcome_start,
                Payment.created_at < outcome_end,
            )
            .limit(MAX_OUTCOME_ROWS)
        )
    ).all()
    for user_id, created_at, status in payment_rows:
        if status in SETTLED_PAYMENT_STATUSES:
            _append_time(checkout_paid, user_id, created_at)

    for bucket in (activity, compiled, failed_compile, checkout_started, checkout_paid):
        for values in bucket.values():
            values.sort()

    empty["activity"] = activity
    empty["compiled"] = compiled
    empty["failed_compile"] = failed_compile
    empty["checkout_started"] = checkout_started
    empty["checkout_paid"] = checkout_paid
    return empty


flag_exposure_service = FlagExposureService()
