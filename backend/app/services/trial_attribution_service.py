"""Trial-to-paid cohort conversion by consented acquisition source.

The cohort is anchored on ``device_trials.created_at``. While a trial is
anonymous, :func:`capture_trial_source` may attach the visitor's server-stored,
consent-gated first-touch campaign labels to that trial. When the visitor signs
in, :func:`claim_trial_attribution` links the same row to the account and, when
applicable, to the account's first paid subscription. No raw device
fingerprint, IP address, user-agent, email, name, token or document id is
persisted in ``trial_attributions`` or returned by the admin report.

Only aggregate rows are returned. A source/plan/month cohort with fewer than
five trials is omitted, and any 1-4 user cell inside a visible cohort is
suppressed. Delete-account cascades remove the linkage and source, so a deleted
account becomes an anonymous/unlinked trial rather than a retained identity.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable, Mapping
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logging import get_logger
from ..database import models
from .traffic_source_service import (
    ATTRIBUTION_LOOKBACK_DAYS,
    LANDING_ACTION,
    SIGNUP_ACTION,
    is_valid_visitor_id,
    validate_stored_attribution,
)

logger = get_logger(__name__)

MIN_COHORT_SIZE = 5
MAX_BREAKDOWN_ROWS = 100
MAX_TRIAL_ROWS = 100_000
CONVERSION_WINDOWS = (7, 30, 90)
PAID_SUBSCRIPTION_STATUSES = (
    "active",
    "cancel_scheduled",
    "past_due",
    "on_hold",
    "paused",
)
DIRECT_SOURCE_LABEL = "direct"
NO_PAID_PLAN_LABEL = "no paid plan"
UNKNOWN_PLAN_LABEL = "unknown plan"

TrialAttribution = models.TrialAttribution
DeviceTrial = models.DeviceTrial
UsageAnalytics = models.UsageAnalytics
User = models.User
Subscription = models.Subscription


def _pct(value: int, total: int) -> float:
    return round((value / total) * 100, 2) if total else 0.0


def _median(values: Iterable[float]) -> float | None:
    items = list(values)
    return round(float(statistics.median(items)), 2) if items else None


def _days_between(start: datetime, end: datetime | None) -> float | None:
    if end is None:
        return None
    return round(max(0.0, (end - start).total_seconds() / 86_400), 2)


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


async def _landing_metadata(
    db: AsyncSession,
    visitor_id: str,
    *,
    cutoff: datetime,
) -> Mapping[str, Any] | None:
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
    return metadata if isinstance(metadata, Mapping) else None


async def _signup_metadata(
    db: AsyncSession, user_id: str
) -> Mapping[str, Any] | None:
    metadata = (
        await db.execute(
            select(UsageAnalytics.event_metadata)
            .where(
                UsageAnalytics.action == SIGNUP_ACTION,
                UsageAnalytics.user_id == user_id,
            )
            .order_by(UsageAnalytics.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return metadata if isinstance(metadata, Mapping) else None


def _source_values(attribution: Mapping[str, str]) -> dict[str, str | None]:
    """Map validated first-touch metadata onto the stored allowlist columns."""

    return {
        "acquisition_source": attribution.get("utm_source") or DIRECT_SOURCE_LABEL,
        "acquisition_medium": attribution.get("utm_medium"),
        "acquisition_campaign": attribution.get("utm_campaign"),
        "acquisition_content": attribution.get("utm_content"),
        "acquisition_term": attribution.get("utm_term"),
        "referrer_host": attribution.get("referrer_host"),
        "landing_path": attribution.get("landing_path"),
    }


def _apply_source(row: TrialAttribution, attribution: Mapping[str, str]) -> None:
    for key, value in _source_values(attribution).items():
        setattr(row, key, value)


async def capture_trial_source(
    db: AsyncSession,
    *,
    trial: DeviceTrial,
    visitor_id: str | None,
) -> bool:
    """Attach consent-gated first-touch source to a newly-created trial.

    The visitor cookie is a server-issued opaque grouping key. Source values are
    read from the already-validated landing row, never from the caller. A trial
    without a consented landing row stays unattributed.
    """

    if not visitor_id or not is_valid_visitor_id(visitor_id):
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(days=ATTRIBUTION_LOOKBACK_DAYS)
    try:
        metadata = await _landing_metadata(db, visitor_id, cutoff=cutoff)
        if metadata is None:
            return False
        attribution = validate_stored_attribution(metadata)
        if attribution is None:
            return False
        now = datetime.now(timezone.utc)
        values = {
            "id": str(uuid4()),
            "trial_id": trial.id,
            "user_id": None,
            "subscription_id": None,
            "consent_granted": True,
            "trial_started_at": trial.created_at or now,
            "signup_at": None,
            "paid_at": None,
            "created_at": now,
            "updated_at": now,
            **_source_values(attribution),
        }
        async with db.begin_nested():
            await db.execute(
                pg_insert(TrialAttribution)
                .values(**values)
                .on_conflict_do_nothing(index_elements=["trial_id"])
            )
        return True
    except Exception as exc:  # analytics must never break trial admission
        logger.warning(
            "Trial source capture failed (%s)", type(exc).__name__
        )
        return False


async def _earliest_paid_subscription(
    db: AsyncSession,
    user_id: str,
    *,
    after: datetime | None,
) -> Subscription | None:
    stmt = select(Subscription).where(
        Subscription.user_id == user_id,
        Subscription.status.in_(PAID_SUBSCRIPTION_STATUSES),
    )
    if after is not None:
        stmt = stmt.where(Subscription.created_at >= after)
    return (
        await db.execute(
            stmt.order_by(Subscription.created_at.asc(), Subscription.id.asc()).limit(1)
        )
    ).scalar_one_or_none()


def _subscription_paid_at(subscription: Subscription) -> datetime:
    return (
        subscription.current_period_start
        or subscription.created_at
        or datetime.now(timezone.utc)
    )


async def claim_trial_attribution(
    db: AsyncSession,
    *,
    user_id: str,
    device_fingerprint: str | None,
    consent_granted: bool,
    visitor_id: str | None = None,
) -> dict[str, Any]:
    """Link the account's trial to this user and its first paid subscription.

    The caller must supply explicit consent. Without it, no attribution is
    written or linked. A trial is only linked once, and an account is only
    linked to one trial, so a cohort cannot double-count a device or account.
    """

    if not consent_granted:
        return {"recorded": False, "reason": "consent_required"}
    if not device_fingerprint:
        return {"recorded": False, "reason": "no_device"}

    user = await db.get(User, user_id)
    if user is None:
        return {"recorded": False, "reason": "no_user"}

    trial = (
        await db.execute(
            select(DeviceTrial)
            .where(DeviceTrial.device_fingerprint == device_fingerprint)
            .order_by(DeviceTrial.created_at.asc(), DeviceTrial.id.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if trial is None:
        return {"recorded": False, "reason": "no_trial"}

    existing_user_row = (
        await db.execute(
            select(TrialAttribution)
            .where(TrialAttribution.user_id == user_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    row = (
        await db.execute(
            select(TrialAttribution)
            .where(TrialAttribution.trial_id == trial.id)
            .with_for_update()
        )
    ).scalar_one_or_none()

    already_linked = existing_user_row is not None
    if existing_user_row is not None and (
        row is None or str(existing_user_row.id) != str(row.id)
    ):
        return {"recorded": False, "reason": "already_linked"}
    if row is not None and row.user_id and str(row.user_id) != str(user_id):
        return {"recorded": False, "reason": "trial_already_linked"}

    if row is None:
        row = TrialAttribution(
            trial_id=trial.id,
            consent_granted=True,
            trial_started_at=trial.created_at or datetime.now(timezone.utc),
        )
        db.add(row)

    if row.acquisition_source is None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=ATTRIBUTION_LOOKBACK_DAYS)
        metadata = await _signup_metadata(db, user_id)
        if metadata is None and visitor_id and is_valid_visitor_id(visitor_id):
            metadata = await _landing_metadata(db, visitor_id, cutoff=cutoff)
        attribution = (
            validate_stored_attribution(metadata) if metadata is not None else None
        )
        if attribution is not None:
            _apply_source(row, attribution)

    row.user_id = user_id
    row.signup_at = user.created_at or datetime.now(timezone.utc)
    row.consent_granted = True
    row.updated_at = datetime.now(timezone.utc)

    if row.subscription_id is None:
        subscription = await _earliest_paid_subscription(
            db, user_id, after=row.trial_started_at
        )
        if subscription is not None:
            row.subscription_id = subscription.id
            row.plan_id = subscription.plan_id
            row.paid_at = _subscription_paid_at(subscription)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return {"recorded": False, "reason": "already_linked"}

    if already_linked:
        return {
            "recorded": False,
            "reason": "already_linked",
            "source_recorded": row.acquisition_source is not None,
        }
    return {
        "recorded": True,
        "source_recorded": row.acquisition_source is not None,
    }


async def link_subscription_for_user(
    db: AsyncSession,
    *,
    user_id: str,
    subscription_id: str,
    plan_id: str | None,
    paid_at: datetime | None = None,
) -> bool:
    """Persist the paid conversion on an already-linked trial.

    Called after a successful billing payment. Failures are swallowed by the
    caller: attribution must never roll back or delay an entitlement change.
    """

    row = (
        await db.execute(
            select(TrialAttribution)
            .where(TrialAttribution.user_id == user_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None or row.subscription_id is not None:
        return False
    when = paid_at or datetime.now(timezone.utc)
    if row.trial_started_at is not None and when < row.trial_started_at:
        return False
    row.subscription_id = subscription_id
    row.plan_id = plan_id
    row.paid_at = when
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return True


def _row(label: str, records: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, bool]:
    """Build one suppressed cohort row. Returns (row, hidden)."""

    trials = len(records)
    if trials < MIN_COHORT_SIZE:
        return None, True

    signups = [record for record in records if record["signup_at"] is not None]
    paid = [record for record in records if record["paid_at"] is not None]
    suppressed_cells: list[str] = []

    show_signups = len(signups) == 0 or len(signups) >= MIN_COHORT_SIZE
    show_paid = len(paid) == 0 or len(paid) >= MIN_COHORT_SIZE
    if not show_signups:
        suppressed_cells.append("signups")
    if not show_paid:
        suppressed_cells.append("paid_users")

    # Once the paid cell itself is publishable (0 or >=5), its 7/30/90-day
    # subsets are aggregate facts about that visible cohort. When the paid cell
    # is suppressed, every window is suppressed with it.
    paid_windows: dict[int, int | None] = {}
    for window in CONVERSION_WINDOWS:
        count = sum(
            1
            for record in paid
            if (days := record["days_to_paid"]) is not None and days <= window
        )
        paid_windows[window] = count if show_paid else None

    row = {
        "label": label,
        "trial_starts": trials,
        "signups": len(signups) if show_signups else None,
        "paid_users": len(paid) if show_paid else None,
        "trial_to_signup_pct": _pct(len(signups), trials) if show_signups else None,
        "trial_to_paid_pct": _pct(len(paid), trials) if show_paid else None,
        "signup_to_paid_pct": (
            _pct(len(paid), len(signups))
            if show_paid and show_signups and signups
            else (0.0 if show_paid and show_signups else None)
        ),
        "median_days_to_signup": (
            _median(
                record["days_to_signup"]
                for record in signups
                if record["days_to_signup"] is not None
            )
            if show_signups
            else None
        ),
        "median_days_to_paid": (
            _median(
                record["days_to_paid"]
                for record in paid
                if record["days_to_paid"] is not None
            )
            if show_paid
            else None
        ),
        "paid_within_7d": paid_windows[7],
        "paid_within_30d": paid_windows[30],
        "paid_within_90d": paid_windows[90],
        "conversion_within_7d_pct": (
            _pct(paid_windows[7], trials) if paid_windows[7] is not None else None
        ),
        "conversion_within_30d_pct": (
            _pct(paid_windows[30], trials) if paid_windows[30] is not None else None
        ),
        "conversion_within_90d_pct": (
            _pct(paid_windows[90], trials) if paid_windows[90] is not None else None
        ),
        "suppressed_cells": sorted(set(suppressed_cells)),
    }
    return row, False


def _rows_for(
    groups: Mapping[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], int, int]:
    rows: list[dict[str, Any]] = []
    suppressed = 0
    ordered = sorted(
        groups.items(),
        key=lambda item: (-len(item[1]), item[0]),
    )
    for label, records in ordered:
        row, hidden = _row(label, records)
        if hidden:
            suppressed += 1
            continue
        rows.append(row)
    truncated = max(0, len(rows) - MAX_BREAKDOWN_ROWS)
    return rows[:MAX_BREAKDOWN_ROWS], suppressed, truncated


def _group(
    records: Iterable[dict[str, Any]],
    key_func,
) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        key = key_func(record)
        if key:
            groups[key].append(record)
    return groups


async def _count_scalar(db: AsyncSession, stmt) -> int:
    return int((await db.execute(stmt)).scalar() or 0)


async def snapshot(
    db: AsyncSession,
    *,
    days: int = 30,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    """Aggregate trial-start -> signup -> paid cohorts for admins."""

    start_at, end_at = resolve_period(
        days=days, start_date=start_date, end_date=end_date
    )
    total_trials = await _count_scalar(
        db,
        select(func.count(DeviceTrial.id)).where(
            DeviceTrial.created_at >= start_at,
            DeviceTrial.created_at < end_at,
        ),
    )

    rows = (
        await db.execute(
            select(
                TrialAttribution,
                DeviceTrial.created_at.label("trial_created_at"),
                User.created_at.label("user_created_at"),
                Subscription.plan_id.label("subscription_plan"),
                Subscription.status.label("subscription_status"),
            )
            .join(DeviceTrial, DeviceTrial.id == TrialAttribution.trial_id)
            .outerjoin(User, User.id == TrialAttribution.user_id)
            .outerjoin(Subscription, Subscription.id == TrialAttribution.subscription_id)
            .where(
                DeviceTrial.created_at >= start_at,
                DeviceTrial.created_at < end_at,
            )
            .order_by(DeviceTrial.created_at.asc(), TrialAttribution.id.asc())
            .limit(MAX_TRIAL_ROWS)
        )
    ).all()

    records: list[dict[str, Any]] = []
    linked_trials = 0
    source_trials = 0
    anonymous_source_trials = 0
    linked_signups = 0
    linked_paid = 0
    subscriptions_linked = 0
    deleted_user_attributions = 0

    for attribution, trial_created_at, user_created_at, sub_plan, _sub_status in rows:
        if not attribution.consent_granted:
            continue
        trial_started = trial_created_at or attribution.trial_started_at
        signup_at = attribution.signup_at if attribution.user_id else None
        paid_at = attribution.paid_at if attribution.user_id else None
        if attribution.user_id and user_created_at is None:
            # The FK cascades on account deletion; this is defensive only.
            deleted_user_attributions += 1
        if attribution.user_id:
            linked_trials += 1
            if signup_at is not None:
                linked_signups += 1
            if paid_at is not None:
                linked_paid += 1
        if attribution.subscription_id:
            subscriptions_linked += 1
        if attribution.acquisition_source:
            source_trials += 1
            if attribution.user_id is None:
                anonymous_source_trials += 1

        records.append(
            {
                "trial_started_at": trial_started,
                "signup_at": signup_at,
                "paid_at": paid_at,
                "days_to_signup": _days_between(trial_started, signup_at),
                "days_to_paid": _days_between(trial_started, paid_at),
                "source": attribution.acquisition_source,
                "plan": attribution.plan_id or sub_plan,
                "signup_month": (
                    signup_at.strftime("%Y-%m") if signup_at is not None else None
                ),
                "user_linked": attribution.user_id is not None,
            }
        )

    by_source_rows, source_suppressed, source_truncated = _rows_for(
        _group(records, lambda record: record["source"])
    )
    by_plan_rows, plan_suppressed, plan_truncated = _rows_for(
        _group(
            records,
            lambda record: (
                (record["plan"] or UNKNOWN_PLAN_LABEL)
                if record["paid_at"] is not None
                else (
                    NO_PAID_PLAN_LABEL
                    if record["user_linked"]
                    else None
                )
            ),
        )
    )
    by_month_rows, month_suppressed, month_truncated = _rows_for(
        _group(records, lambda record: record["signup_month"])
    )

    paid_records = [record for record in records if record["paid_at"] is not None]
    signup_records = [record for record in records if record["signup_at"] is not None]
    paid_days = [
        record["days_to_paid"]
        for record in paid_records
        if record["days_to_paid"] is not None
    ]
    signup_days = [
        record["days_to_signup"]
        for record in signup_records
        if record["days_to_signup"] is not None
    ]

    show_total_signups = len(signup_records) == 0 or len(signup_records) >= MIN_COHORT_SIZE
    show_total_paid = len(paid_records) == 0 or len(paid_records) >= MIN_COHORT_SIZE

    window_totals: dict[int, int | None] = {}
    for window in CONVERSION_WINDOWS:
        count = sum(1 for value in paid_days if value <= window)
        window_totals[window] = count if show_total_paid else None

    period_signups = await _count_scalar(
        db,
        select(func.count(User.id)).where(
            User.created_at >= start_at,
            User.created_at < end_at,
        ),
    )
    period_paid_subscriptions = await _count_scalar(
        db,
        select(func.count(Subscription.id)).where(
            Subscription.created_at >= start_at,
            Subscription.created_at < end_at,
            Subscription.status.in_(PAID_SUBSCRIPTION_STATUSES),
        ),
    )
    period_paid_users = await _count_scalar(
        db,
        select(func.count(func.distinct(Subscription.user_id))).where(
            Subscription.created_at >= start_at,
            Subscription.created_at < end_at,
            Subscription.status.in_(PAID_SUBSCRIPTION_STATUSES),
        ),
    )
    cohort_signups_in_period = sum(
        1
        for record in signup_records
        if start_at <= record["signup_at"] < end_at
    )
    cohort_paid_in_period = sum(
        1
        for record in paid_records
        if start_at <= record["paid_at"] < end_at
    )

    return {
        "period": {
            "start": start_at.isoformat(),
            "end": end_at.isoformat(),
            "days": round((end_at - start_at).total_seconds() / 86_400, 2),
        },
        "minimum_cohort_size": MIN_COHORT_SIZE,
        "conversion_windows_days": list(CONVERSION_WINDOWS),
        "totals": {
            "trial_starts": total_trials,
            "linked_trials": linked_trials,
            "unlinked_trials": max(0, total_trials - linked_trials),
            "anonymous_source_trials": anonymous_source_trials,
            "signups": len(signup_records) if show_total_signups else None,
            "paid_users": len(paid_records) if show_total_paid else None,
            "trial_to_signup_pct": (
                _pct(len(signup_records), total_trials) if show_total_signups else None
            ),
            "trial_to_paid_pct": (
                _pct(len(paid_records), total_trials) if show_total_paid else None
            ),
            "signup_to_paid_pct": (
                _pct(len(paid_records), len(signup_records))
                if show_total_paid and show_total_signups and signup_records
                else (
                    0.0
                    if show_total_paid and show_total_signups
                    else None
                )
            ),
            "median_days_to_signup": _median(signup_days) if show_total_signups else None,
            "median_days_to_paid": _median(paid_days) if show_total_paid else None,
            "paid_within_7d": window_totals[7],
            "paid_within_30d": window_totals[30],
            "paid_within_90d": window_totals[90],
            "conversion_within_7d_pct": (
                _pct(window_totals[7], total_trials)
                if window_totals[7] is not None
                else None
            ),
            "conversion_within_30d_pct": (
                _pct(window_totals[30], total_trials)
                if window_totals[30] is not None
                else None
            ),
            "conversion_within_90d_pct": (
                _pct(window_totals[90], total_trials)
                if window_totals[90] is not None
                else None
            ),
            "source_attributed_trials": source_trials,
            "linkage_coverage_pct": _pct(linked_trials, total_trials),
            "source_coverage_pct": _pct(source_trials, total_trials),
        },
        "reconciliation": {
            "period_trial_starts": total_trials,
            "linked_trials": linked_trials,
            "unlinked_trials": max(0, total_trials - linked_trials),
            "anonymous_trials": max(0, total_trials - linked_trials),
            "source_attributed_trials": source_trials,
            "unattributed_trials": max(0, total_trials - source_trials),
            "cohort_signups": len(signup_records),
            "cohort_paid_users": len(paid_records),
            "subscriptions_linked_to_cohort": subscriptions_linked,
            "period_signups": period_signups,
            "period_paid_subscriptions": period_paid_subscriptions,
            "period_paid_users": period_paid_users,
            "unattributed_signups": max(0, period_signups - cohort_signups_in_period),
            "unattributed_paid_users": max(
                0, period_paid_users - cohort_paid_in_period
            ),
            "deleted_user_attributions": deleted_user_attributions,
        },
        "by_source": by_source_rows,
        "by_plan": by_plan_rows,
        "by_signup_month": by_month_rows,
        "suppressed": {
            "source": source_suppressed,
            "plan": plan_suppressed,
            "signup_month": month_suppressed,
        },
        "truncated": {
            "source": source_truncated,
            "plan": plan_truncated,
            "signup_month": month_truncated,
        },
        "notes": [
            (
                "Trials are counted by device_trials.created_at in the selected period. "
                "Source is the consent-gated first-touch landing row; account, subscription "
                "and payment linkage is server-owned."
            ),
            (
                "Source cohorts include anonymous trials, so trial-to-signup and "
                "trial-to-paid are end-to-end rates. Plan and signup-month cohorts only "
                "include linked accounts."
            ),
            (
                f"Cohorts with fewer than {MIN_COHORT_SIZE} trials are hidden; 1-4 user "
                "cells inside a visible cohort are suppressed. No raw fingerprint, IP, "
                "email, name, token or account id is returned."
            ),
            (
                "Deleting an account cascades the attribution link; the anonymous trial "
                "remains in the trial count and is reported as unlinked."
            ),
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
