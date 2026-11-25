"""Feature adoption matrix: registry features by plan, role, and signup cohort.

Only aggregate counts leave this module. The query reads ``usage_analytics``
joined to ``users`` and the most relevant ``subscriptions`` row; the feature
registry supplies every matrix row. Entitlement tables (``plan_features`` /
``role_features``) are deliberately not part of the usage query — a grant is
access, not adoption.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import PLAN_FAMILY_ALIASES
from ..core.feature_registry import FEATURE_REGISTRY
from ..database import models

MIN_SEGMENT_SIZE = 5
MAX_RANGE_DAYS = 365
DIMENSIONS = ("plan", "role", "cohort")
SUBSCRIPTION_STATUSES = ("active", "trialing", "past_due", "cancel_scheduled")

# Historical frontend labels that pre-date the registry keys. Only explicit,
# allowlisted labels are mapped; arbitrary event metadata values stay out of the
# matrix (and out of the response).
FEATURE_EVENT_ALIASES = {
    "ai_optimization": "llm_optimize",
    "cover_letter": "cover_letters",
    "cover_letter_generation": "cover_letters",
    "optimize": "llm_optimize",
    "resume_optimization": "llm_optimize",
}

_REGISTRY_KEYS = frozenset(feature.key for feature in FEATURE_REGISTRY)
_CANONICAL_FEATURE_CASE: dict[str, str] = {key: key for key in _REGISTRY_KEYS}
for _alias, _target in FEATURE_EVENT_ALIASES.items():
    if _target in _REGISTRY_KEYS:
        _CANONICAL_FEATURE_CASE.setdefault(_alias, _target)

_PLAN_LABELS = {
    "free": "Free",
    "basic": "Basic",
    "pro": "Pro",
    "byok": "BYOK",
    "team": "Team",
}
_ROLE_LABELS = {
    "anonymous": "Anonymous",
    "user": "Users",
    "support": "Support",
    "admin": "Admins",
}
_ROLE_ORDER = {role: index for index, role in enumerate(("user", "support", "admin", "anonymous"))}
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _plan_bucket(value: str | None) -> str:
    """Map a concrete SKU to its family, preserving custom/test plan names."""
    normalized = (value or "free").strip().lower()
    if not normalized:
        return "free"
    return PLAN_FAMILY_ALIASES.get(normalized, normalized)


def _plan_label(key: str) -> str:
    return _PLAN_LABELS.get(key, key.replace("_", " ").title())


def _role_label(key: str) -> str:
    return _ROLE_LABELS.get(key, key.replace("_", " ").title())


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


def _resolve_range(
    *,
    days: int,
    start_date: date | str | None,
    end_date: date | str | None,
) -> tuple[date, date, datetime, datetime, datetime]:
    """Return inclusive day bounds plus the UTC half-open event range."""
    today = datetime.now(timezone.utc).date()

    def _as_date(value: date | str | None) -> date | None:
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
    span = (end_day - start_day).days + 1
    if span > MAX_RANGE_DAYS:
        raise ValueError(f"date range cannot exceed {MAX_RANGE_DAYS} days")

    start_at = datetime.combine(start_day, time.min, tzinfo=timezone.utc)
    end_at = datetime.combine(end_day + timedelta(days=1), time.min, tzinfo=timezone.utc)
    weekly_start = max(start_at, end_at - timedelta(days=7))
    return start_day, end_day, start_at, end_at, weekly_start


def _feature_matches(feature, query: str) -> bool:
    if not query:
        return True
    haystack = " ".join(
        str(value)
        for value in (
            feature.key,
            feature.label,
            feature.category,
            feature.description,
            feature.inventory_id,
            feature.product_inventory_id,
        )
        if value
    ).lower()
    return query.lower() in haystack


class AdminFeatureAdoptionService:
    async def feature_adoption(
        self,
        db: AsyncSession,
        *,
        days: int = 30,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        plan: str | None = None,
        role: str | None = None,
        cohort: str | None = None,
        feature: str | None = None,
    ) -> dict[str, Any]:
        """Return a feature x segment adoption matrix with denominators.

        Segment rows are emitted only at or above ``MIN_SEGMENT_SIZE`` users.
        Every registry feature appears in every visible segment, including
        features with zero recorded events, so gaps are explicit.
        """
        days = max(1, min(int(days), MAX_RANGE_DAYS))
        start_day, end_day, start_at, end_at, weekly_start = _resolve_range(
            days=days, start_date=start_date, end_date=end_date
        )
        plans = sorted({_plan_bucket(item) for item in _split_csv(plan)})
        roles = sorted({item.strip().lower() for item in _split_csv(role) if item.strip()})
        cohorts = sorted({item.strip() for item in _split_csv(cohort) if item.strip()})
        feature_query = (feature or "").strip()[:120]
        for month in cohorts:
            _month_bounds(month)
        if len(plans) > 25:
            raise ValueError("at most 25 plans can be selected")
        if len(roles) > 10:
            raise ValueError("at most 10 roles can be selected")
        if len(cohorts) > 36:
            raise ValueError("at most 36 cohorts can be selected")

        # One current subscription row per user. User.subscription_plan remains
        # the fallback for accounts that never had a local subscription row.
        latest_subscription = (
            select(models.Subscription.user_id, models.Subscription.plan_id)
            .where(models.Subscription.status.in_(SUBSCRIPTION_STATUSES))
            .distinct(models.Subscription.user_id)
            .order_by(
                models.Subscription.user_id,
                models.Subscription.current_period_end.desc().nulls_last(),
                models.Subscription.created_at.desc(),
            )
            .subquery("latest_subscription")
        )
        plan_expr = func.lower(
            func.coalesce(
                latest_subscription.c.plan_id,
                models.User.subscription_plan,
                "free",
            )
        )

        user_conditions: list[Any] = [models.User.created_at < end_at]
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
        if roles:
            user_conditions.append(func.lower(models.User.role).in_(roles))
        if cohorts:
            user_conditions.append(
                or_(
                    *[
                        (models.User.created_at >= bounds[0]) & (models.User.created_at < bounds[1])
                        for bounds in (_month_bounds(month) for month in cohorts)
                    ]
                )
            )

        user_rows = (
            await db.execute(
                select(
                    models.User.id,
                    models.User.role,
                    models.User.created_at,
                    plan_expr.label("plan"),
                )
                .select_from(models.User)
                .outerjoin(
                    latest_subscription,
                    latest_subscription.c.user_id == models.User.id,
                )
                .where(*user_conditions)
            )
        ).all()

        users: dict[str, dict[str, str]] = {}
        for row in user_rows:
            user_id = str(row.id)
            users[user_id] = {
                "plan": _plan_bucket(row.plan),
                "role": str(row.role or "user").strip().lower(),
                "cohort": _month_label(row.created_at) if row.created_at else "unknown",
            }

        segment_users: dict[str, dict[str, set[str]]] = {dimension: defaultdict(set) for dimension in DIMENSIONS}
        user_segments: dict[str, dict[str, str]] = {}
        for user_id, labels in users.items():
            user_segments[user_id] = labels
            for dimension in DIMENSIONS:
                segment_users[dimension][labels[dimension]].add(user_id)

        raw_feature = func.lower(
            func.coalesce(
                models.UsageAnalytics.event_metadata["feature"].as_string(),
                models.UsageAnalytics.action,
            )
        )
        canonical_feature = case(_CANONICAL_FEATURE_CASE, value=raw_feature, else_=None).label("feature_key")
        usage_conditions: list[Any] = [
            models.UsageAnalytics.created_at >= start_at,
            models.UsageAnalytics.created_at < end_at,
            models.UsageAnalytics.user_id.is_not(None),
            canonical_feature.is_not(None),
            *user_conditions,
        ]
        usage_rows = (
            await db.execute(
                select(
                    canonical_feature,
                    models.UsageAnalytics.user_id.label("user_id"),
                    func.count(models.UsageAnalytics.id).label("events"),
                    func.count(models.UsageAnalytics.id)
                    .filter(models.UsageAnalytics.created_at >= weekly_start)
                    .label("weekly_events"),
                    func.max(models.UsageAnalytics.created_at).label("last_used_at"),
                )
                .select_from(models.UsageAnalytics)
                .join(models.User, models.User.id == models.UsageAnalytics.user_id)
                .outerjoin(
                    latest_subscription,
                    latest_subscription.c.user_id == models.User.id,
                )
                .where(*usage_conditions)
                .group_by(canonical_feature, models.UsageAnalytics.user_id)
            )
        ).all()

        feature_stats: dict[str, dict[str, dict[str, dict[str, Any]]]] = {
            dimension: defaultdict(dict) for dimension in DIMENSIONS
        }
        matrix_events = 0
        for row in usage_rows:
            user_id = str(row.user_id)
            labels = user_segments.get(user_id)
            if labels is None:
                continue
            feature_key = str(row.feature_key)
            events = int(row.events or 0)
            weekly_events = int(row.weekly_events or 0)
            matrix_events += events
            for dimension in DIMENSIONS:
                bucket = feature_stats[dimension][labels[dimension]]
                stat = bucket.setdefault(
                    feature_key,
                    {"users": set(), "weekly_users": set(), "events": 0, "last_used_at": None},
                )
                stat["users"].add(user_id)
                if weekly_events:
                    stat["weekly_users"].add(user_id)
                stat["events"] += events
                last_used_at = row.last_used_at
                current_last = stat["last_used_at"]
                if last_used_at is not None and (current_last is None or last_used_at > current_last):
                    stat["last_used_at"] = last_used_at

        visible_features = [item for item in FEATURE_REGISTRY if _feature_matches(item, feature_query)]
        segments: list[dict[str, Any]] = []
        suppressed_segments = {dimension: 0 for dimension in DIMENSIONS}
        for dimension in DIMENSIONS:
            dimension_segments: list[dict[str, Any]] = []
            for key, user_ids in segment_users[dimension].items():
                denominator = len(user_ids)
                if denominator < MIN_SEGMENT_SIZE:
                    suppressed_segments[dimension] += 1
                    continue
                segment_stats = feature_stats[dimension].get(key, {})
                feature_rows: list[dict[str, Any]] = []
                for definition in visible_features:
                    stat = segment_stats.get(definition.key)
                    used = len(stat["users"]) if stat else 0
                    weekly_active = len(stat["weekly_users"]) if stat else 0
                    events = int(stat["events"]) if stat else 0
                    feature_rows.append(
                        {
                            "feature": definition.key,
                            "key": definition.key,
                            "label": definition.label,
                            "category": definition.category,
                            "description": definition.description,
                            "used_at_least_once": used,
                            "weekly_active": weekly_active,
                            "penetration": round(used / denominator * 100, 2),
                            "weekly_active_penetration": round(weekly_active / denominator * 100, 2),
                            "events": events,
                            "last_used_at": (
                                stat["last_used_at"].isoformat() if stat and stat["last_used_at"] else None
                            ),
                        }
                    )
                dimension_segments.append(
                    {
                        "dimension": dimension,
                        "key": key,
                        "label": (
                            _plan_label(key)
                            if dimension == "plan"
                            else _role_label(key)
                            if dimension == "role"
                            else key
                        ),
                        "denominator": denominator,
                        "suppressed": False,
                        "features": feature_rows,
                    }
                )
            if dimension == "plan":
                dimension_segments.sort(key=lambda item: (-item["denominator"], item["key"]))
            elif dimension == "role":
                dimension_segments.sort(
                    key=lambda item: (
                        _ROLE_ORDER.get(item["key"], len(_ROLE_ORDER)),
                        item["key"],
                    )
                )
            else:
                dimension_segments.sort(key=lambda item: item["key"])
            segments.extend(dimension_segments)

        usage_events = int(
            (
                await db.execute(
                    select(func.count(models.UsageAnalytics.id))
                    .select_from(models.UsageAnalytics)
                    .join(models.User, models.User.id == models.UsageAnalytics.user_id)
                    .outerjoin(
                        latest_subscription,
                        latest_subscription.c.user_id == models.User.id,
                    )
                    .where(
                        models.UsageAnalytics.created_at >= start_at,
                        models.UsageAnalytics.created_at < end_at,
                        *user_conditions,
                    )
                )
            ).scalar()
            or 0
        )
        candidate_segments = sum(len(values) for values in segment_users.values())
        suppressed_total = sum(suppressed_segments.values())
        selected_range_days = (end_day - start_day).days + 1
        now = datetime.now(timezone.utc)

        return {
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
                "role": roles or None,
                "cohort": cohorts or None,
                "feature": feature_query or None,
                "timezone": "UTC",
            },
            "minimum_segment_size": MIN_SEGMENT_SIZE,
            "feature_count": len(FEATURE_REGISTRY),
            "visible_feature_count": len(visible_features),
            "suppressed": bool(candidate_segments) and suppressed_total == candidate_segments,
            "suppressed_segments": suppressed_segments,
            "segments": segments,
            "reconciliation": {
                "source": "usage_analytics",
                "audience_users": len(users),
                "usage_events": usage_events,
                "matrix_events": matrix_events,
                "unmatched_events": max(0, usage_events - matrix_events),
                "features_with_usage": len({row.feature_key for row in usage_rows}),
                "matched_rate": round(matrix_events / usage_events * 100, 2) if usage_events else 0.0,
            },
            "definitions": {
                "used_at_least_once": (
                    "Distinct users with at least one registry feature event in the selected date range."
                ),
                "weekly_active": (
                    "Distinct users with at least one registry feature event in the "
                    "final 7 days of the selected date range."
                ),
                "penetration": "used_at_least_once divided by the segment denominator.",
                "denominator": (
                    "Users in the segment who existed by the end of the date range. "
                    f"Segments below {MIN_SEGMENT_SIZE} users are not emitted."
                ),
                "usage_source": (
                    "usage_analytics feature events only. Entitlement grants from "
                    "plan_features/role_features are never counted as usage."
                ),
            },
            "generated_at": now.isoformat(),
        }


admin_feature_adoption_service = AdminFeatureAdoptionService()
