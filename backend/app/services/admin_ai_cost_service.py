"""Versioned AI cost rollups, spend caps, and rolling anomaly signals.

The ledger is intentionally built from first-party records only:

* ``optimizations`` keeps the legacy per-run token total recorded by the UI.
* ``resume_optimization_stages`` keeps the paid resume-engine stage usage,
  including the provider-reported ``cost_usd`` when available.

Neither source stores a provider key.  Unknown models are never priced as if
they were free: they use a visible fallback estimate and are marked in every
rollup so an operator can reconcile the gap against an invoice.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.log_sanitize import sanitize_for_log
from ..core.logging import get_logger
from ..database import models

logger = get_logger(__name__)

RUNBOOK_URL = "https://github.com/sanskarpan/Latexy/blob/main/docs/ADMIN_CONTROL_ROOM.md"
FALLBACK_PER_MILLION_USD = 3.0
PRICING_SCHEMA_VERSION = "pricing-v1"
INVOICE_CONTRACT_VERSION = "ai-invoice-sample-v1"

PAID_PAYMENT_STATUSES = ("paid", "partially_refunded", "captured", "refunded")
REFUNDED_STATUSES = ("succeeded",)

_STAGE_FEATURES = (
    ("requirements", "requirements"),
    ("patches", "optimization_patches"),
    ("support-review", "support_review"),
    ("global-review", "quality_review"),
    ("refinement", "refinement"),
)


def _utc(value: datetime | None = None) -> datetime:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _day_key(value: datetime | date | None) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, datetime):
        return _utc(value).date().isoformat()
    return value.isoformat()


def _minor(value: float) -> int:
    """Convert a major-unit amount to integer minor units without float drift."""
    if not math.isfinite(value):
        return 0
    return int(round(value * 100))


def _float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) and value >= 0 else None


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _stage_feature(stage_key: str | None) -> str:
    key = (stage_key or "").strip().lower()
    for prefix, label in _STAGE_FEATURES:
        if key.startswith(prefix):
            return label
    return key[:120] or "resume_engine_stage"


def _persona(settings_json: Any) -> str:
    value = None
    if isinstance(settings_json, dict):
        value = settings_json.get("last_persona")
    if not isinstance(value, str):
        return "unknown"
    value = value.strip().lower()
    if not value or len(value) > 64:
        return "unknown"
    if not all(char.isalnum() or char in {"_", "-"} for char in value):
        return "unknown"
    return value


@dataclass(frozen=True)
class PriceQuote:
    input_per_million: float
    output_per_million: float
    blended_per_million: float
    status: str
    known: bool


@dataclass(frozen=True)
class PricingBook:
    version: str
    fallback_per_million_usd: float
    models: tuple[dict[str, Any], ...]

    def quote(self, provider: str, model: str) -> PriceQuote:
        key = f"{provider}:{model}"
        for row in self.models:
            if row["key"] == key:
                return PriceQuote(
                    input_per_million=float(row["input_per_million_usd"]),
                    output_per_million=float(row["output_per_million_usd"]),
                    blended_per_million=float(row["blended_per_million_usd"]),
                    status="configured",
                    known=True,
                )
        return PriceQuote(
            input_per_million=self.fallback_per_million_usd,
            output_per_million=self.fallback_per_million_usd,
            blended_per_million=self.fallback_per_million_usd,
            status="fallback_estimate",
            known=False,
        )

    def public(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "schema_version": PRICING_SCHEMA_VERSION,
            "source": "settings.RESUME_ENGINE_MODEL_PRICING",
            "currency": "USD",
            "minor_unit": "cent",
            "unit": "per_million_tokens",
            "blended_for_total_tokens": True,
            "fallback_per_million_usd": self.fallback_per_million_usd,
            "models": list(self.models),
        }


def _pricing_book() -> PricingBook:
    raw = settings.RESUME_ENGINE_MODEL_PRICING or {}
    rows: list[dict[str, Any]] = []
    canonical: list[list[Any]] = []
    for key, price in raw.items():
        if not isinstance(key, str) or ":" not in key or not isinstance(price, dict):
            continue
        provider, model = key.split(":", 1)
        input_price = _float(price.get("input_per_million"))
        output_price = _float(price.get("output_per_million"))
        if input_price is None or output_price is None:
            continue
        row = {
            "key": key,
            "provider": provider,
            "model": model,
            "input_per_million_usd": input_price,
            "output_per_million_usd": output_price,
            "blended_per_million_usd": (input_price + output_price) / 2,
        }
        rows.append(row)
        canonical.append([key, input_price, output_price])
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:12]
    return PricingBook(
        version=f"{PRICING_SCHEMA_VERSION}:{digest}",
        fallback_per_million_usd=FALLBACK_PER_MILLION_USD,
        models=tuple(sorted(rows, key=lambda item: item["key"])),
    )


@dataclass
class CostEntry:
    occurred_at: datetime
    day: str
    user_id: str | None
    plan: str
    provider: str
    model: str
    tokens: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    feature: str
    persona: str
    source: str
    row_id: str
    pricing_status: str
    estimated: bool
    unknown_pricing: bool


@dataclass
class _Bucket:
    runs: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    estimated_runs: int = 0
    unknown_pricing_runs: int = 0
    revenue_inr: float = 0.0
    pricing_statuses: set[str] = field(default_factory=set)

    def add(self, entry: CostEntry) -> None:
        self.runs += 1
        self.tokens += entry.tokens
        self.cost_usd += entry.cost_usd
        if entry.estimated:
            self.estimated_runs += 1
        if entry.unknown_pricing:
            self.unknown_pricing_runs += 1
        self.pricing_statuses.add(entry.pricing_status)


def _bucket_row(label: str, bucket: _Bucket, key_name: str = "label") -> dict[str, Any]:
    return {
        key_name: label,
        "runs": bucket.runs,
        "tokens": bucket.tokens,
        "cost_usd": round(bucket.cost_usd, 6),
        "cost_usd_minor": _minor(bucket.cost_usd),
        "estimated_runs": bucket.estimated_runs,
        "unknown_pricing_runs": bucket.unknown_pricing_runs,
    }


def _model_pricing_status(bucket: _Bucket) -> str:
    if bucket.pricing_statuses == {"recorded_usage"}:
        return "recorded_usage"
    if bucket.unknown_pricing_runs:
        return "fallback_estimate"
    if "recorded_usage" in bucket.pricing_statuses:
        return "mixed_recorded_usage"
    return "configured"


async def _load_cost_entries(
    db: AsyncSession,
    *,
    start: datetime,
    end: datetime,
    user_id: str | None = None,
) -> list[CostEntry]:
    pricing = _pricing_book()
    entries: list[CostEntry] = []

    optimization_stmt = (
        select(
            models.Optimization.id,
            models.Optimization.user_id,
            models.Optimization.provider,
            models.Optimization.model,
            models.Optimization.tokens_used,
            models.Optimization.created_at,
            models.User.subscription_plan,
            models.Resume.resume_settings,
        )
        .outerjoin(models.User, models.User.id == models.Optimization.user_id)
        .outerjoin(models.Resume, models.Resume.id == models.Optimization.resume_id)
        .where(
            models.Optimization.created_at >= start,
            models.Optimization.created_at <= end,
            models.Optimization.tokens_used.is_not(None),
            models.Optimization.tokens_used > 0,
            models.Optimization.is_auto_save.is_not(True),
        )
    )
    if user_id:
        optimization_stmt = optimization_stmt.where(models.Optimization.user_id == user_id)
    for row_id, row_user, provider, model, tokens, created_at, plan, resume_settings in (
        await db.execute(optimization_stmt)
    ).all():
        token_count = int(tokens or 0)
        if token_count <= 0:
            continue
        provider_name = (provider or "unknown")[:80]
        model_name = (model or "unknown")[:160]
        quote = pricing.quote(provider_name, model_name)
        cost = token_count / 1_000_000 * quote.blended_per_million
        occurred = _utc(created_at)
        entries.append(
            CostEntry(
                occurred_at=occurred,
                day=_day_key(occurred),
                user_id=str(row_user) if row_user else None,
                plan=plan or "free",
                provider=provider_name,
                model=model_name,
                tokens=token_count,
                input_tokens=0,
                output_tokens=0,
                cost_usd=cost,
                feature="resume_optimization",
                persona=_persona(resume_settings),
                source="optimization_history",
                row_id=str(row_id),
                pricing_status=quote.status,
                estimated=not quote.known,
                unknown_pricing=not quote.known,
            )
        )

    stage_stmt = (
        select(
            models.ResumeOptimizationStage.id,
            models.ResumeOptimizationRun.user_id,
            models.ResumeOptimizationRun.provider,
            models.ResumeOptimizationRun.model,
            models.ResumeOptimizationStage.stage_key,
            models.ResumeOptimizationStage.usage,
            models.ResumeOptimizationStage.completed_at,
            models.ResumeOptimizationStage.created_at,
            models.User.subscription_plan,
            models.Resume.resume_settings,
        )
        .join(
            models.ResumeOptimizationRun,
            models.ResumeOptimizationRun.id == models.ResumeOptimizationStage.run_id,
        )
        .outerjoin(models.User, models.User.id == models.ResumeOptimizationRun.user_id)
        .outerjoin(models.Resume, models.Resume.id == models.ResumeOptimizationRun.resume_id)
        .where(
            models.ResumeOptimizationStage.status.in_(("completed", "ambiguous")),
            models.ResumeOptimizationStage.usage.is_not(None),
            func.coalesce(
                models.ResumeOptimizationStage.completed_at,
                models.ResumeOptimizationStage.created_at,
            ).between(start, end),
        )
    )
    if user_id:
        stage_stmt = stage_stmt.where(models.ResumeOptimizationRun.user_id == user_id)
    for row_id, row_user, provider, model, stage_key, usage, completed_at, created_at, plan, resume_settings in (
        await db.execute(stage_stmt)
    ).all():
        payload = usage if isinstance(usage, dict) else {}
        input_tokens = _int(payload.get("input_tokens")) or 0
        output_tokens = _int(payload.get("output_tokens")) or 0
        total_tokens = _int(payload.get("total_tokens")) or (input_tokens + output_tokens)
        recorded_cost = _float(payload.get("cost_usd"))
        if total_tokens == 0 and recorded_cost in (None, 0.0):
            continue
        provider_name = (provider or "unknown")[:80]
        model_name = (model or "unknown")[:160]
        quote = pricing.quote(provider_name, model_name)
        if recorded_cost is not None:
            cost = recorded_cost
            pricing_status = "recorded_usage"
            estimated = False
        else:
            if input_tokens or output_tokens:
                cost = (
                    input_tokens * quote.input_per_million
                    + output_tokens * quote.output_per_million
                ) / 1_000_000
            else:
                cost = total_tokens / 1_000_000 * quote.blended_per_million
            pricing_status = quote.status
            estimated = not quote.known
        occurred = _utc(completed_at or created_at)
        entries.append(
            CostEntry(
                occurred_at=occurred,
                day=_day_key(occurred),
                user_id=str(row_user) if row_user else None,
                plan=plan or "free",
                provider=provider_name,
                model=model_name,
                tokens=total_tokens,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost,
                feature=_stage_feature(stage_key),
                persona=_persona(resume_settings),
                source="resume_engine_stage",
                row_id=str(row_id),
                pricing_status=pricing_status,
                estimated=estimated,
                unknown_pricing=not quote.known,
            )
        )
    return entries


async def _load_revenue(
    db: AsyncSession,
    *,
    start: datetime,
    end: datetime,
    plan: str | None = None,
) -> tuple[dict[tuple[str, str], float], dict[tuple[str, str], float]]:
    payment_day = func.date_trunc(literal_column("'day'"), models.Payment.created_at)
    refund_day = func.date_trunc(literal_column("'day'"), models.PaymentRefund.created_at)
    payment_stmt = (
        select(
            models.Payment.user_id,
            models.User.subscription_plan,
            payment_day,
            func.coalesce(func.sum(models.Payment.amount), 0),
        )
        .join(models.User, models.User.id == models.Payment.user_id)
        .where(
            models.Payment.created_at >= start,
            models.Payment.created_at <= end,
            models.Payment.currency == "INR",
            models.Payment.status.in_(PAID_PAYMENT_STATUSES),
        )
        .group_by(
            models.Payment.user_id,
            models.User.subscription_plan,
            payment_day,
        )
    )
    refund_stmt = (
        select(
            models.Payment.user_id,
            models.User.subscription_plan,
            refund_day,
            func.coalesce(func.sum(models.PaymentRefund.amount), 0),
        )
        .join(models.Payment, models.Payment.id == models.PaymentRefund.payment_id)
        .join(models.User, models.User.id == models.Payment.user_id)
        .where(
            models.PaymentRefund.created_at >= start,
            models.PaymentRefund.created_at <= end,
            models.PaymentRefund.status.in_(REFUNDED_STATUSES),
            models.Payment.currency == "INR",
        )
        .group_by(
            models.Payment.user_id,
            models.User.subscription_plan,
            refund_day,
        )
    )
    if plan:
        payment_stmt = payment_stmt.where(models.User.subscription_plan == plan)
        refund_stmt = refund_stmt.where(models.User.subscription_plan == plan)

    user_day: dict[tuple[str, str], float] = defaultdict(float)
    plan_day: dict[tuple[str, str], float] = defaultdict(float)
    for user_id, plan_id, day, amount in (await db.execute(payment_stmt)).all():
        if not user_id or not day:
            continue
        key_day = _day_key(day)
        value = int(amount or 0) / 100
        user_day[(key_day, str(user_id))] += value
        plan_day[(key_day, plan_id or "free")] += value
    for user_id, plan_id, day, amount in (await db.execute(refund_stmt)).all():
        if not user_id or not day:
            continue
        key_day = _day_key(day)
        value = int(amount or 0) / 100
        user_day[(key_day, str(user_id))] -= value
        plan_day[(key_day, plan_id or "free")] -= value
    return dict(user_day), dict(plan_day)


def _cap_status(
    *,
    month_cost: float,
    day_cost: float,
    monthly_soft: float,
    monthly_hard: float,
    daily_soft: float,
    daily_hard: float,
    estimated_job_cost: float,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    decision = "allow"
    if monthly_hard > 0 and (month_cost >= monthly_hard or month_cost + estimated_job_cost > monthly_hard):
        reasons.append("monthly_hard_cap_reached")
        decision = "block"
    if daily_hard > 0 and (day_cost >= daily_hard or day_cost + estimated_job_cost > daily_hard):
        reasons.append("daily_hard_cap_reached")
        decision = "block"
    if decision == "block":
        return decision, reasons
    if monthly_soft > 0 and month_cost >= monthly_soft:
        reasons.append("monthly_soft_cap_reached")
        decision = "warn"
    if daily_soft > 0 and day_cost >= daily_soft:
        reasons.append("daily_soft_cap_reached")
        decision = "warn"
    return decision, reasons


def _window(now: datetime) -> dict[str, Any]:
    day_start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
    month_start = day_start.replace(day=1)
    next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return {
        "day": now.date().isoformat(),
        "day_start": day_start.isoformat(),
        "day_resets_at": (day_start + timedelta(days=1)).isoformat(),
        "month": now.strftime("%Y-%m"),
        "month_start": month_start.isoformat(),
        "month_resets_at": next_month.isoformat(),
    }


def _build_spend_monitor(entries: Iterable[CostEntry], now: datetime) -> dict[str, Any]:
    settings_snapshot = settings
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    user_month: dict[str, float] = defaultdict(float)
    user_day: dict[str, float] = defaultdict(float)
    user_plan: dict[str, str] = {}
    user_unknown: dict[str, int] = defaultdict(int)
    month_total = 0.0
    day_total = 0.0
    for entry in entries:
        occurred = _utc(entry.occurred_at)
        if occurred >= month_start:
            month_total += entry.cost_usd
            if entry.user_id:
                user_month[entry.user_id] += entry.cost_usd
                user_plan[entry.user_id] = entry.plan
                if entry.unknown_pricing:
                    user_unknown[entry.user_id] += 1
        if occurred >= day_start:
            day_total += entry.cost_usd
            if entry.user_id:
                user_day[entry.user_id] += entry.cost_usd

    monthly_soft = float(settings_snapshot.ADMIN_AI_MONTHLY_SOFT_CAP_USD or 0)
    monthly_hard = float(settings_snapshot.ADMIN_AI_MONTHLY_SPEND_CAP_USD or 0)
    user_monthly_soft = float(settings_snapshot.ADMIN_AI_USER_MONTHLY_SOFT_CAP_USD or 0)
    user_monthly_hard = float(settings_snapshot.ADMIN_AI_USER_MONTHLY_HARD_CAP_USD or 0)
    user_daily_soft = float(settings_snapshot.ADMIN_AI_USER_DAILY_SOFT_CAP_USD or 0)
    user_daily_hard = float(settings_snapshot.ADMIN_AI_USER_DAILY_HARD_CAP_USD or 0)
    estimated_job_cost = float(settings_snapshot.ADMIN_AI_JOB_ESTIMATE_USD or 0)

    global_decision, global_reasons = _cap_status(
        month_cost=month_total,
        day_cost=day_total,
        monthly_soft=monthly_soft,
        monthly_hard=monthly_hard,
        daily_soft=0,
        daily_hard=0,
        estimated_job_cost=estimated_job_cost,
    )
    global_status = {
        "month_to_date_usd": round(month_total, 6),
        "month_to_date_usd_minor": _minor(month_total),
        "today_usd": round(day_total, 6),
        "today_usd_minor": _minor(day_total),
        "monthly_soft_cap_usd": monthly_soft or None,
        "monthly_hard_cap_usd": monthly_hard or None,
        "decision": global_decision,
        "reasons": global_reasons,
    }

    users: list[dict[str, Any]] = []
    for user_id in sorted(set(user_month) | set(user_day), key=lambda item: -user_month.get(item, 0.0)):
        month_cost = user_month.get(user_id, 0.0)
        day_cost = user_day.get(user_id, 0.0)
        decision, reasons = _cap_status(
            month_cost=month_cost,
            day_cost=day_cost,
            monthly_soft=user_monthly_soft,
            monthly_hard=user_monthly_hard,
            daily_soft=user_daily_soft,
            daily_hard=user_daily_hard,
            estimated_job_cost=estimated_job_cost,
        )
        users.append(
            {
                "user_id": user_id,
                "plan": user_plan.get(user_id, "free"),
                "month_to_date_usd": round(month_cost, 6),
                "month_to_date_usd_minor": _minor(month_cost),
                "today_usd": round(day_cost, 6),
                "today_usd_minor": _minor(day_cost),
                "monthly_soft_cap_usd": user_monthly_soft or None,
                "monthly_hard_cap_usd": user_monthly_hard or None,
                "daily_soft_cap_usd": user_daily_soft or None,
                "daily_hard_cap_usd": user_daily_hard or None,
                "decision": decision,
                "reasons": reasons,
                "unknown_pricing_runs": user_unknown.get(user_id, 0),
                "pricing_complete": user_unknown.get(user_id, 0) == 0,
            }
        )
    hard_users = [row for row in users if row["decision"] == "block"]
    soft_users = [row for row in users if row["decision"] == "warn"]
    return {
        "currency": "USD",
        "minor_unit": "cent",
        "window": _window(now),
        "estimated_job_cost_usd": estimated_job_cost,
        "enforcement": {
            "mode": "new_jobs_only",
            "in_flight_jobs_unaffected": True,
            "auto_suspend": False,
            "requires_actor_and_reason_log": True,
        },
        "global": global_status,
        "users": users,
        "summary": {
            "users_over_hard_cap": len(hard_users),
            "users_over_soft_cap": len(soft_users),
            "users_with_unknown_pricing": sum(1 for row in users if row["unknown_pricing_runs"]),
        },
    }


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _build_outliers(entries: Iterable[CostEntry], now: datetime) -> list[dict[str, Any]]:
    baseline_days = max(1, int(settings.ADMIN_AI_ANOMALY_BASELINE_DAYS or 14))
    min_baseline_days = max(1, min(int(settings.ADMIN_AI_ANOMALY_MIN_BASELINE_DAYS or 5), baseline_days))
    multiplier = float(settings.ADMIN_AI_ANOMALY_MAD_MULTIPLIER or 3.0)
    minimum_usd = float(settings.ADMIN_AI_ANOMALY_MIN_USD or 0.0)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    baseline_start = day_start - timedelta(days=baseline_days)
    today_key = now.date().isoformat()

    daily: dict[str, dict[str, float]] = {
        "user": defaultdict(float),
        "model": defaultdict(float),
        "feature": defaultdict(float),
    }
    labels: dict[str, set[str]] = {"user": set(), "model": set(), "feature": set()}
    for entry in entries:
        occurred = _utc(entry.occurred_at)
        if occurred < baseline_start or occurred > now:
            continue
        day = occurred.date().isoformat()
        keys = {
            "user": entry.user_id or "anonymous",
            "model": f"{entry.provider}/{entry.model}",
            "feature": entry.feature,
        }
        for dimension, key in keys.items():
            daily[dimension][f"{day}\0{key}"] += entry.cost_usd
            labels[dimension].add(key)

    outliers: list[dict[str, Any]] = []
    for dimension in ("user", "model", "feature"):
        for key in labels[dimension]:
            today_cost = daily[dimension].get(f"{today_key}\0{key}", 0.0)
            if today_cost <= 0:
                continue
            history: list[float] = []
            for offset in range(1, baseline_days + 1):
                day = (now.date() - timedelta(days=offset)).isoformat()
                value = daily[dimension].get(f"{day}\0{key}", 0.0)
                if value > 0:
                    history.append(value)
            if len(history) < min_baseline_days:
                continue
            median = _median(history)
            mad = _median([abs(value - median) for value in history])
            threshold = max(
                median + multiplier * 1.4826 * mad,
                median * 2 if median > 0 else 0.0,
                minimum_usd,
            )
            if today_cost <= threshold:
                continue
            outliers.append(
                {
                    "dimension": dimension,
                    "key": key,
                    "user_id": key if dimension == "user" and key != "anonymous" else None,
                    "today_usd": round(today_cost, 6),
                    "today_usd_minor": _minor(today_cost),
                    "baseline_median_usd": round(median, 6),
                    "baseline_median_usd_minor": _minor(median),
                    "baseline_mad_usd": round(mad, 6),
                    "threshold_usd": round(threshold, 6),
                    "threshold_usd_minor": _minor(threshold),
                    "multiple_of_median": round(today_cost / median, 2) if median > 0 else None,
                    "baseline_days": baseline_days,
                    "active_baseline_days": len(history),
                    "method": "median_mad",
                }
            )
    return sorted(outliers, key=lambda row: (-row["today_usd"], row["dimension"], row["key"]))


def _build_reconciliation(
    *,
    entries: list[CostEntry],
    total_cost_usd: float,
    pricing: PricingBook,
    invoice_total_minor: int | None,
    invoice_reference: str | None,
) -> dict[str, Any]:
    by_source: dict[str, _Bucket] = {}
    for entry in entries:
        bucket = by_source.setdefault(entry.source, _Bucket())
        bucket.add(entry)
    sources = [
        {
            "source": source,
            "runs": bucket.runs,
            "tokens": bucket.tokens,
            "cost_usd": round(bucket.cost_usd, 6),
            "cost_usd_minor": _minor(bucket.cost_usd),
            "estimated_runs": bucket.estimated_runs,
            "unknown_pricing_runs": bucket.unknown_pricing_runs,
        }
        for source, bucket in sorted(by_source.items())
    ]
    ledger_minor = _minor(total_cost_usd)
    tolerance = int(settings.ADMIN_AI_INVOICE_TOLERANCE_MINOR or 0)
    sample: dict[str, Any] = {
        "provided": invoice_total_minor is not None,
        "currency": "USD",
        "minor_unit": "cent",
        "total_minor": invoice_total_minor,
        "reference": invoice_reference,
        "variance_minor": None,
        "variance_percent": None,
        "within_tolerance": None,
        "status": "awaiting_sample",
    }
    if invoice_total_minor is not None:
        variance = int(invoice_total_minor) - ledger_minor
        sample.update(
            {
                "variance_minor": variance,
                "variance_usd": round(variance / 100, 2),
                "variance_percent": round(variance / ledger_minor * 100, 2) if ledger_minor else None,
                "within_tolerance": abs(variance) <= tolerance,
                "status": "matched" if abs(variance) <= tolerance else "variance",
            }
        )
    return {
        "contract_version": INVOICE_CONTRACT_VERSION,
        "status": sample["status"],
        "estimated": True,
        "provider_keys_required": False,
        "provider_key_included": False,
        "ledger_currency": "USD",
        "ledger_minor_unit": "cent",
        "ledger_total_usd": round(total_cost_usd, 6),
        "ledger_total_minor": ledger_minor,
        "tolerance_minor": tolerance,
        "tolerance_usd": round(tolerance / 100, 2),
        "sampled_invoice": sample,
        "sources": sources,
        "contract": {
            "required_fields": [
                "provider",
                "period_start",
                "period_end",
                "currency",
                "total_minor",
                "models",
            ],
            "supported_currencies": ["USD"],
            "minor_unit": "cent",
            "provider_credentials_required": False,
            "query_parameter": "invoice_total_minor",
            "note": (
                "Enter a sampled provider invoice total as integer USD cents. "
                "No provider key or credential is read by this endpoint."
            ),
        },
        "notes": [
            "Costs are first-party estimates derived from recorded token usage and the active pricing version.",
            "Unknown models use a visible fallback estimate and are counted separately.",
            "A variance inside the configured tolerance is marked as matched, never silently rounded away.",
        ],
    }


def _build_alerts(
    *,
    entries: list[CostEntry],
    monitor: dict[str, Any],
    outliers: list[dict[str, Any]],
    pricing_version: str,
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    global_caps = monitor["global"]
    hard_cap = global_caps["monthly_hard_cap_usd"]
    month_cost = global_caps["month_to_date_usd"]
    if hard_cap and month_cost >= hard_cap:
        alerts.append(
            {
                "severity": "critical" if month_cost >= hard_cap * 1.1 else "warning",
                "code": "ai_monthly_cap",
                "message": f"Estimated AI spend ${month_cost:.2f} has reached the ${hard_cap:.2f} monthly cap.",
                "value": round(month_cost, 2),
                "threshold": hard_cap,
            }
        )
    soft_cap = global_caps["monthly_soft_cap_usd"]
    if soft_cap and month_cost >= soft_cap and not (hard_cap and month_cost >= hard_cap):
        alerts.append(
            {
                "severity": "warning",
                "code": "ai_monthly_soft_cap",
                "message": f"Estimated AI spend ${month_cost:.2f} has reached the ${soft_cap:.2f} soft monthly cap.",
                "value": round(month_cost, 2),
                "threshold": soft_cap,
            }
        )

    for user in monitor["users"]:
        if user["decision"] != "block":
            continue
        for reason in user["reasons"]:
            alerts.append(
                {
                    "severity": "critical",
                    "code": "ai_user_hard_cap",
                    "message": (
                        f"User {user['user_id'][:8]}… hit the {reason.replace('_', ' ')} "
                        f"(${user['month_to_date_usd']:.2f} month, ${user['today_usd']:.2f} today)."
                    ),
                    "value": user["month_to_date_usd"] if "monthly" in reason else user["today_usd"],
                    "threshold": user["monthly_hard_cap_usd"] if "monthly" in reason else user["daily_hard_cap_usd"],
                    "user_id": user["user_id"],
                    "reason": reason,
                }
            )

    for outlier in outliers[:20]:
        alerts.append(
            {
                "severity": "warning",
                "code": f"ai_{outlier['dimension']}_daily_anomaly",
                "message": (
                    f"{outlier['dimension'].title()} {outlier['key']} spent ${outlier['today_usd']:.2f} today, "
                    f"above the rolling median threshold of ${outlier['threshold_usd']:.2f}."
                ),
                "value": outlier["today_usd"],
                "threshold": outlier["threshold_usd"],
                "user_id": outlier.get("user_id"),
                "dimension": outlier["dimension"],
            }
        )

    unknown_runs = sum(1 for entry in entries if entry.unknown_pricing)
    if unknown_runs:
        alerts.append(
            {
                "severity": "warning",
                "code": "ai_unknown_pricing",
                "message": (
                    f"{unknown_runs} run(s) use a provider/model without configured pricing; "
                    "they are shown with a visible fallback estimate."
                ),
                "value": unknown_runs,
                "threshold": 0,
                "pricing_version": pricing_version,
            }
        )

    user_threshold = float(settings.ADMIN_AI_USER_DAILY_COST_ALERT_USD or 0)
    if user_threshold > 0:
        for user in monitor["users"][:10]:
            if user["today_usd"] >= user_threshold:
                alerts.append(
                    {
                        "severity": "warning",
                        "code": "ai_user_daily_outlier",
                        "message": f"User {user['user_id'][:8]}… estimated ${user['today_usd']:.2f} today.",
                        "value": round(user["today_usd"], 2),
                        "threshold": user_threshold,
                        "user_id": user["user_id"],
                        "date": monitor["window"]["day"],
                    }
                )
    return alerts


def _signal(
    *,
    kind: str,
    severity: str,
    title: str,
    dedupe_key: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "kind": kind,
        "severity": severity,
        "owner": "Growth",
        "title": title,
        "dedupe_key": dedupe_key,
        "payload": payload,
        "runbook_url": RUNBOOK_URL,
    }


async def collect_spend_signals(db: AsyncSession, now: datetime) -> list[dict[str, Any]]:
    """Return aggregate spend signals for the existing admin alert evaluator.

    Payloads intentionally contain only counts, thresholds, and window labels.
    Account identifiers stay in the Growth tab so the alert strip never becomes
    a per-user surveillance surface.
    """
    now = _utc(now)
    baseline_days = max(1, int(settings.ADMIN_AI_ANOMALY_BASELINE_DAYS or 14))
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start = min(month_start, now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=baseline_days))
    entries = await _load_cost_entries(db, start=start, end=now)
    monitor = _build_spend_monitor(entries, now)
    outliers = _build_outliers(entries, now)
    pricing = _pricing_book()
    signals: list[dict[str, Any]] = []
    window = monitor["window"]

    hard = monitor["global"]["monthly_hard_cap_usd"]
    month_cost = monitor["global"]["month_to_date_usd"]
    if hard and month_cost >= hard:
        signals.append(
            _signal(
                kind="spend.monthly_cap",
                severity="critical" if month_cost >= hard * 1.1 else "medium",
                title="Estimated AI spend reached the monthly hard cap",
                dedupe_key=f"spend.monthly_cap:{window['month']}",
                payload={
                    "value_usd": round(month_cost, 2),
                    "threshold_usd": hard,
                    "month": window["month"],
                    "pricing_version": pricing.version,
                    "unknown_pricing_runs": sum(1 for entry in entries if entry.unknown_pricing),
                },
            )
        )
    soft = monitor["global"]["monthly_soft_cap_usd"]
    if soft and month_cost >= soft and not (hard and month_cost >= hard):
        signals.append(
            _signal(
                kind="spend.monthly_soft_cap",
                severity="medium",
                title="Estimated AI spend reached the monthly soft cap",
                dedupe_key=f"spend.monthly_soft_cap:{window['month']}",
                payload={
                    "value_usd": round(month_cost, 2),
                    "threshold_usd": soft,
                    "month": window["month"],
                    "pricing_version": pricing.version,
                },
            )
        )

    hard_users = [row for row in monitor["users"] if row["decision"] == "block"]
    soft_users = [row for row in monitor["users"] if row["decision"] == "warn"]
    if hard_users or soft_users:
        signals.append(
            _signal(
                kind="spend.user_caps",
                severity="high" if hard_users else "medium",
                title="AI spend caps reached by one or more users",
                dedupe_key=f"spend.user_caps:{window['month']}",
                payload={
                    "hard_cap_users": len(hard_users),
                    "soft_cap_users": len(soft_users),
                    "month": window["month"],
                    "pricing_version": pricing.version,
                },
            )
        )

    if outliers:
        dimensions: dict[str, int] = defaultdict(int)
        for outlier in outliers:
            dimensions[outlier["dimension"]] += 1
        signals.append(
            _signal(
                kind="spend.anomaly",
                severity="high" if any(row["today_usd"] >= 10 for row in outliers) else "medium",
                title="AI spend anomaly above the rolling baseline",
                dedupe_key=f"spend.anomaly:{window['day']}",
                payload={
                    "users": dimensions.get("user", 0),
                    "models": dimensions.get("model", 0),
                    "features": dimensions.get("feature", 0),
                    "largest_today_usd": round(outliers[0]["today_usd"], 2),
                    "day": window["day"],
                    "pricing_version": pricing.version,
                },
            )
        )
    return signals


def _caps_configured() -> bool:
    return any(
        float(value or 0) > 0
        for value in (
            settings.ADMIN_AI_USER_MONTHLY_SOFT_CAP_USD,
            settings.ADMIN_AI_USER_MONTHLY_HARD_CAP_USD,
            settings.ADMIN_AI_USER_DAILY_SOFT_CAP_USD,
            settings.ADMIN_AI_USER_DAILY_HARD_CAP_USD,
        )
    )


async def check_user_spend_guard(
    db: AsyncSession,
    *,
    user_id: str,
    actor: str,
    reason: str,
    job_type: str,
    now: datetime | None = None,
    estimated_job_cost_usd: float | None = None,
) -> dict[str, Any]:
    """Check per-user soft/hard caps before admitting new AI work.

    This function never mutates the user, job, or ledger. A hard-cap decision
    rejects only the new request; it cannot cancel or fail work already in
    flight. All decisions are logged with the actor and reason.
    """
    now = _utc(now)
    if not _caps_configured():
        return {
            "allowed": True,
            "decision": "allow",
            "enforced": False,
            "reasons": [],
            "actor": actor,
            "reason": reason,
            "job_type": job_type,
        }
    estimated = (
        float(estimated_job_cost_usd)
        if estimated_job_cost_usd is not None
        else float(settings.ADMIN_AI_JOB_ESTIMATE_USD or 0)
    )
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    entries = await _load_cost_entries(db, start=month_start, end=now, user_id=user_id)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_cost = sum(entry.cost_usd for entry in entries)
    day_cost = sum(entry.cost_usd for entry in entries if _utc(entry.occurred_at) >= day_start)
    unknown_runs = sum(1 for entry in entries if entry.unknown_pricing)
    decision, reasons = _cap_status(
        month_cost=month_cost,
        day_cost=day_cost,
        monthly_soft=float(settings.ADMIN_AI_USER_MONTHLY_SOFT_CAP_USD or 0),
        monthly_hard=float(settings.ADMIN_AI_USER_MONTHLY_HARD_CAP_USD or 0),
        daily_soft=float(settings.ADMIN_AI_USER_DAILY_SOFT_CAP_USD or 0),
        daily_hard=float(settings.ADMIN_AI_USER_DAILY_HARD_CAP_USD or 0),
        estimated_job_cost=estimated,
    )
    result = {
        "allowed": decision != "block",
        "decision": decision,
        "enforced": True,
        "reasons": reasons,
        "actor": actor,
        "reason": reason,
        "job_type": job_type,
        "user_id": user_id,
        "month_to_date_usd": round(month_cost, 6),
        "month_to_date_usd_minor": _minor(month_cost),
        "today_usd": round(day_cost, 6),
        "today_usd_minor": _minor(day_cost),
        "estimated_job_cost_usd": estimated,
        "monthly_soft_cap_usd": float(settings.ADMIN_AI_USER_MONTHLY_SOFT_CAP_USD or 0) or None,
        "monthly_hard_cap_usd": float(settings.ADMIN_AI_USER_MONTHLY_HARD_CAP_USD or 0) or None,
        "daily_soft_cap_usd": float(settings.ADMIN_AI_USER_DAILY_SOFT_CAP_USD or 0) or None,
        "daily_hard_cap_usd": float(settings.ADMIN_AI_USER_DAILY_HARD_CAP_USD or 0) or None,
        "unknown_pricing_runs": unknown_runs,
        "pricing_complete": unknown_runs == 0,
        "window": _window(now),
        "in_flight_jobs_affected": False,
        "auto_suspend": False,
    }
    logger.info(
        "AI spend cap decision actor=%s reason=%s job_type=%s user=%s decision=%s reasons=%s "
        "month_usd=%.4f day_usd=%.4f unknown_pricing_runs=%s",
        sanitize_for_log(actor),
        sanitize_for_log(reason),
        sanitize_for_log(job_type),
        sanitize_for_log(user_id),
        decision,
        ",".join(reasons) or "within_caps",
        month_cost,
        day_cost,
        unknown_runs,
    )
    return result


async def ai_cost_snapshot(
    db: AsyncSession,
    *,
    days: int = 30,
    plan: str | None = None,
    feature: str | None = None,
    persona: str | None = None,
    invoice_total_minor: int | None = None,
    invoice_reference: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    days = max(1, min(days, 365))
    now = _utc(now)
    plan = (plan or "").strip().lower() or None
    feature = (feature or "").strip().lower() or None
    persona = (persona or "").strip().lower() or None
    display_start = now - timedelta(days=days)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    baseline_days = max(1, int(settings.ADMIN_AI_ANOMALY_BASELINE_DAYS or 14))
    baseline_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=baseline_days)
    load_start = min(display_start, month_start, baseline_start)
    pricing = _pricing_book()

    all_entries = await _load_cost_entries(db, start=load_start, end=now)
    plan_entries = [
        entry
        for entry in all_entries
        if entry.occurred_at >= display_start and (not plan or entry.plan == plan)
    ]
    display_entries = [
        entry
        for entry in plan_entries
        if (not feature or entry.feature == feature) and (not persona or entry.persona == persona)
    ]
    revenue_user_day, revenue_plan_day = await _load_revenue(
        db, start=load_start, end=now, plan=plan
    )

    plan_cost_by_user_day: dict[tuple[str, str], float] = defaultdict(float)
    user_plan: dict[str, str] = {}
    for entry in plan_entries:
        if entry.user_id:
            plan_cost_by_user_day[(entry.day, entry.user_id)] += entry.cost_usd
            user_plan[entry.user_id] = entry.plan

    filtered_revenue = bool(feature or persona)

    def allocated_revenue(entry: CostEntry) -> float:
        if not entry.user_id or not filtered_revenue:
            return 0.0
        total = plan_cost_by_user_day.get((entry.day, entry.user_id), 0.0)
        if total <= 0:
            return 0.0
        return revenue_user_day.get((entry.day, entry.user_id), 0.0) * entry.cost_usd / total

    by_model: dict[tuple[str, str], _Bucket] = {}
    by_plan: dict[str, _Bucket] = {}
    by_user: dict[str, _Bucket] = {}
    by_feature: dict[str, _Bucket] = {}
    by_persona: dict[str, _Bucket] = {}
    by_day: dict[str, _Bucket] = {}
    daily_plan: dict[tuple[str, str], _Bucket] = {}
    daily_user: dict[tuple[str, str], _Bucket] = {}
    daily_feature: dict[tuple[str, str], _Bucket] = {}
    daily_persona: dict[tuple[str, str], _Bucket] = {}
    daily_model: dict[tuple[str, str], _Bucket] = {}
    plan_revenue_day: dict[tuple[str, str], float] = {}
    user_revenue_day: dict[tuple[str, str], float] = {}

    display_day = display_start.date().isoformat()
    if not filtered_revenue:
        for (day, plan_id), value in revenue_plan_day.items():
            if day >= display_day:
                plan_revenue_day[(day, plan_id)] = value
        for (day, user_id), value in revenue_user_day.items():
            if day >= display_day:
                user_revenue_day[(day, user_id)] = value
    else:
        for entry in display_entries:
            allocated = allocated_revenue(entry)
            if allocated:
                plan_revenue_day[(entry.day, entry.plan)] = plan_revenue_day.get((entry.day, entry.plan), 0.0) + allocated
                if entry.user_id:
                    user_revenue_day[(entry.day, entry.user_id)] = (
                        user_revenue_day.get((entry.day, entry.user_id), 0.0) + allocated
                    )

    total_cost = 0.0
    total_tokens = 0
    total_runs = 0
    estimated_runs = 0
    unknown_runs = 0
    pricing_gaps: dict[tuple[str, str], _Bucket] = {}
    for entry in display_entries:
        total_cost += entry.cost_usd
        total_tokens += entry.tokens
        total_runs += 1
        if entry.estimated:
            estimated_runs += 1
        if entry.unknown_pricing:
            unknown_runs += 1
            pricing_gaps.setdefault((entry.provider, entry.model), _Bucket()).add(entry)

        model_key = (entry.provider, entry.model)
        by_model.setdefault(model_key, _Bucket()).add(entry)
        by_plan.setdefault(entry.plan, _Bucket()).add(entry)
        by_day.setdefault(entry.day, _Bucket()).add(entry)
        daily_plan.setdefault((entry.day, entry.plan), _Bucket()).add(entry)
        daily_feature.setdefault((entry.day, entry.feature), _Bucket()).add(entry)
        daily_persona.setdefault((entry.day, entry.persona), _Bucket()).add(entry)
        daily_model.setdefault((entry.day, f"{entry.provider}/{entry.model}"), _Bucket()).add(entry)
        if entry.user_id:
            by_user.setdefault(entry.user_id, _Bucket()).add(entry)
            daily_user.setdefault((entry.day, entry.user_id), _Bucket()).add(entry)
        feature_bucket = by_feature.setdefault(entry.feature, _Bucket())
        feature_bucket.add(entry)
        persona_bucket = by_persona.setdefault(entry.persona, _Bucket())
        persona_bucket.add(entry)
        allocated = allocated_revenue(entry)
        if allocated:
            feature_bucket.revenue_inr += allocated
            persona_bucket.revenue_inr += allocated
            daily_feature[(entry.day, entry.feature)].revenue_inr += allocated
            daily_persona[(entry.day, entry.persona)].revenue_inr += allocated

    # Plans with revenue but no displayed cost still need a margin row.
    for _day, plan_id in plan_revenue_day:
        by_plan.setdefault(plan_id, _Bucket())
    for (day, plan_id), value in plan_revenue_day.items():
        if plan_id in by_plan:
            by_plan[plan_id].revenue_inr += value
        else:
            by_plan[plan_id] = _Bucket(revenue_inr=value)
    for (day, user_id), value in user_revenue_day.items():
        if user_id in by_user:
            by_user[user_id].revenue_inr += value
        else:
            by_user[user_id] = _Bucket(revenue_inr=value)

    def _row_from_bucket(label: str, bucket: _Bucket, key_name: str = "label") -> dict[str, Any]:
        return _bucket_row(label, bucket, key_name=key_name)

    def _with_financials(row: dict[str, Any], bucket: _Bucket, revenue: float) -> dict[str, Any]:
        cost_usd = round(bucket.cost_usd, 6)
        revenue = round(revenue, 6)
        cost_inr = cost_usd * float(settings.ADMIN_AI_COST_USD_INR_RATE)
        margin = revenue - cost_inr
        row.update(
            {
                "cost_usd": cost_usd,
                "cost_usd_minor": _minor(cost_usd),
                "ai_cost_inr": round(cost_inr, 2),
                "ai_cost_inr_minor": _minor(cost_inr),
                "revenue_inr": round(revenue, 2),
                "revenue_inr_minor": _minor(revenue),
                "gross_margin_inr": round(margin, 2),
                "gross_margin_inr_minor": _minor(margin),
                "estimated": bucket.estimated_runs > 0,
            }
        )
        return row

    total_cost_usd = round(total_cost, 2)
    inr_rate = float(settings.ADMIN_AI_COST_USD_INR_RATE)
    total_cost_inr = round(total_cost_usd * inr_rate, 2)
    display_revenue = sum(plan_revenue_day.values()) if not filtered_revenue else sum(user_revenue_day.values())
    display_margin = display_revenue - total_cost_inr

    by_plan_rows = []
    for plan_id, bucket in by_plan.items():
        row = _with_financials(_row_from_bucket(plan_id, bucket, key_name="plan"), bucket, bucket.revenue_inr)
        row["revenue_attribution"] = "allocated_by_ai_cost" if filtered_revenue else "recorded_payments"
        by_plan_rows.append(row)
    by_plan_rows.sort(key=lambda item: -item["cost_usd"])

    by_user_rows = []
    for user_id, bucket in by_user.items():
        row = _with_financials(_row_from_bucket(user_id, bucket, key_name="user_id"), bucket, bucket.revenue_inr)
        row["plan"] = user_plan.get(user_id, "free")
        row["revenue_attribution"] = "allocated_by_ai_cost" if filtered_revenue else "recorded_payments"
        by_user_rows.append(row)
    by_user_rows.sort(key=lambda item: -item["cost_usd"])
    top_users = by_user_rows[:100]

    by_feature_rows = []
    for feature_name, bucket in by_feature.items():
        row = _with_financials(_row_from_bucket(feature_name, bucket, key_name="feature"), bucket, bucket.revenue_inr)
        row["revenue_attribution"] = "proportional_to_ai_cost" if bucket.revenue_inr else "unattributed"
        by_feature_rows.append(row)
    by_feature_rows.sort(key=lambda item: -item["cost_usd"])

    by_persona_rows = []
    for persona_name, bucket in by_persona.items():
        row = _with_financials(_row_from_bucket(persona_name, bucket, key_name="persona"), bucket, bucket.revenue_inr)
        row["revenue_attribution"] = "proportional_to_ai_cost" if bucket.revenue_inr else "unknown"
        by_persona_rows.append(row)
    by_persona_rows.sort(key=lambda item: -item["cost_usd"])

    by_day_rows = []
    for day, bucket in sorted(by_day.items()):
        revenue = sum(value for (revenue_day, _key), value in plan_revenue_day.items() if revenue_day == day)
        row = _with_financials(_row_from_bucket(day, bucket, key_name="date"), bucket, revenue)
        by_day_rows.append(row)
    by_day_rows.sort(key=lambda item: item["date"])

    def _daily_rows(source: dict[tuple[str, str], _Bucket], key_name: str) -> list[dict[str, Any]]:
        rows = []
        for (day, key), bucket in sorted(source.items()):
            if key_name == "plan":
                revenue = plan_revenue_day.get((day, key), 0.0)
            elif key_name == "user_id":
                revenue = user_revenue_day.get((day, key), 0.0)
            else:
                revenue = bucket.revenue_inr
            row = _with_financials(_row_from_bucket(key, bucket, key_name=key_name), bucket, revenue)
            row["date"] = day
            rows.append(row)
        return rows

    margin_by_plan = [
        {
            "plan": row["plan"],
            "revenue_inr": row["revenue_inr"],
            "revenue_inr_minor": row["revenue_inr_minor"],
            "ai_cost_inr": row["ai_cost_inr"],
            "ai_cost_inr_minor": row["ai_cost_inr_minor"],
            "ai_cost_usd": row["cost_usd"],
            "ai_cost_usd_minor": row["cost_usd_minor"],
            "gross_margin_inr": row["gross_margin_inr"],
            "gross_margin_inr_minor": row["gross_margin_inr_minor"],
            "estimated": row["estimated"],
        }
        for row in by_plan_rows
    ]
    margin_by_plan.sort(key=lambda item: -item["gross_margin_inr"])

    monitor = _build_spend_monitor(all_entries, now)
    outliers = _build_outliers(all_entries, now)
    alerts = _build_alerts(
        entries=all_entries,
        monitor=monitor,
        outliers=outliers,
        pricing_version=pricing.version,
    )
    reconciliation = _build_reconciliation(
        entries=display_entries,
        total_cost_usd=total_cost_usd,
        pricing=pricing,
        invoice_total_minor=invoice_total_minor,
        invoice_reference=invoice_reference,
    )

    unknown_pricing_rows = [
        {
            "provider": provider,
            "model": model,
            **{
                key: value
                for key, value in _bucket_row(f"{provider}/{model}", bucket, key_name="label").items()
                if key != "label"
            },
            "pricing_status": _model_pricing_status(bucket),
            "estimated": bucket.estimated_runs > 0,
            "unknown_pricing": True,
        }
        for (provider, model), bucket in sorted(pricing_gaps.items())
    ]

    daily_payload = {
        "by_plan": _daily_rows(daily_plan, "plan"),
        "by_user": _daily_rows(daily_user, "user_id"),
        "by_feature": _daily_rows(daily_feature, "feature"),
        "by_persona": _daily_rows(daily_persona, "persona"),
        "by_model": _daily_rows(daily_model, "label"),
    }

    return {
        "period_days": days,
        "generated_at": now.isoformat(),
        "filters": {"plan": plan, "feature": feature, "persona": persona},
        "estimated": True,
        "price_note": (
            "Costs are estimates from recorded token usage. Legacy optimization rows use a blended "
            "input/output rate; resume-engine stage rows prefer provider-recorded cost_usd. Rows with "
            "fallback_price=true or pricing_status='fallback_estimate' use the visible fallback price."
        ),
        "cost_currency": "USD",
        "cost_minor_unit": "cent",
        "revenue_currency": "INR",
        "revenue_minor_unit": "paise",
        "pricing_version": pricing.version,
        "pricing": pricing.public(),
        "usd_inr_rate": inr_rate,
        "monthly_spend_cap_usd": float(settings.ADMIN_AI_MONTHLY_SPEND_CAP_USD or 0) or None,
        "monthly_soft_spend_cap_usd": float(settings.ADMIN_AI_MONTHLY_SOFT_CAP_USD or 0) or None,
        "total_tokens": total_tokens,
        "total_cost_usd": total_cost_usd,
        "total_cost_usd_minor": _minor(total_cost_usd),
        "total_cost_inr": total_cost_inr,
        "total_cost_inr_minor": _minor(total_cost_inr),
        "total_revenue_inr": round(display_revenue, 2),
        "total_revenue_inr_minor": _minor(display_revenue),
        "gross_margin_inr": round(display_margin, 2),
        "gross_margin_inr_minor": _minor(display_margin),
        "optimizations": total_runs,
        "estimated_runs": estimated_runs,
        "unknown_pricing_runs": unknown_runs,
        "pricing_complete": unknown_runs == 0,
        "by_model": sorted(
            [
                {
                    "provider": provider,
                    "model": model,
                    "runs": bucket.runs,
                    "tokens": bucket.tokens,
                    "cost_usd": round(bucket.cost_usd, 6),
                    "cost_usd_minor": _minor(bucket.cost_usd),
                    "fallback_price": bucket.unknown_pricing_runs > 0,
                    "pricing_status": _model_pricing_status(bucket),
                    "estimated": bucket.estimated_runs > 0,
                    "estimated_runs": bucket.estimated_runs,
                    "unknown_pricing_runs": bucket.unknown_pricing_runs,
                    "unknown_pricing": bucket.unknown_pricing_runs > 0,
                }
                for (provider, model), bucket in by_model.items()
            ],
            key=lambda item: -item["cost_usd"],
        ),
        "unknown_pricing": {
            "runs": unknown_runs,
            "tokens": sum(row["tokens"] for row in unknown_pricing_rows),
            "cost_usd": round(sum(row["cost_usd"] for row in unknown_pricing_rows), 6),
            "cost_usd_minor": sum(row["cost_usd_minor"] for row in unknown_pricing_rows),
            "models": unknown_pricing_rows,
        },
        "by_plan": by_plan_rows,
        "by_user": by_user_rows,
        "by_feature": by_feature_rows,
        "by_persona": by_persona_rows,
        "by_day": by_day_rows,
        "daily": daily_payload,
        "daily_by_plan": daily_payload["by_plan"],
        "daily_by_user": daily_payload["by_user"],
        "daily_by_feature": daily_payload["by_feature"],
        "daily_by_persona": daily_payload["by_persona"],
        "daily_by_model": daily_payload["by_model"],
        "top_users": top_users,
        "margin_by_plan": margin_by_plan,
        "caps": monitor,
        "outliers": outliers,
        "alerts": alerts,
        "reconciliation": reconciliation,
        "invoice_reconciliation": reconciliation,
    }


admin_ai_cost_service = object()
