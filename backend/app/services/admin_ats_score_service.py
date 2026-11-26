"""Admin-only ATS score distribution and before/after improvement.

The report reads only numeric score columns plus bounded classification keys
from ``optimizations`` and the owner's subscription plan. Resume text, job
descriptions, prompts, optimization changes and identities are never selected
or returned.

A row is eligible for the report only when it has a post-optimization score.
Rows with a post-score but no comparable baseline are excluded from every
distribution/delta calculation and counted separately as ``missing_baseline``.
Auto-save checkpoints are not optimization runs and are not counted as missing
baselines.

Breakdown rows (industry, profile, plan) are hidden when they contain fewer
than five distinct users. If the whole filtered selection has fewer than five
distinct users, all metrics and distributions are suppressed.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import PLAN_FAMILY_ALIASES
from ..database import models
from .ats_score_dimensions import UNKNOWN, normalize_industry, normalize_profile, normalize_score

Optimization = models.Optimization
User = models.User

MIN_GROUP_USERS = 5
MAX_RANGE_DAYS = 365
MAX_FILTER_VALUES = 25

# Lower bound inclusive, upper bound inclusive only for the final bucket.
# ``upper`` is exclusive for every bucket except the final 90-100 bucket,
# which includes a score of exactly 100.
BUCKETS: tuple[tuple[float, float, str], ...] = (
    (0.0, 10.0, "0-9"),
    (10.0, 20.0, "10-19"),
    (20.0, 30.0, "20-29"),
    (30.0, 40.0, "30-39"),
    (40.0, 50.0, "40-49"),
    (50.0, 60.0, "50-59"),
    (60.0, 70.0, "60-69"),
    (70.0, 80.0, "70-79"),
    (80.0, 90.0, "80-89"),
    (90.0, 100.0, "90-100"),
)

def normalize_plan(value: Any) -> str:
    normalized = str(value or "free").strip().lower() or "free"
    if normalized in PLAN_FAMILY_ALIASES:
        return PLAN_FAMILY_ALIASES[normalized]
    # Preserve an unknown-but-bounded plan label for operator visibility.
    return normalized[:50]


def bucket_for_score(score: float) -> Optional[str]:
    """Return the 10-point bucket label for a valid score."""
    normalized = normalize_score(score)
    if normalized is None:
        return None
    if normalized >= 90:
        return BUCKETS[-1][2]
    return BUCKETS[int(normalized // 10)][2]


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


def _split_csv(value: str | None) -> list[str]:
    if value is None:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _filtered_industries(value: str | None) -> list[str]:
    selected: set[str] = set()
    for item in _split_csv(value):
        normalized = normalize_industry(item)
        if normalized is None:
            raw = item.strip().lower()[:100]
            normalized = UNKNOWN if raw == UNKNOWN else raw
        selected.add(normalized)
    if len(selected) > MAX_FILTER_VALUES:
        raise ValueError(f"at most {MAX_FILTER_VALUES} industries can be selected")
    return sorted(selected)


def _filtered_profiles(value: str | None) -> list[str]:
    selected: set[str] = set()
    for item in _split_csv(value):
        normalized = normalize_profile(item)
        if normalized is None:
            raw = item.strip().lower()[:100]
            normalized = UNKNOWN if raw == UNKNOWN else raw
        selected.add(normalized)
    if len(selected) > MAX_FILTER_VALUES:
        raise ValueError(f"at most {MAX_FILTER_VALUES} profiles can be selected")
    return sorted(selected)


def _filtered_plans(value: str | None) -> list[str]:
    selected = {normalize_plan(item) for item in _split_csv(value)}
    if len(selected) > MAX_FILTER_VALUES:
        raise ValueError(f"at most {MAX_FILTER_VALUES} plans can be selected")
    return sorted(selected)


def _round(value: float | None) -> Optional[float]:
    return round(float(value), 2) if value is not None else None


def _pct(part: int, whole: int) -> float:
    return round(part / whole * 100, 2) if whole else 0.0


def _percentile(values: list[float], fraction: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return _round(ordered[0])
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return _round(ordered[lower])
    weight = position - lower
    return _round(ordered[lower] * (1 - weight) + ordered[upper] * weight)


@dataclass
class _Group:
    before: list[float] = field(default_factory=list)
    after: list[float] = field(default_factory=list)
    users: set[str] = field(default_factory=set)

    @property
    def runs(self) -> int:
        return len(self.before)

    def add(self, *, before: float, after: float, user_id: str | None) -> None:
        self.before.append(before)
        self.after.append(after)
        if user_id:
            self.users.add(user_id)


def _metrics(group: _Group) -> dict[str, Any]:
    deltas = [after - before for before, after in zip(group.before, group.after, strict=True)]
    improved = sum(1 for delta in deltas if delta > 0)
    declined = sum(1 for delta in deltas if delta < 0)
    unchanged = len(deltas) - improved - declined
    positive = [delta for delta in deltas if delta > 0]
    return {
        "runs": group.runs,
        "users": len(group.users),
        "mean_before": _round(statistics.fmean(group.before)) if group.before else None,
        "mean_after": _round(statistics.fmean(group.after)) if group.after else None,
        "median_before": _round(statistics.median(group.before)) if group.before else None,
        "median_after": _round(statistics.median(group.after)) if group.after else None,
        "mean_delta": _round(statistics.fmean(deltas)) if deltas else None,
        "median_delta": _round(statistics.median(deltas)) if deltas else None,
        # Wording used by the D5 acceptance criteria. The median improvement is
        # the median before/after delta across all baseline rows; the positive
        # subset is reported separately.
        "median_improvement": _round(statistics.median(deltas)) if deltas else None,
        "median_positive_delta": _round(statistics.median(positive)) if positive else 0.0,
        "p25_delta": _percentile(deltas, 0.25),
        "p75_delta": _percentile(deltas, 0.75),
        "improved": improved,
        "unchanged": unchanged,
        "declined": declined,
        "improvement_rate_pct": _pct(improved, len(deltas)),
    }


def _zero_metrics() -> dict[str, Any]:
    return _metrics(_Group())


def _bucket_metadata() -> list[dict[str, Any]]:
    return [
        {
            "bucket": label,
            "lower_bound": lower,
            "upper_bound": 100.0 if label == BUCKETS[-1][2] else round(upper - 0.01, 2),
            "upper_inclusive": label == BUCKETS[-1][2],
            "before_count": 0,
            "before_pct": 0.0,
            "after_count": 0,
            "after_pct": 0.0,
        }
        for lower, upper, label in BUCKETS
    ]


class AdminAtsScoreService:
    async def distribution_report(
        self,
        db: AsyncSession,
        *,
        days: int = 30,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        industry: str | None = None,
        profile: str | None = None,
        plan: str | None = None,
    ) -> dict[str, Any]:
        days = max(1, min(int(days), MAX_RANGE_DAYS))
        start_day, end_day, start_at, end_at = _resolve_range(
            days=days, start_date=start_date, end_date=end_date
        )
        selected_range_days = (end_day - start_day).days + 1
        industries = _filtered_industries(industry)
        profiles = _filtered_profiles(profile)
        plans = _filtered_plans(plan)

        score_after = func.coalesce(Optimization.ats_score_after, Optimization.ats_score)
        stmt = (
            select(
                Optimization.ats_score_before,
                score_after.label("ats_score_after"),
                Optimization.industry,
                Optimization.profile,
                Optimization.created_at,
                Optimization.user_id,
                User.subscription_plan,
            )
            .outerjoin(User, User.id == Optimization.user_id)
            .where(
                Optimization.created_at >= start_at,
                Optimization.created_at < end_at,
                Optimization.is_auto_save.is_(False),
                Optimization.is_checkpoint.is_(False),
                score_after.is_not(None),
            )
        )
        rows = (await db.execute(stmt)).all()

        total = _Group()
        by_industry: dict[str, _Group] = defaultdict(_Group)
        by_profile: dict[str, _Group] = defaultdict(_Group)
        by_plan: dict[str, _Group] = defaultdict(_Group)
        distribution = _bucket_metadata()

        rows_scanned = 0
        invalid_scores = 0
        missing_baseline = 0

        for row in rows:
            rows_scanned += 1
            industry_key = normalize_industry(row.industry) or UNKNOWN
            profile_key = normalize_profile(row.profile) or UNKNOWN
            plan_key = normalize_plan(row.subscription_plan)

            if industries and industry_key not in industries:
                continue
            if profiles and profile_key not in profiles:
                continue
            if plans and plan_key not in plans:
                continue

            after = normalize_score(row.ats_score_after)
            if after is None:
                invalid_scores += 1
                continue
            before = normalize_score(row.ats_score_before)
            if before is None:
                missing_baseline += 1
                continue

            user_id = str(row.user_id) if row.user_id else None
            total.add(before=before, after=after, user_id=user_id)
            by_industry[industry_key].add(before=before, after=after, user_id=user_id)
            by_profile[profile_key].add(before=before, after=after, user_id=user_id)
            by_plan[plan_key].add(before=before, after=after, user_id=user_id)

            before_bucket = bucket_for_score(before)
            after_bucket = bucket_for_score(after)
            for bucket in distribution:
                if bucket["bucket"] == before_bucket:
                    bucket["before_count"] += 1
                if bucket["bucket"] == after_bucket:
                    bucket["after_count"] += 1

        evaluated = total.runs
        for bucket in distribution:
            bucket["before_pct"] = _pct(bucket["before_count"], evaluated)
            bucket["after_pct"] = _pct(bucket["after_count"], evaluated)

        suppressed = evaluated > 0 and len(total.users) < MIN_GROUP_USERS

        by_dimension: dict[str, int] = {}
        if suppressed:
            totals = _zero_metrics()
            distribution_out: list[dict[str, Any]] = []
            industry_rows: list[dict[str, Any]] = []
            profile_rows: list[dict[str, Any]] = []
            plan_rows: list[dict[str, Any]] = []
            for dimension, groups in (
                ("industry", by_industry),
                ("profile", by_profile),
                ("plan", by_plan),
            ):
                by_dimension[dimension] = len(groups)
        else:
            totals = _metrics(total)

            def _rows(
                dimension: str, groups: dict[str, _Group]
            ) -> tuple[list[dict[str, Any]], int]:
                visible: list[dict[str, Any]] = []
                hidden = 0
                for key, group in groups.items():
                    if len(group.users) < MIN_GROUP_USERS:
                        hidden += 1
                        continue
                    visible.append({dimension: key, **_metrics(group)})
                visible.sort(
                    key=lambda item: (
                        -int(item["runs"]),
                        -float(item["improvement_rate_pct"] or 0),
                        str(item[dimension]),
                    )
                )
                return visible, hidden

            industry_rows, industry_hidden = _rows("industry", by_industry)
            profile_rows, profile_hidden = _rows("profile", by_profile)
            plan_rows, plan_hidden = _rows("plan", by_plan)
            by_dimension = {
                "industry": industry_hidden,
                "profile": profile_hidden,
                "plan": plan_hidden,
            }
            distribution_out = distribution

        hidden_rows = sum(by_dimension.values())
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
                "industry": industries or None,
                "profile": profiles or None,
                "plan": plans or None,
                "timezone": "UTC",
            },
            "minimum_users": MIN_GROUP_USERS,
            "minimum_runs": MIN_GROUP_USERS,
            "suppressed": suppressed,
            "suppression": {
                "minimum_users": MIN_GROUP_USERS,
                "rule": "Hide breakdown rows with fewer than 5 distinct users; suppress all metrics when the filtered selection has fewer than 5 distinct users.",
                "filtered_suppressed": suppressed,
                "suppressed_rows": hidden_rows,
                "by_dimension": by_dimension,
            },
            "totals": totals,
            "distribution": distribution_out,
            "by_industry": industry_rows,
            "by_profile": profile_rows,
            "by_plan": plan_rows,
            "excluded": {
                "missing_baseline": missing_baseline,
                "invalid_scores": invalid_scores,
                "auto_save_rows_excluded": True,
            },
            "reconciliation": {
                "source": "optimizations",
                "rows_scanned": rows_scanned,
                "baseline_runs": evaluated,
                "missing_baseline": missing_baseline,
                "invalid_scores": invalid_scores,
                "reconciled": rows_scanned == evaluated + missing_baseline + invalid_scores,
                "hidden_by_suppression": suppressed,
            },
            "privacy": {
                "aggregate_only": True,
                "per_user_rows": False,
                "content_fields_read": [
                    "optimizations.ats_score_before",
                    "optimizations.ats_score_after",
                    "optimizations.ats_score",
                    "optimizations.industry",
                    "optimizations.profile",
                    "optimizations.created_at",
                    "users.subscription_plan",
                ],
                "content_fields_excluded": [
                    "resume and LaTeX content",
                    "job descriptions",
                    "prompts and model output",
                    "optimization change payloads",
                    "user identities and emails",
                    "per-user rows",
                ],
            },
            "notes": [
                "Only runs with both a pre-optimization baseline and a post-optimization score are counted.",
                "Rows missing a baseline are excluded from the distribution and delta math and counted under excluded.missing_baseline.",
                "Auto-save checkpoints are not optimization runs and are excluded.",
                "median_improvement is the median before/after delta; negative deltas are retained.",
                "improvement_rate_pct is the share of baseline runs with a strictly positive delta.",
                "Breakdown rows under 5 distinct users are hidden; filters selecting fewer than 5 users suppress all metrics.",
            ],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }


admin_ats_score_service = AdminAtsScoreService()
