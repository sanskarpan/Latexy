"""Admin-only referral programme analytics (issue #2066).

The report is deliberately aggregate-only and read-only.  It is built from the
existing operational tables written by the B59 referral programme:

* ``referral_attributions`` — captured/qualified/reversed first-touch rows
* ``referral_rewards`` — reward ledger status/value
* ``payments`` / ``subscriptions`` — server-verified first paid event and plan

No referral bearer code, digest, email, fingerprint, provider payment id,
payment method or per-user row is returned.  The report does not read
``usage_analytics`` or any other consent-gated behavioural telemetry, so an
operator privacy choice cannot be bypassed by this surface.  It never pays out,
issues, reverses or punishes a referral; every fraud signal is a manual-review
input only.
"""

from __future__ import annotations

import csv
import io
import math
import re
import statistics
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import PLAN_FAMILY_ALIASES, resolve_plan_family
from ..database import models

ReferralAttribution = models.ReferralAttribution
ReferralReward = models.ReferralReward
Payment = models.Payment
Subscription = models.Subscription
User = models.User

MIN_REFERRAL_USERS = 5
MAX_RANGE_DAYS = 365
MAX_PLAN_FILTERS = 6
MAX_REJECTION_REASONS = 20

PAID_PAYMENT_STATUSES = frozenset(
    {"paid", "captured", "succeeded", "partially_refunded", "refunded"}
)
REFUNDED_PAYMENT_STATUSES = frozenset({"refunded", "partially_refunded"})
REWARD_STATUS_ORDER = ("issued", "pending", "reversed", "unavailable")

FRAUD_BURST_CAPTURES = 3
FRAUD_BURST_WINDOW = timedelta(hours=24)
FRAUD_HIGH_VOLUME = 5
FRAUD_LOW_QUALIFICATION_PCT = 20.0
FRAUD_REVERSAL_COUNT = 2
FRAUD_REFUND_COUNT = 2

_REASON_LABELS = {
    "already_referred": "Account already attributed",
    "ineligible_referrer": "Referrer ineligible",
    "invalid_code": "Invalid or unknown referral code",
    "outside_attribution_window": "Outside the attribution window",
    "payment_before_attribution": "Payment predates attribution",
    "payment_refunded": "Payment refunded",
    "plan_not_qualifying": "Plan not eligible",
    "prior_payment_before_attribution": "Prior payment predates attribution",
    "referrer_limit_reached": "Referrer attribution limit reached",
    "self_referral": "Self-referral rejected",
    "subscription_missing": "Paid subscription missing",
    "reward_unavailable": "Reward unavailable for the referrer plan",
    "other": "Other recorded reason",
}

# Only allowlisted reason keys leave the service.  This prevents a legacy or
# manually-written free-form value from echoing an email, bearer token or other
# identifier through the aggregate report or CSV.
_REASON_ALIASES = {
    "account_too_old": "outside_attribution_window",
    "already_claimed": "already_referred",
    "attribution_window_expired": "outside_attribution_window",
    "duplicate": "already_referred",
    "ineligible": "ineligible_referrer",
    "limit_reached": "referrer_limit_reached",
    "no_subscription": "subscription_missing",
    "outside_window": "outside_attribution_window",
    "payment_reversed": "payment_refunded",
    "plan_not_eligible": "plan_not_qualifying",
    "refunded": "payment_refunded",
    "referral_limit": "referrer_limit_reached",
    "reward_not_available": "reward_unavailable",
    "self_referral_rejected": "self_referral",
}

CSV_COLUMNS = (
    "section",
    "key",
    "label",
    "count",
    "value_days",
    "percentage",
    "suppressed",
    "note",
)

_REASON_CLEAN_RE = re.compile(r"[^a-z0-9_]+")


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


