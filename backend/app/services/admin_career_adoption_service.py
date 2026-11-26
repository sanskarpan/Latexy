"""Admin adoption report for cover letters, interview prep and career paths.

The report answers four questions for each feature and every visible plan or
signup cohort: how many distinct users adopted it, how many runs they produced,
how many came back for a second run, and how many adopted it after an
optimization (cross-sell).

Only aggregate counts leave this module.  Inputs are the existing tables
(``cover_letters``, ``interview_prep``, ``career_analyses``) plus allowlisted
``usage_analytics`` events.  Event metadata, résumé/LaTeX text, job
descriptions, generated questions and analysis prose are never selected or
returned.  Plans and cohorts below five distinct users are not emitted; a
filtered audience below five users has every metric and reconciliation number
withheld.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import PLAN_FAMILY_ALIASES
from ..database import models
from .career_feature_events import (
    CANONICAL_EVENTS,
    FEATURE_CAREER_PATHS,
    FEATURE_COVER_LETTERS,
    FEATURE_EVENT_ACTIONS,
    FEATURE_INTERVIEW_PREP,
    FEATURE_METADATA_ALIASES,
    OPTIMIZATION_ACTIONS,
    OPTIMIZATION_METADATA_ALIASES,
)

UsageAnalytics = models.UsageAnalytics
User = models.User
Optimization = models.Optimization

MIN_SEGMENT_SIZE = 5
MAX_RANGE_DAYS = 365
MAX_PLAN_FILTERS = 25
MAX_COHORT_FILTERS = 36
OPTIMIZATION_LOOKBACK_DAYS = 365
SUBSCRIPTION_STATUSES = ("active", "trialing", "past_due", "cancel_scheduled")
DIMENSIONS = ("plan", "cohort")
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

FEATURE_LABELS: dict[str, str] = {
    FEATURE_COVER_LETTERS: "Cover letters",
    FEATURE_INTERVIEW_PREP: "Interview prep",
    FEATURE_CAREER_PATHS: "Career path analysis",
}
FEATURE_TABLES: dict[str, Any] = {
    FEATURE_COVER_LETTERS: models.CoverLetter,
    FEATURE_INTERVIEW_PREP: models.InterviewPrep,
    FEATURE_CAREER_PATHS: models.CareerAnalysis,
}
FEATURE_DEFINITIONS: tuple[str, ...] = (
    FEATURE_COVER_LETTERS,
    FEATURE_INTERVIEW_PREP,
    FEATURE_CAREER_PATHS,
)

_PLAN_LABELS = {
    "free": "Free",
    "basic": "Basic",
    "pro": "Pro",
    "byok": "BYOK",
    "team": "Team",
}


def _plan_bucket(value: str | None) -> str:
    normalized = (value or "free").strip().lower()
    if not normalized:
        return "free"
    return PLAN_FAMILY_ALIASES.get(normalized, normalized)


def _plan_label(key: str) -> str:
    return _PLAN_LABELS.get(key, key.replace("_", " ").title())


def _month_label(value: datetime | date) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def _month_bounds(month: str) -> tuple[datetime, datetime]:
    if not isinstance(month, str) or _MONTH_RE.fullmatch(month) is None:
        raise ValueError("cohort must use the YYYY-MM format")
    year = int(month[:4])
    month_number = int(month[5:])
    start = datetime(year, month_number, 1, tzinfo=timezone.utc)
    if month_number == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month_number + 1, 1, tzinfo=timezone.utc)
    return start, end


def _split_csv(value: str | None) -> list[str]:
    if value is None:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _as_date(value: date | str | None) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError("date range must use YYYY-MM-DD") from exc


def _resolve_range(
    *,
    days: int,
    start_date: date | str | None,
    end_date: date | str | None,
) -> tuple[date, date, datetime, datetime]:
    today = datetime.now(timezone.utc).date()
    start_day = _as_date(start_date)
    end_day = _as_date(end_date)
    if start_day is None and end_day is None:
        end_day = today
        start_day = end_day - timedelta(days=max(1, int(days)) - 1)
    elif start_day is None:
        end_day = end_day or today
        start_day = end_day - timedelta(days=max(1, int(days)) - 1)
    elif end_day is None:
        end_day = today

    assert start_day is not None and end_day is not None
    if start_day > end_day:
        raise ValueError("start_date must be on or before end_date")
    if (end_day - start_day).days + 1 > MAX_RANGE_DAYS:
        raise ValueError(f"date range cannot exceed {MAX_RANGE_DAYS} days")

    start_at = datetime.combine(start_day, time.min, tzinfo=timezone.utc)
    end_at = datetime.combine(end_day + timedelta(days=1), time.min, tzinfo=timezone.utc)
    return start_day, end_day, start_at, end_at


def _pct(part: int, whole: int) -> float:
    return round(part / whole * 100, 2) if whole else 0.0


def _round(value: float) -> float:
    return round(float(value), 2)


def _feature_case():
    """Map allowlisted actions/metadata onto the three registry feature keys."""
    action = func.lower(func.coalesce(UsageAnalytics.action, ""))
    metadata_feature = func.lower(
        func.coalesce(UsageAnalytics.event_metadata["feature"].as_string(), "")
    )
    branches = []
    for feature in FEATURE_DEFINITIONS:
        branches.append(
            (
                or_(
                    action.in_(sorted(FEATURE_EVENT_ACTIONS[feature])),
                    and_(
                        action == "feature_usage",
                        metadata_feature.in_(sorted(FEATURE_METADATA_ALIASES[feature])),
                    ),
                ),
                feature,
            )
        )
    return case(*branches, else_=None)


def _canonical_event_case():
    """Mark rows whose action is the canonical server event for its feature."""
    action = func.lower(func.coalesce(UsageAnalytics.action, ""))
    return case(
        *[
            (action == CANONICAL_EVENTS[feature], 1)
            for feature in FEATURE_DEFINITIONS
        ],
        else_=0,
    )


def _optimization_match():
    action = func.lower(func.coalesce(UsageAnalytics.action, ""))
    metadata_feature = func.lower(
        func.coalesce(UsageAnalytics.event_metadata["feature"].as_string(), "")
    )
    return or_(
        action.in_(sorted(OPTIMIZATION_ACTIONS)),
        and_(
            action == "feature_usage",
            metadata_feature.in_(sorted(OPTIMIZATION_METADATA_ALIASES)),
        ),
    )


@dataclass
class _FeatureStat:
    runs: int = 0
    first_at: Optional[datetime] = None
    last_at: Optional[datetime] = None


@dataclass
class _FeatureUsers:
    stats: dict[str, _FeatureStat] = field(default_factory=dict)

    def add(
        self,
        user_id: str,
        runs: int,
        first_at: datetime | None,
        last_at: datetime | None,
    ) -> None:
        self.stats[user_id] = _FeatureStat(runs=runs, first_at=first_at, last_at=last_at)


def _metrics(
    stats: dict[str, _FeatureStat],
    user_ids: Iterable[str],
    optimization_first: dict[str, datetime],
    *,
    denominator: int | None = None,
) -> dict[str, Any]:
    selected = [user_id for user_id in user_ids if user_id in stats]
    runs = sum(stats[user_id].runs for user_id in selected)
    users = len(selected)
    repeat_users = sum(1 for user_id in selected if stats[user_id].runs >= 2)
    after_optimization_users = 0
    for user_id in selected:
        first_at = stats[user_id].first_at
        optimized_at = optimization_first.get(user_id)
        if first_at is not None and optimized_at is not None and first_at >= optimized_at:
            after_optimization_users += 1
    payload: dict[str, Any] = {
        "users": users,
        "runs": runs,
        "runs_per_user": _round(runs / users) if users else 0.0,
        "repeat_users": repeat_users,
        "repeat_rate": _pct(repeat_users, users),
        "after_optimization_users": after_optimization_users,
        "after_optimization_rate": _pct(after_optimization_users, users),
    }
    if denominator is not None:
        payload["denominator"] = denominator
        payload["penetration"] = _pct(users, denominator)
    return payload


class AdminCareerAdoptionService:
    async def adoption_report(
        self,
        db: AsyncSession,
        *,
        days: int = 30,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        plan: str | None = None,
        cohort: str | None = None,
    ) -> dict[str, Any]:
        days = max(1, min(int(days), MAX_RANGE_DAYS))
        start_day, end_day, start_at, end_at = _resolve_range(
            days=days, start_date=start_date, end_date=end_date
        )
        plans = sorted({_plan_bucket(item) for item in _split_csv(plan)})
        cohorts = sorted({item.strip() for item in _split_csv(cohort) if item.strip()})
        for month in cohorts:
            _month_bounds(month)
        if len(plans) > MAX_PLAN_FILTERS:
            raise ValueError(f"at most {MAX_PLAN_FILTERS} plans can be selected")
        if len(cohorts) > MAX_COHORT_FILTERS:
            raise ValueError(f"at most {MAX_COHORT_FILTERS} cohorts can be selected")

        latest_subscription = (
            select(models.Subscription.user_id, models.Subscription.plan_id)
            .where(models.Subscription.status.in_(SUBSCRIPTION_STATUSES))
            .distinct(models.Subscription.user_id)
            .order_by(
                models.Subscription.user_id,
                models.Subscription.current_period_end.desc().nulls_last(),
                models.Subscription.created_at.desc(),
            )
            .subquery("career_adoption_subscription")
        )
        plan_expr = func.lower(
            func.coalesce(
                latest_subscription.c.plan_id,
                User.subscription_plan,
                "free",
            )
        )

        user_conditions: list[Any] = [User.created_at < end_at]
        if plans:
            requested_plan_values: set[str] = set()
            for selected in plans:
                if selected in PLAN_FAMILY_ALIASES.values():
                    requested_plan_values.update(
                        alias for alias, family in PLAN_FAMILY_ALIASES.items() if family == selected
                    )
                    requested_plan_values.add(selected)
                else:
                    requested_plan_values.add(selected)
            user_conditions.append(plan_expr.in_(sorted(requested_plan_values)))
        if cohorts:
            user_conditions.append(
                or_(
                    *[
                        (User.created_at >= bounds[0]) & (User.created_at < bounds[1])
                        for bounds in (_month_bounds(month) for month in cohorts)
                    ]
                )
            )

        user_rows = (
            await db.execute(
                select(
                    User.id,
                    User.created_at,
                    plan_expr.label("plan"),
                )
                .select_from(User)
                .outerjoin(
                    latest_subscription,
                    latest_subscription.c.user_id == User.id,
                )
                .where(*user_conditions)
            )
        ).all()

        users: dict[str, dict[str, str]] = {}
        segment_users: dict[str, dict[str, set[str]]] = {
            dimension: defaultdict(set) for dimension in DIMENSIONS
        }
        for row in user_rows:
            user_id = str(row.id)
            labels = {
                "plan": _plan_bucket(row.plan),
                "cohort": _month_label(row.created_at) if row.created_at else "unknown",
            }
            users[user_id] = labels
            for dimension in DIMENSIONS:
                segment_users[dimension][labels[dimension]].add(user_id)

        feature_case = _feature_case()
        canonical_case = _canonical_event_case()
        usage_conditions: list[Any] = [
            UsageAnalytics.created_at >= start_at,
            UsageAnalytics.created_at < end_at,
            UsageAnalytics.user_id.is_not(None),
            feature_case.is_not(None),
            *user_conditions,
        ]
        event_rows = (
            await db.execute(
                select(
                    feature_case.label("feature_key"),
                    UsageAnalytics.user_id.label("user_id"),
                    func.count(UsageAnalytics.id).label("runs"),
                    func.sum(canonical_case).label("canonical_runs"),
                    func.min(UsageAnalytics.created_at).label("first_at"),
                    func.max(UsageAnalytics.created_at).label("last_at"),
                )
                .select_from(UsageAnalytics)
                .join(User, User.id == UsageAnalytics.user_id)
                .outerjoin(
                    latest_subscription,
                    latest_subscription.c.user_id == User.id,
                )
                .where(*usage_conditions)
                .group_by(feature_case, UsageAnalytics.user_id)
            )
        ).all()

        feature_users: dict[str, _FeatureUsers] = {
            feature: _FeatureUsers() for feature in FEATURE_DEFINITIONS
        }
        for row in event_rows:
            feature = str(row.feature_key)
            if feature not in feature_users:
                continue
            all_runs = int(row.runs or 0)
            canonical_runs = int(row.canonical_runs or 0)
            # A legacy client feature_usage event and the new server event can
            # describe the same run. Prefer the larger label count instead of
            # summing mirrored events; distinct runs of one label still count.
            alias_runs = max(0, all_runs - canonical_runs)
            runs = max(canonical_runs, alias_runs) if canonical_runs and alias_runs else all_runs
            feature_users[feature].add(
                str(row.user_id),
                runs,
                row.first_at,
                row.last_at,
            )

        optimization_conditions: list[Any] = [
            UsageAnalytics.created_at >= start_at - timedelta(days=OPTIMIZATION_LOOKBACK_DAYS),
            UsageAnalytics.created_at < end_at,
            UsageAnalytics.user_id.is_not(None),
            _optimization_match(),
            *user_conditions,
        ]
        optimization_event_rows = (
            await db.execute(
                select(
                    UsageAnalytics.user_id.label("user_id"),
                    func.min(UsageAnalytics.created_at).label("first_at"),
                )
                .select_from(UsageAnalytics)
                .join(User, User.id == UsageAnalytics.user_id)
                .outerjoin(
                    latest_subscription,
                    latest_subscription.c.user_id == User.id,
                )
                .where(*optimization_conditions)
                .group_by(UsageAnalytics.user_id)
            )
        ).all()
        optimization_first: dict[str, datetime] = {
            str(row.user_id): row.first_at
            for row in optimization_event_rows
            if row.first_at is not None
        }

        optimization_table_rows = (
            await db.execute(
                select(
                    Optimization.user_id.label("user_id"),
                    func.min(Optimization.created_at).label("first_at"),
                )
                .select_from(Optimization)
                .join(User, User.id == Optimization.user_id)
                .outerjoin(
                    latest_subscription,
                    latest_subscription.c.user_id == User.id,
                )
                .where(
                    Optimization.created_at >= start_at - timedelta(days=OPTIMIZATION_LOOKBACK_DAYS),
                    Optimization.created_at < end_at,
                    Optimization.is_auto_save.is_(False),
                    Optimization.is_checkpoint.is_(False),
                    *user_conditions,
                )
                .group_by(Optimization.user_id)
            )
        ).all()
        for row in optimization_table_rows:
            if row.first_at is None:
                continue
            user_id = str(row.user_id)
            current = optimization_first.get(user_id)
            if current is None or row.first_at < current:
                optimization_first[user_id] = row.first_at

        table_counts: dict[str, dict[str, int]] = {}
        table_users: dict[str, set[str]] = {}
        unattributed_table_rows: dict[str, int] = {}
        for feature, model in FEATURE_TABLES.items():
            counts = {
                str(row.user_id): int(row.rows or 0)
                for row in (
                    await db.execute(
                        select(
                            model.user_id.label("user_id"),
                            func.count(model.id).label("rows"),
                        )
                        .select_from(model)
                        .join(User, User.id == model.user_id)
                        .outerjoin(
                            latest_subscription,
                            latest_subscription.c.user_id == User.id,
                        )
                        .where(
                            model.created_at >= start_at,
                            model.created_at < end_at,
                            *user_conditions,
                        )
                        .group_by(model.user_id)
                    )
                ).all()
            }
            table_counts[feature] = counts
            table_users[feature] = set(counts)
            unattributed_table_rows[feature] = int(
                (
                    await db.execute(
                        select(func.count(model.id)).where(
                            model.created_at >= start_at,
                            model.created_at < end_at,
                            model.user_id.is_(None),
                        )
                    )
                ).scalar()
                or 0
            )

        unattributed_events = int(
            (
                await db.execute(
                    select(func.count(UsageAnalytics.id)).where(
                        UsageAnalytics.created_at >= start_at,
                        UsageAnalytics.created_at < end_at,
                        UsageAnalytics.user_id.is_(None),
                        feature_case.is_not(None),
                    )
                )
            ).scalar()
            or 0
        )

        now = datetime.now(timezone.utc)
        selected_range_days = (end_day - start_day).days + 1
        candidate_segments = sum(len(values) for values in segment_users.values())
        suppressed_segments = {dimension: 0 for dimension in DIMENSIONS}

        response: dict[str, Any] = {
            "days": selected_range_days,
            "start_date": start_day.isoformat(),
            "end_date": end_day.isoformat(),
            "timezone": "UTC",
            "date_range": {
                "start": start_at.isoformat(),
                "end": end_at.isoformat(),
                "days": selected_range_days,
                "timezone": "UTC",
            },
            "filters": {
                "days": selected_range_days,
                "start_date": start_day.isoformat(),
                "end_date": end_day.isoformat(),
                "plan": plans or None,
                "cohort": cohorts or None,
                "timezone": "UTC",
            },
            "minimum_segment_size": MIN_SEGMENT_SIZE,
            "optimization_lookback_days": OPTIMIZATION_LOOKBACK_DAYS,
            "audience_users": len(users),
            "suppressed": False,
            "suppressed_segments": suppressed_segments,
            "features": [],
            "reconciliation": {},
            "definitions": self._definitions(),
            "privacy": {
                "aggregate_only": True,
                "per_user_rows": False,
                "content_fields_read": [],
                "content_fields_excluded": [
                    "generated cover-letter body",
                    "generated interview set",
                    "generated career analysis",
                    "source documents",
                    "job postings",
                ],
            },
            "generated_at": now.isoformat(),
        }

        if len(users) < MIN_SEGMENT_SIZE:
            # Withhold all feature and reconciliation counts for a filtered
            # audience below the privacy floor.  An empty audience is not a
            # small group and can safely report zeroes.
            if users:
                response["suppressed"] = True
                response["suppressed_segments"] = {
                    dimension: len(values) for dimension, values in segment_users.items()
                }
                response["features"] = [
                    {
                        "key": feature,
                        "label": FEATURE_LABELS[feature],
                        "event": CANONICAL_EVENTS[feature],
                        "adoption": None,
                        "segments": [],
                    }
                    for feature in FEATURE_DEFINITIONS
                ]
                response["reconciliation"] = {
                    "source": "usage_analytics + cover_letters/interview_prep/career_analyses",
                    "suppressed": True,
                    "features": {},
                }
                return response

            response["features"] = [
                {
                    "key": feature,
                    "label": FEATURE_LABELS[feature],
                    "event": CANONICAL_EVENTS[feature],
                    "adoption": _metrics({}, [], {}),
                    "segments": [],
                }
                for feature in FEATURE_DEFINITIONS
            ]
            response["reconciliation"] = {
                "source": "usage_analytics + cover_letters/interview_prep/career_analyses",
                "suppressed": False,
                "audience_users": 0,
                "features": {
                    feature: {
                        "event_users": 0,
                        "table_users": 0,
                        "events": 0,
                        "table_rows": 0,
                        "matched": 0,
                        "unmatched_events": 0,
                        "unmatched_rows": 0,
                    }
                    for feature in FEATURE_DEFINITIONS
                },
                "unattributed_events": unattributed_events,
                "unattributed_table_rows": unattributed_table_rows,
                "totals": {
                    "events": 0,
                    "table_rows": 0,
                    "matched": 0,
                    "unmatched_events": 0,
                    "unmatched_rows": 0,
                    "matched_rate": 0.0,
                },
            }
            return response

        feature_payloads: list[dict[str, Any]] = []
        for feature in FEATURE_DEFINITIONS:
            stats = feature_users[feature].stats
            feature_segments: list[dict[str, Any]] = []
            for dimension in DIMENSIONS:
                for key, user_ids in segment_users[dimension].items():
                    denominator = len(user_ids)
                    if denominator < MIN_SEGMENT_SIZE:
                        suppressed_segments[dimension] += 1
                        continue
                    metrics = _metrics(
                        stats,
                        user_ids,
                        optimization_first,
                        denominator=denominator,
                    )
                    feature_segments.append(
                        {
                            "dimension": dimension,
                            "key": key,
                            "label": _plan_label(key) if dimension == "plan" else key,
                            **metrics,
                        }
                    )
            feature_segments.sort(
                key=lambda item: (
                    DIMENSIONS.index(item["dimension"]),
                    -item["denominator"] if item["dimension"] == "plan" else 0,
                    item["key"],
                )
            )
            feature_payloads.append(
                {
                    "key": feature,
                    "label": FEATURE_LABELS[feature],
                    "event": CANONICAL_EVENTS[feature],
                    "adoption": _metrics(
                        stats,
                        users.keys(),
                        optimization_first,
                        denominator=len(users),
                    ),
                    "segments": feature_segments,
                }
            )

        reconciliation_features: dict[str, dict[str, Any]] = {}
        total_events = 0
        total_rows = 0
        total_matched = 0
        for feature in FEATURE_DEFINITIONS:
            events = sum(stat.runs for stat in feature_users[feature].stats.values())
            rows = sum(table_counts[feature].values())
            matched = min(events, rows)
            total_events += events
            total_rows += rows
            total_matched += matched
            reconciliation_features[feature] = {
                "event_users": len(feature_users[feature].stats),
                "table_users": len(table_users[feature]),
                "events": events,
                "table_rows": rows,
                "matched": matched,
                "unmatched_events": max(0, events - rows),
                "unmatched_rows": max(0, rows - events),
            }

        response["features"] = feature_payloads
        response["suppressed"] = bool(candidate_segments) and sum(suppressed_segments.values()) == candidate_segments
        response["reconciliation"] = {
            "source": "usage_analytics + cover_letters/interview_prep/career_analyses",
            "suppressed": False,
            "audience_users": len(users),
            "optimization_users": len(optimization_first),
            "features": reconciliation_features,
            "unattributed_events": unattributed_events,
            "unattributed_table_rows": unattributed_table_rows,
            "totals": {
                "events": total_events,
                "table_rows": total_rows,
                "matched": total_matched,
                "unmatched_events": max(0, total_events - total_rows),
                "unmatched_rows": max(0, total_rows - total_events),
                "matched_rate": _pct(total_matched, max(total_events, total_rows)),
            },
        }
        return response

    @staticmethod
    def _definitions() -> dict[str, str]:
        return {
            "users": (
                "Distinct users with at least one first-party generation event for the "
                "feature in the selected range."
            ),
            "runs": (
                "Allowlisted generation/completion event rows in the selected range. "
                "Reconciled one-to-one with the feature's persisted table."
            ),
            "repeat_users": "Distinct users with at least two generation events in the range.",
            "repeat_rate": "repeat_users divided by feature users.",
            "after_optimization_users": (
                "Feature users whose first generation in the range happened at or after "
                f"their earliest optimization in the previous {OPTIMIZATION_LOOKBACK_DAYS} days."
            ),
            "cross_sell_rate": "after_optimization_users divided by feature users.",
            "denominator": (
                "Users in the plan or signup cohort who existed by the end of the range. "
                f"Segments below {MIN_SEGMENT_SIZE} users are not emitted."
            ),
            "reconciliation": (
                "Event runs compared with persisted cover_letters/interview_prep/"
                "career_analyses rows for the same audience and window."
            ),
            "suppression": (
                f"Plan and cohort segments below {MIN_SEGMENT_SIZE} distinct users are "
                "withheld; a filtered audience below that floor returns no metrics."
            ),
        }


admin_career_adoption_service = AdminCareerAdoptionService()