def _plan_filters(value: str | None) -> list[str]:
    selected: list[str] = []
    for item in _split_csv(value):
        key = item.strip().lower()
        if key in {"all", "any"}:
            continue
        if key not in PLAN_FAMILY_ALIASES:
            raise ValueError("plan must be one of " + ", ".join(sorted(PLAN_FAMILY_ALIASES)))
        selected.append(resolve_plan_family(key))
    unique = sorted(set(selected))
    if len(unique) > MAX_PLAN_FILTERS:
        raise ValueError(f"at most {MAX_PLAN_FILTERS} plan families can be selected")
    return unique


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _pct(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round((numerator / denominator) * 100, 2)


def _uuid(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return None


def _reason_key(value: Any) -> Optional[str]:
    if value is None:
        return None
    cleaned = _REASON_CLEAN_RE.sub("_", str(value).strip().lower()).strip("_")[:64]
    if not cleaned:
        return None
    cleaned = _REASON_ALIASES.get(cleaned, cleaned)
    return cleaned if cleaned in _REASON_LABELS else "other"


def _reason_label(key: str) -> str:
    return _REASON_LABELS.get(key, _REASON_LABELS["other"])


def _safe_csv_cell(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    if value[:1] in {"=", "+", "-", "@", "\t", "\r"}:
        return f"'{value}"
    return value


def _percentile(values: Iterable[float], percentile: float) -> Optional[float]:
    ordered = sorted(values)
    if not ordered:
        return None
    index = min(len(ordered) - 1, max(0, math.ceil((percentile / 100) * len(ordered)) - 1))
    return ordered[index]


def _row_plan(row: Any) -> str:
    return resolve_plan_family(row.payment_plan or row.subscription_plan)


def _ever_qualified(row: Any) -> bool:
    return row.qualified_at is not None or row.status in {"qualified", "reversed"}


def _is_paid(row: Any) -> bool:
    return bool(row.qualifying_payment_id) and row.payment_status in PAID_PAYMENT_STATUSES


def _burst_size(timestamps: list[datetime]) -> int:
    ordered = sorted(timestamps)
    best = 0
    left = 0
    for right, timestamp in enumerate(ordered):
        while timestamp - ordered[left] > FRAUD_BURST_WINDOW:
            left += 1
        best = max(best, right - left + 1)
    return best


class AdminReferralAnalyticsService:
    """Build the aggregate referral funnel, reward and fraud-review report."""

    async def summary(
        self,
        db: AsyncSession,
        *,
        days: int = 30,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        plan: str | None = None,
    ) -> dict[str, Any]:
        days = max(1, min(int(days), MAX_RANGE_DAYS))
        plans = _plan_filters(plan)
        start_day, end_day, start_at, end_at = _resolve_range(
            days=days, start_date=start_date, end_date=end_date
        )

        rows = list(
            (
                await db.execute(
                    select(
                        ReferralAttribution.id,
                        ReferralAttribution.referrer_user_id,
                        ReferralAttribution.referred_user_id,
                        ReferralAttribution.status,
                        ReferralAttribution.rejection_reason,
                        ReferralAttribution.captured_at,
                        ReferralAttribution.qualified_at,
                        ReferralAttribution.reversed_at,
                        ReferralAttribution.qualifying_payment_id,
                        User.subscription_plan,
                        Subscription.plan_id.label("payment_plan"),
                        Payment.status.label("payment_status"),
                        ReferralReward.status.label("reward_status"),
                        ReferralReward.reward_value.label("reward_value"),
                        ReferralReward.issued_at.label("reward_issued_at"),
                        ReferralReward.reversed_at.label("reward_reversed_at"),
                    )
                    .join(User, User.id == ReferralAttribution.referred_user_id)
                    .outerjoin(Payment, Payment.id == ReferralAttribution.qualifying_payment_id)
                    .outerjoin(Subscription, Subscription.id == Payment.subscription_id)
                    .outerjoin(ReferralReward, ReferralReward.attribution_id == ReferralAttribution.id)
                    .where(
                        ReferralAttribution.captured_at >= start_at,
                        ReferralAttribution.captured_at < end_at,
                    )
                    .order_by(ReferralAttribution.captured_at.asc())
                )
            ).all()
        )

        if plans:
            rows = [row for row in rows if _row_plan(row) in set(plans)]

        captured = len(rows)
        cohort_users = len({_uuid(row.referred_user_id) for row in rows if _uuid(row.referred_user_id)})
        suppressed = 0 < cohort_users < MIN_REFERRAL_USERS

        if suppressed:
            return self._suppressed_payload(
                days=days,
                start_day=start_day,
                end_day=end_day,
                plans=plans,
                cohort_users=cohort_users,
                captured=captured,
            )

        ever_qualified_rows = [row for row in rows if _ever_qualified(row)]
        paid_rows = [row for row in rows if _is_paid(row)]
        reversed_rows = [row for row in rows if row.status == "reversed"]
        qualified_rows = [row for row in rows if row.status == "qualified"]

        funnel = {
            "captured": captured,
            "qualified": len(ever_qualified_rows),
            "paid": len(paid_rows),
            "currently_qualified": len(qualified_rows),
            "reversed": len(reversed_rows),
            "qualified_conversion_pct": _pct(len(ever_qualified_rows), captured),
            "paid_conversion_pct": _pct(len(paid_rows), captured),
            "paid_conversion_rate": _pct(len(paid_rows), captured),
            "reversal_pct": _pct(len(reversed_rows), len(ever_qualified_rows)),
            "suppressed": False,
            "stages": [
                {"key": "captured", "label": "Captured", "count": captured},
                {
                    "key": "qualified",
                    "label": "Qualified by first paid event",
                    "count": len(ever_qualified_rows),
                },
                {"key": "paid", "label": "First paid confirmed", "count": len(paid_rows)},
            ],
        }

        reward_summary = self._reward_summary(rows)
        rejection_reasons = self._rejection_reasons(rows)
        time_to_qualify = self._time_to_qualify(rows)
        fraud_review = self._fraud_review(rows)
        by_plan = self._by_plan(rows)

        reward_total = reward_summary["total_rewards"]
        source_reward_count = sum(1 for row in rows if row.reward_status)
        source_paid = len(paid_rows)
        source_qualified = len(ever_qualified_rows)
        source_reversed = len(reversed_rows)
        counts = {
            "source_attributions": captured,
            "funnel_captured": funnel["captured"],
            "source_qualified": source_qualified,
            "funnel_qualified": funnel["qualified"],
            "source_paid": source_paid,
            "funnel_paid": funnel["paid"],
            "source_reversed": source_reversed,
            "funnel_reversed": funnel["reversed"],
            "source_rewards": source_reward_count,
            "reward_total": reward_total,
        }
        reconciled = (
            counts["source_attributions"] == counts["funnel_captured"]
            and counts["source_qualified"] == counts["funnel_qualified"]
            and counts["source_paid"] == counts["funnel_paid"]
            and counts["source_reversed"] == counts["funnel_reversed"]
            and counts["source_rewards"] == counts["reward_total"]
        )

        qualified_without_qualified_at = sum(
            1
            for row in ever_qualified_rows
            if row.qualified_at is None
        )
        qualified_without_reward = sum(
            1 for row in ever_qualified_rows if not row.reward_status
        )
        missing_payments = sum(
            1
            for row in rows
            if row.qualifying_payment_id and row.payment_status is None
        )
        invalid_time_to_qualify = sum(
            1
            for row in ever_qualified_rows
            if row.qualified_at is not None
            and row.captured_at is not None
            and _aware(row.qualified_at) < _aware(row.captured_at)
        )

        activity = {
            "captured_in_range": captured,
            "qualified_in_range": sum(
                1
                for row in rows
                if row.qualified_at is not None and start_at <= _aware(row.qualified_at) < end_at
            ),
            "reversed_in_range": sum(
                1
                for row in rows
                if row.reversed_at is not None and start_at <= _aware(row.reversed_at) < end_at
            ),
            "rewards_issued_in_range": sum(
                1
                for row in rows
                if row.reward_issued_at is not None
                and start_at <= _aware(row.reward_issued_at) < end_at
            ),
            "rewards_reversed_in_range": sum(
                1
                for row in rows
                if row.reward_reversed_at is not None
                and start_at <= _aware(row.reward_reversed_at) < end_at
            ),
        }

        return {
            "days": (end_day - start_day).days + 1,
            "start_date": start_day.isoformat(),
            "end_date": end_day.isoformat(),
            "timezone": "UTC",
            "date_range": {
                "start": start_at.isoformat(),
                "end": end_at.isoformat(),
                "days": (end_day - start_day).days + 1,
                "timezone": "UTC",
            },
            "filters": {
                "days": days,
                "start_date": start_day.isoformat(),
                "end_date": end_day.isoformat(),
                "plan": plans or None,
                "timezone": "UTC",
            },
            "minimum_users": MIN_REFERRAL_USERS,
            "suppressed": False,
            "suppression": {
                "minimum_users": MIN_REFERRAL_USERS,
                "applied": False,
                "distinct_referred_users": cohort_users,
                "suppressed_groups": (
                    reward_summary["suppressed_statuses"]
                    + rejection_reasons["suppressed_reasons"]
                    + fraud_review["suppressed_signals"]
                    + sum(1 for item in by_plan if item.get("__suppressed__"))
                ),
                "rule": (
                    "Hide any referral cohort or breakdown group with fewer than 5 "
                    "distinct referred users; a filtered cohort of 1-4 users returns "
                    "null metrics."
                ),
            },
            "funnel": funnel,
            "totals": {
                "captured": funnel["captured"],
                "qualified": funnel["qualified"],
                "paid": funnel["paid"],
                "reversed": funnel["reversed"],
                "rewards": reward_summary["total_rewards"],
                "reward_value_days": reward_summary["total_value_days"],
            },
            "conversion": {
                "capture_to_qualified_pct": funnel["qualified_conversion_pct"],
                "paid_conversion_pct": funnel["paid_conversion_pct"],
                "paid_conversion_rate": funnel["paid_conversion_rate"],
                "reversal_pct": funnel["reversal_pct"],
            },
            "definitions": {
                "captured": "First-touch referral attribution row persisted after signup.",
                "qualified": "A server-verified paid payment qualified the attribution.",
                "paid": "The qualifying payment is in a settled paid status.",
                "reversed": "A provider refund reversed the attribution and reward.",
                "reward_status": "Ledger status of the subscription-extension reward.",
                "click_through": (
                    "Referral click-throughs are not persisted; capture is the first "
                    "reportable funnel stage."
                ),
            },
            "reward_summary": reward_summary,
            "rejection_reasons": rejection_reasons,
            "time_to_qualify": time_to_qualify,
            "fraud_review": fraud_review,
            "fraud_signals": fraud_review["signals"],
            "fraud_review_queue": fraud_review["queue"],
            "by_plan": [item for item in by_plan if not item.get("__suppressed__")],
            "activity": activity,
            "reconciliation": {
                "source": "referral_attributions + referral_rewards",
                "counts": counts,
                "qualified_without_qualified_at": qualified_without_qualified_at,
                "qualified_without_reward": qualified_without_reward,
                "missing_payments": missing_payments,
                "invalid_time_to_qualify": invalid_time_to_qualify,
                "reconciled": reconciled,
            },
            "payout": {
                "status": "not_applicable",
                "basis": (
                    "The programme issues subscription extension days in the reward "
                    "ledger; no cash payout or provider transfer exists."
                ),
                "automatic_payout": False,
            },
            "programme_issue": 1341,
            "data_sources": [
                "referral_attributions",
                "referral_rewards",
                "payments",
                "subscriptions",
                "users.subscription_plan",
            ],
            "privacy": {
                "aggregate_only": True,
                "minimum_users": MIN_REFERRAL_USERS,
                "excluded_fields": [
                    "referral bearer code",
                    "referral code digest",
                    "email",
                    "raw fingerprint",
                    "provider payment id",
                    "payment credentials",
                ],
                "reads_consent_gated_analytics": False,
            },
            "automation": {
                "automatic_payout": False,
                "automatic_punishment": False,
                "manual_review_required": True,
            },
            "notes": [
                "Aggregates are derived from operational referral, reward and billing rows only.",
                "No usage_analytics or consent-gated behavioural telemetry is read.",
                "Referral click-throughs are not persisted; capture is the first reportable stage.",
                "Read-only: this report never issues, reverses, pays out or penalises a referral.",
            ],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _reward_summary(self, rows: list[Any]) -> dict[str, Any]:
        counts: dict[str, int] = defaultdict(int)
        value_days: dict[str, int] = defaultdict(int)
        total_rewards = 0
        total_value = 0
        for row in rows:
            if not row.reward_status:
                continue
            status = str(row.reward_status)
            if status not in REWARD_STATUS_ORDER:
                status = "other"
            value = max(0, int(row.reward_value or 0))
            counts[status] += 1
            value_days[status] += value
            total_rewards += 1
            total_value += value

        statuses: list[dict[str, Any]] = []
        hidden = 0
        for status in (*REWARD_STATUS_ORDER, "other"):
            count = counts.get(status, 0)
            if count == 0:
                continue
            if count < MIN_REFERRAL_USERS:
                hidden += 1
                continue
            statuses.append(
                {
                    "status": status,
                    "label": status.replace("_", " ").title(),
                    "rewards": count,
                    "value_days": value_days.get(status, 0),
                    "suppressed": False,
                }
            )

        return {
            "statuses": statuses,
            "total_rewards": total_rewards,
            "total_value_days": total_value,
            "issued": counts.get("issued", 0),
            "pending": counts.get("pending", 0),
            "reversed": counts.get("reversed", 0),
            "unavailable": counts.get("unavailable", 0),
            "issued_value_days": value_days.get("issued", 0),
            "pending_value_days": value_days.get("pending", 0),
            "reversed_value_days": value_days.get("reversed", 0),
            "payout_status": "not_applicable",
            "payout_basis": (
                "Rewards are subscription extension days in the referral ledger; "
                "there is no cash payout or provider transfer to report."
            ),
            "suppressed_statuses": hidden,
            "suppressed": False,
        }

    def _rejection_reasons(self, rows: list[Any]) -> dict[str, Any]:
        counts: dict[str, int] = defaultdict(int)
        for row in rows:
            reason = _reason_key(row.rejection_reason)
            if reason is None and row.status == "reversed":
                # A reversal is only written after a provider refund in
                # ``referral_service.reverse_paid_payment``.  Persisted legacy
                # rows may not have the explicit label, so derive the safe one.
                reason = "payment_refunded"
            if reason is not None:
                counts[reason] += 1

        items: list[dict[str, Any]] = []
        hidden = 0
        for reason, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
            if count < MIN_REFERRAL_USERS:
                hidden += 1
                continue
            if len(items) >= MAX_REJECTION_REASONS:
                hidden += 1
                continue
            items.append(
                {
                    "reason": reason,
                    "label": _reason_label(reason),
                    "count": count,
                    "suppressed": False,
                }
            )

        return {
            "items": items,
            "suppressed_reasons": hidden,
            "suppressed": False,
            "basis": (
                "Persisted attribution rejection/reversal reasons. Claim-time "
                "rejections that never create an attribution row are not stored "
                "and therefore cannot be reported."
            ),
        }

    def _time_to_qualify(self, rows: list[Any]) -> dict[str, Any]:
        durations: list[float] = []
        for row in rows:
            if not _ever_qualified(row) or row.qualified_at is None or row.captured_at is None:
                continue
            captured_at = _aware(row.captured_at)
            qualified_at = _aware(row.qualified_at)
            if captured_at is None or qualified_at is None or qualified_at < captured_at:
                continue
            durations.append((qualified_at - captured_at).total_seconds())

        sample_size = len(durations)
        if sample_size < MIN_REFERRAL_USERS:
            return {
                "basis": "captured_at -> qualified_at",
                "sample_size": sample_size if sample_size == 0 else None,
                "average_hours": None,
                "median_hours": None,
                "p90_hours": None,
                "average_days": None,
                "median_days": None,
                "p90_days": None,
                "buckets": [],
                "suppressed": sample_size > 0,
            }

        average = sum(durations) / sample_size
        median = statistics.median(durations)
        p90 = _percentile(durations, 90)
        bucket_defs = (
            ("under_1_hour", "Under 1 hour", 0, 3_600),
            ("1_to_24_hours", "1-24 hours", 3_600, 86_400),
            ("1_to_7_days", "1-7 days", 86_400, 604_800),
            ("over_7_days", "Over 7 days", 604_800, None),
        )
        buckets: list[dict[str, Any]] = []
        hidden = 0
        for key, label, minimum, maximum in bucket_defs:
            count = sum(
                1
                for seconds in durations
                if seconds >= minimum and (maximum is None or seconds < maximum)
            )
            if count == 0:
                continue
            if count < MIN_REFERRAL_USERS:
                hidden += 1
                continue
            buckets.append({"key": key, "label": label, "count": count, "suppressed": False})

        return {
            "basis": "captured_at -> qualified_at",
            "sample_size": sample_size,
            "average_hours": round(average / 3_600, 2),
            "median_hours": round(median / 3_600, 2),
            "p90_hours": round((p90 or 0) / 3_600, 2),
            "average_days": round(average / 86_400, 2),
            "median_days": round(median / 86_400, 2),
            "p90_days": round((p90 or 0) / 86_400, 2),
            "buckets": buckets,
            "suppressed_buckets": hidden,
            "suppressed": False,
        }

    def _fraud_review(self, rows: list[Any]) -> dict[str, Any]:
        stats: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "captured": 0,
                "qualified": 0,
                "reversed": 0,
                "refunded": 0,
                "timestamps": [],
            }
        )
        for row in rows:
            referrer = _uuid(row.referrer_user_id)
            if referrer is None:
                continue
            entry = stats[referrer]
            entry["captured"] += 1
            if _ever_qualified(row):
                entry["qualified"] += 1
            if row.status == "reversed":
                entry["reversed"] += 1
            if row.payment_status in REFUNDED_PAYMENT_STATUSES:
                entry["refunded"] += 1
            captured_at = _aware(row.captured_at)
            if captured_at is not None:
                entry["timestamps"].append(captured_at)

        def _aggregate(members: list[dict[str, Any]], key: str) -> int:
            return sum(int(member[key]) for member in members)

        signals: list[dict[str, Any]] = []
        hidden = 0

        def _add_signal(
            *,
            key: str,
            label: str,
            priority: str,
            threshold: str,
            members: list[dict[str, Any]],
        ) -> None:
            nonlocal hidden
            if len(members) < MIN_REFERRAL_USERS:
                hidden += 1
                return
            signals.append(
                {
                    "key": key,
                    "label": label,
                    "priority": priority,
                    "threshold": threshold,
                    "referrers": len(members),
                    "captured": _aggregate(members, "captured"),
                    "qualified": _aggregate(members, "qualified"),
                    "reversed": _aggregate(members, "reversed"),
                    "refunded": _aggregate(members, "refunded"),
                    "suppressed": False,
                }
            )

        burst_members = [
            entry for entry in stats.values() if _burst_size(entry["timestamps"]) >= FRAUD_BURST_CAPTURES
        ]
        _add_signal(
            key="rapid_capture_burst",
            label="Captures clustered in a short window",
            priority="medium",
            threshold=f"{FRAUD_BURST_CAPTURES}+ captures by one referrer within 24 hours",
            members=burst_members,
        )

        low_qualification_members = [
            entry
            for entry in stats.values()
            if entry["captured"] >= FRAUD_HIGH_VOLUME
            and _pct(entry["qualified"], entry["captured"]) < FRAUD_LOW_QUALIFICATION_PCT
        ]
        _add_signal(
            key="high_volume_low_qualification",
            label="High capture volume with low qualification",
            priority="medium",
            threshold=(
                f"{FRAUD_HIGH_VOLUME}+ captures and under "
                f"{FRAUD_LOW_QUALIFICATION_PCT:.0f}% qualified"
            ),
            members=low_qualification_members,
        )

        reversal_members = [
            entry for entry in stats.values() if entry["reversed"] >= FRAUD_REVERSAL_COUNT
        ]
        _add_signal(
            key="repeated_reversals",
            label="Repeated reversals for one referrer",
            priority="high",
            threshold=f"{FRAUD_REVERSAL_COUNT}+ reversed attributions",
            members=reversal_members,
        )

        refund_members = [
            entry for entry in stats.values() if entry["refunded"] >= FRAUD_REFUND_COUNT
        ]
        _add_signal(
            key="payment_refund_cluster",
            label="Refunded qualifying payments for one referrer",
            priority="high",
            threshold=f"{FRAUD_REFUND_COUNT}+ refunded qualifying payments",
            members=refund_members,
        )

        signals.sort(key=lambda item: (0 if item["priority"] == "high" else 1, item["key"]))
        queue = [
            {
                "signal": signal["key"],
                "label": signal["label"],
                "priority": signal["priority"],
                "referrers": signal["referrers"],
                "recommended_action": "manual_review",
                "automatic_action": False,
            }
            for signal in signals
        ]

        return {
            "method": "aggregate_heuristics",
            "signals": signals,
            "queue": queue,
            "signal_count": len(signals),
            "suppressed_signals": hidden,
            "may_overlap": True,
            "manual_review_required": True,
            "automatic_payout": False,
            "automatic_punishment": False,
            "suppressed": False,
        }

    def _by_plan(self, rows: list[Any]) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, int]] = defaultdict(
            lambda: {"captured": 0, "qualified": 0, "paid": 0, "reversed": 0, "rewards": 0}
        )
        for row in rows:
            entry = grouped[_row_plan(row)]
            entry["captured"] += 1
            if _ever_qualified(row):
                entry["qualified"] += 1
            if _is_paid(row):
                entry["paid"] += 1
            if row.status == "reversed":
                entry["reversed"] += 1
            if row.reward_status:
                entry["rewards"] += 1

        result: list[dict[str, Any]] = []
        for plan, entry in sorted(grouped.items(), key=lambda item: (-item[1]["captured"], item[0])):
            if entry["captured"] < MIN_REFERRAL_USERS:
                result.append({"plan": plan, "__suppressed__": True})
                continue
            result.append(
                {
                    "plan": plan,
                    "captured": entry["captured"],
                    "qualified": entry["qualified"],
                    "paid": entry["paid"],
                    "reversed": entry["reversed"],
                    "rewards": entry["rewards"],
                    "paid_conversion_pct": _pct(entry["paid"], entry["captured"]),
                }
            )
        return result

    def _suppressed_payload(
        self,
        *,
        days: int,
        start_day: date,
        end_day: date,
        plans: list[str],
        cohort_users: int,
        captured: int,
    ) -> dict[str, Any]:
        return {
            "days": (end_day - start_day).days + 1,
            "start_date": start_day.isoformat(),
            "end_date": end_day.isoformat(),
            "timezone": "UTC",
            "date_range": {
                "start": datetime.combine(start_day, time.min, tzinfo=timezone.utc).isoformat(),
                "end": datetime.combine(
                    end_day + timedelta(days=1), time.min, tzinfo=timezone.utc
                ).isoformat(),
                "days": (end_day - start_day).days + 1,
                "timezone": "UTC",
            },
            "filters": {
                "days": days,
                "start_date": start_day.isoformat(),
                "end_date": end_day.isoformat(),
                "plan": plans or None,
                "timezone": "UTC",
            },
            "minimum_users": MIN_REFERRAL_USERS,
            "suppressed": True,
            "suppression": {
                "minimum_users": MIN_REFERRAL_USERS,
                "applied": True,
                "distinct_referred_users": None,
                "suppressed_groups": 0,
                "rule": (
                    "Hide any referral cohort or breakdown group with fewer than 5 "
                    "distinct referred users; a filtered cohort of 1-4 users returns "
                    "null metrics."
                ),
            },
            "funnel": {
                "captured": None,
                "qualified": None,
                "paid": None,
                "currently_qualified": None,
                "reversed": None,
                "qualified_conversion_pct": None,
                "paid_conversion_pct": None,
                "paid_conversion_rate": None,
                "reversal_pct": None,
                "suppressed": True,
                "stages": [],
            },
            "totals": {
                "captured": None,
                "qualified": None,
                "paid": None,
                "reversed": None,
                "rewards": None,
                "reward_value_days": None,
            },
            "conversion": {
                "capture_to_qualified_pct": None,
                "paid_conversion_pct": None,
                "paid_conversion_rate": None,
                "reversal_pct": None,
            },
            "definitions": {
                "captured": "First-touch referral attribution row persisted after signup.",
                "qualified": "A server-verified paid payment qualified the attribution.",
                "paid": "The qualifying payment is in a settled paid status.",
                "reversed": "A provider refund reversed the attribution and reward.",
                "reward_status": "Ledger status of the subscription-extension reward.",
                "click_through": (
                    "Referral click-throughs are not persisted; capture is the first "
                    "reportable funnel stage."
                ),
            },
            "reward_summary": {
                "statuses": [],
                "total_rewards": None,
                "total_value_days": None,
                "issued": None,
                "pending": None,
                "reversed": None,
                "unavailable": None,
                "issued_value_days": None,
                "pending_value_days": None,
                "reversed_value_days": None,
                "payout_status": "not_applicable",
                "payout_basis": (
                    "Rewards are subscription extension days in the referral ledger; "
                    "there is no cash payout or provider transfer to report."
                ),
                "suppressed_statuses": 0,
                "suppressed": True,
            },
            "rejection_reasons": {
                "items": [],
                "suppressed_reasons": 0,
                "suppressed": True,
                "basis": "Suppressed for a cohort below the five-user floor.",
            },
            "time_to_qualify": {
                "basis": "captured_at -> qualified_at",
                "sample_size": None,
                "average_hours": None,
                "median_hours": None,
                "p90_hours": None,
                "average_days": None,
                "median_days": None,
                "p90_days": None,
                "buckets": [],
                "suppressed": True,
            },
            "fraud_review": {
                "method": "aggregate_heuristics",
                "signals": [],
                "queue": [],
                "signal_count": None,
                "suppressed_signals": 0,
                "may_overlap": True,
                "manual_review_required": True,
                "automatic_payout": False,
                "automatic_punishment": False,
                "suppressed": True,
            },
            "fraud_signals": [],
            "fraud_review_queue": [],
            "by_plan": [],
            "activity": {
                "captured_in_range": None,
                "qualified_in_range": None,
                "reversed_in_range": None,
                "rewards_issued_in_range": None,
                "rewards_reversed_in_range": None,
            },
            "reconciliation": {
                "source": "referral_attributions + referral_rewards",
                "counts": {},
                "qualified_without_qualified_at": None,
                "qualified_without_reward": None,
                "missing_payments": None,
                "invalid_time_to_qualify": None,
                "reconciled": None,
            },
            "payout": {
                "status": "not_applicable",
                "basis": (
                    "The programme issues subscription extension days in the reward "
                    "ledger; no cash payout or provider transfer exists."
                ),
                "automatic_payout": False,
            },
            "programme_issue": 1341,
            "data_sources": [
                "referral_attributions",
                "referral_rewards",
                "payments",
                "subscriptions",
                "users.subscription_plan",
            ],
            "privacy": {
                "aggregate_only": True,
                "minimum_users": MIN_REFERRAL_USERS,
                "excluded_fields": [
                    "referral bearer code",
                    "referral code digest",
                    "email",
                    "raw fingerprint",
                    "provider payment id",
                    "payment credentials",
                ],
                "reads_consent_gated_analytics": False,
            },
            "automation": {
                "automatic_payout": False,
                "automatic_punishment": False,
                "manual_review_required": True,
            },
            "notes": [
                "Aggregates are derived from operational referral, reward and billing rows only.",
                "No usage_analytics or consent-gated behavioural telemetry is read.",
                "Read-only: this report never issues, reverses, pays out or penalises a referral.",
            ],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def to_csv(self, result: dict[str, Any]) -> str:
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(CSV_COLUMNS)

        def write(
            section: str,
            key: str,
            label: Any,
            *,
            count: Any = "",
            value_days: Any = "",
            percentage: Any = "",
            suppressed: bool = False,
            note: Any = "",
        ) -> None:
            writer.writerow(
                [
                    _safe_csv_cell(section),
                    _safe_csv_cell(key),
                    _safe_csv_cell(label),
                    count,
                    value_days,
                    percentage,
                    str(bool(suppressed)).lower(),
                    _safe_csv_cell(note),
                ]
            )

        filters = result.get("filters") or {}
        write("filter", "start_date", filters.get("start_date") or result.get("start_date"))
        write("filter", "end_date", filters.get("end_date") or result.get("end_date"))
        write("filter", "plan", ",".join(filters.get("plan") or []) or "all")

        if result.get("suppressed"):
            write(
                "suppression",
                "cohort",
                "Cohort suppressed",
                suppressed=True,
                note=result.get("suppression", {}).get("rule", ""),
            )
            return buffer.getvalue()

        funnel = result.get("funnel") or {}
        for key, label in (
            ("captured", "Captured"),
            ("qualified", "Qualified"),
            ("paid", "Paid"),
            ("currently_qualified", "Currently qualified"),
            ("reversed", "Reversed"),
        ):
            write("funnel", key, label, count=funnel.get(key))
        for key, label in (
            ("qualified_conversion_pct", "Capture to qualified"),
            ("paid_conversion_pct", "Paid conversion"),
            ("reversal_pct", "Reversal share of qualified"),
        ):
            write("conversion", key, label, percentage=funnel.get(key))

        rewards = result.get("reward_summary") or {}
        for item in rewards.get("statuses") or []:
            write(
                "reward_status",
                item.get("status"),
                item.get("label"),
                count=item.get("rewards"),
                value_days=item.get("value_days"),
            )
        write("reward_total", "total_rewards", "Total rewards", count=rewards.get("total_rewards"))
        for key, label in (
            ("total_value_days", "Total reward days"),
            ("issued_value_days", "Issued reward days"),
            ("pending_value_days", "Pending reward days"),
            ("reversed_value_days", "Reversed reward days"),
        ):
            write("reward_total", key, label, value_days=rewards.get(key))
        payout = result.get("payout") or {}
        write("payout", "status", payout.get("status"), note=payout.get("basis"))

        reasons = result.get("rejection_reasons") or {}
        for item in reasons.get("items") or []:
            write(
                "rejection_reason",
                item.get("reason"),
                item.get("label"),
                count=item.get("count"),
            )
        if reasons.get("suppressed_reasons"):
            write(
                "rejection_reason",
                "suppressed",
                "Suppressed reason groups",
                suppressed=True,
                note="Fewer than 5 users in each hidden group.",
            )

        timing = result.get("time_to_qualify") or {}
        for key, label in (
            ("sample_size", "Sample size"),
            ("average_hours", "Average hours"),
            ("median_hours", "Median hours"),
            ("p90_hours", "P90 hours"),
            ("average_days", "Average days"),
            ("median_days", "Median days"),
            ("p90_days", "P90 days"),
        ):
            write("time_to_qualify", key, label, count=timing.get(key))
        for item in timing.get("buckets") or []:
            write("time_to_qualify", item.get("key"), item.get("label"), count=item.get("count"))

        fraud = result.get("fraud_review") or {}
        for item in fraud.get("signals") or []:
            write(
                "fraud_signal",
                item.get("key"),
                item.get("label"),
                count=item.get("referrers"),
                note=item.get("threshold"),
            )
        if fraud.get("suppressed_signals"):
            write(
                "fraud_signal",
                "suppressed",
                "Suppressed signal groups",
                suppressed=True,
                note="Fewer than 5 referrers in each hidden group.",
            )

        for item in result.get("by_plan") or []:
            write(
                "plan",
                item.get("plan"),
                item.get("plan"),
                count=item.get("captured"),
                percentage=item.get("paid_conversion_pct"),
            )

        reconciliation = result.get("reconciliation") or {}
        for key, value in (reconciliation.get("counts") or {}).items():
            write("reconciliation", key, key.replace("_", " ").title(), count=value)
        write(
            "reconciliation",
            "reconciled",
            "Counts reconcile",
            note=str(bool(reconciliation.get("reconciled"))).lower(),
        )
        return buffer.getvalue()


admin_referral_analytics_service = AdminReferralAnalyticsService()
