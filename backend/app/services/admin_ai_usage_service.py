"""Aggregate-only admin AI usage breakdown.

The rollup intentionally unions the two first-party AI ledgers:

* ``optimizations`` for legacy per-run usage and latency, and
* ``resume_optimization_stages`` for durable resume-engine stage usage, status,
  latency, and the run's credential source.

Only provider/model identifiers, token counts, timings, subscription plan, and
the resume's saved persona metadata are read.  Prompts, job descriptions,
resume/LaTeX content, API keys, per-account rows, and credential fingerprints
never leave this module.

Persona is not persisted on legacy optimization rows.  For those rows we use the
resume's last saved first-party persona metadata and otherwise report
``unknown``.  Semantic resume-engine runs additionally persist the persona that
was submitted with the job under ``context_payload.direction.persona``; that
value wins when present.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..database import models
from .admin_ai_cost_service import _int, _stage_feature, _utc
from .admin_ai_cost_service import _persona as _resume_persona

MIN_GROUP_SIZE = 5
SUCCESS_STATUSES = frozenset({"completed"})
ERROR_STATUSES = frozenset({"failed", "ambiguous", "cancelled"})
RUN_TERMINAL_STATUSES = frozenset({"completed", "partial", "failed", "cancelled"})

_HEX_HASH = re.compile(r"^[0-9a-f]{64}$")
_PLATFORM_SCOPE_PREFIXES = ("platform", "managed", "system", "server")
_BYOK_SCOPE_PREFIXES = ("byok", "user", "custom", "own")


def _clean(value: Any, limit: int, default: str = "unknown") -> str:
    if not isinstance(value, str):
        return default
    normalized = value.strip().lower()
    if not normalized:
        return default
    return normalized[:limit]


def _filter_value(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized[:limit] if normalized else None


def _event_persona(run_persona: Any, resume_settings: Any) -> str:
    if run_persona:
        persona = _resume_persona({"last_persona": run_persona})
        if persona != "unknown":
            return persona
    return _resume_persona(resume_settings)


def _platform_credential_scopes() -> set[str]:
    """Fingerprints of configured platform keys, never the keys themselves.

    Resume-engine runs persist only a keyed fingerprint.  Comparing it to the
    platform keys (without reading any stored user key) lets us label the source
    as platform versus BYOK without exposing the fingerprint.
    """
    try:
        from .resume_engine.credential_scope import credential_scope
    except Exception:  # pragma: no cover - configuration failure falls back to unknown
        return set()

    scopes: set[str] = set()
    for key in (
        settings.OPENAI_API_KEY,
        settings.ANTHROPIC_API_KEY,
        settings.OPENROUTER_API_KEY,
        settings.GEMINI_API_KEY,
    ):
        if isinstance(key, str) and key:
            try:
                scopes.add(credential_scope(key))
            except Exception:
                continue
    return scopes


def _credential_source(scope: Any, platform_scopes: Iterable[str]) -> str:
    if not isinstance(scope, str) or not scope.strip():
        return "unknown"
    normalized = scope.strip().lower()
    if normalized.startswith(_PLATFORM_SCOPE_PREFIXES):
        return "platform"
    if normalized.startswith(_BYOK_SCOPE_PREFIXES):
        return "byok"
    if normalized in platform_scopes:
        return "platform"
    # Durable resume-engine scopes are keyed HMAC fingerprints.  Anything that is
    # a fingerprint but not the platform key must have come from a user key.
    if _HEX_HASH.match(normalized):
        return "byok"
    return "unknown"


def _stage_outcome(status: Any) -> str:
    normalized = _clean(status, 32)
    if normalized in SUCCESS_STATUSES:
        return "success"
    if normalized in ERROR_STATUSES:
        return "error"
    return "pending"


def _latency_ms(started: Any, finished: Any) -> float | None:
    if not isinstance(started, datetime) or not isinstance(finished, datetime):
        return None
    started = _utc(started)
    finished = _utc(finished)
    seconds = (finished - started).total_seconds()
    if not math.isfinite(seconds) or seconds < 0:
        return None
    return round(seconds * 1000, 3)


def _legacy_latency_ms(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0:
        return None
    return round(seconds * 1000, 3)


def _stage_tokens(usage: Any) -> int:
    payload = usage if isinstance(usage, dict) else {}
    input_tokens = _int(payload.get("input_tokens")) or 0
    output_tokens = _int(payload.get("output_tokens")) or 0
    total = _int(payload.get("total_tokens")) or (input_tokens + output_tokens)
    return max(0, int(total))


def _percentile(values: list[float], percentile: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percentile / 100
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


def _latency_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "p50_ms": None,
            "p95_ms": None,
            "average_ms": None,
            "samples": 0,
        }
    p50 = _percentile(values, 50)
    p95 = _percentile(values, 95)
    average = sum(values) / len(values)
    return {
        "p50_ms": round(p50, 3) if p50 is not None else None,
        "p95_ms": round(p95, 3) if p95 is not None else None,
        "average_ms": round(average, 3),
        "samples": len(values),
    }


@dataclass(frozen=True)
class UsageEvent:
    source: str
    occurred_at: datetime
    user_id: str | None
    plan: str
    feature: str
    provider: str
    model: str
    persona: str
    credential_source: str
    outcome: str
    tokens: int
    latency_ms: float | None


@dataclass
class _Aggregate:
    runs: int = 0
    successes: int = 0
    errors: int = 0
    pending: int = 0
    tokens: int = 0
    users: set[str] = field(default_factory=set)
    latency: list[float] = field(default_factory=list)
    credential_sources: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def add(self, event: UsageEvent) -> None:
        self.runs += 1
        if event.outcome == "success":
            self.successes += 1
        elif event.outcome == "error":
            self.errors += 1
        else:
            self.pending += 1
        self.tokens += max(0, int(event.tokens))
        if event.user_id:
            self.users.add(event.user_id)
        if event.latency_ms is not None:
            self.latency.append(event.latency_ms)
        self.credential_sources[event.credential_source] += 1


def _metrics(bucket: _Aggregate) -> dict[str, Any]:
    latency = _latency_summary(bucket.latency)
    return {
        "runs": bucket.runs,
        "users": len(bucket.users),
        "successes": bucket.successes,
        "errors": bucket.errors,
        "pending": bucket.pending,
        "success_rate": round(bucket.successes / bucket.runs * 100, 2) if bucket.runs else 0.0,
        "error_rate": round(bucket.errors / bucket.runs * 100, 2) if bucket.runs else 0.0,
        "tokens": bucket.tokens,
        "latency_p50_ms": latency["p50_ms"],
        "latency_p95_ms": latency["p95_ms"],
        "latency_avg_ms": latency["average_ms"],
        "latency_samples": latency["samples"],
        "credential_sources": {
            key: bucket.credential_sources[key]
            for key in ("byok", "platform", "unknown")
            if bucket.credential_sources.get(key)
        },
    }


def _row(label: str, bucket: _Aggregate, key: str, value: str) -> dict[str, Any]:
    return {
        "label": label,
        key: value,
        **_metrics(bucket),
    }


async def _load_optimization_events(
    db: AsyncSession,
    *,
    start: datetime,
    end: datetime,
    plan: str | None,
    provider: str | None,
    model: str | None,
) -> list[UsageEvent]:
    statement = (
        select(
            models.Optimization.id,
            models.Optimization.user_id,
            models.Optimization.provider,
            models.Optimization.model,
            models.Optimization.tokens_used,
            models.Optimization.optimization_time,
            models.Optimization.created_at,
            models.User.subscription_plan,
            models.Resume.resume_settings,
        )
        .outerjoin(models.User, models.User.id == models.Optimization.user_id)
        .outerjoin(models.Resume, models.Resume.id == models.Optimization.resume_id)
        .where(
            models.Optimization.created_at >= start,
            models.Optimization.created_at < end,
            models.Optimization.is_auto_save.is_not(True),
            models.Optimization.is_checkpoint.is_not(True),
            func.lower(func.coalesce(models.Optimization.provider, "")) != "checkpoint",
        )
    )
    if plan:
        statement = statement.where(func.lower(models.User.subscription_plan) == plan)
    if provider:
        statement = statement.where(func.lower(models.Optimization.provider) == provider)
    if model:
        statement = statement.where(func.lower(models.Optimization.model) == model)

    events: list[UsageEvent] = []
    for (
        _row_id,
        user_id,
        row_provider,
        row_model,
        tokens,
        optimization_time,
        created_at,
        plan_id,
        resume_settings,
    ) in (await db.execute(statement)).all():
        occurred = _utc(created_at)
        token_count = int(tokens or 0) if isinstance(tokens, int) and not isinstance(tokens, bool) else 0
        events.append(
            UsageEvent(
                source="optimizations",
                occurred_at=occurred,
                user_id=str(user_id) if user_id else None,
                plan=_clean(plan_id, 50, "free"),
                feature="resume_optimization",
                provider=_clean(row_provider, 80),
                model=_clean(row_model, 160),
                persona=_resume_persona(resume_settings),
                credential_source="unknown",
                outcome="success",
                tokens=max(0, token_count),
                latency_ms=_legacy_latency_ms(optimization_time),
            )
        )
    return events


async def _load_stage_events(
    db: AsyncSession,
    *,
    start: datetime,
    end: datetime,
    plan: str | None,
    provider: str | None,
    model: str | None,
) -> list[UsageEvent]:
    occurred_at = func.coalesce(
        models.ResumeOptimizationStage.completed_at,
        models.ResumeOptimizationStage.created_at,
    )
    statement = (
        select(
            models.ResumeOptimizationStage.id,
            models.ResumeOptimizationRun.id,
            models.ResumeOptimizationRun.user_id,
            models.ResumeOptimizationRun.provider,
            models.ResumeOptimizationRun.model,
            models.ResumeOptimizationRun.credential_scope,
            models.ResumeOptimizationRun.context_payload["direction"]["persona"].astext,
            models.ResumeOptimizationStage.stage_key,
            models.ResumeOptimizationStage.status,
            models.ResumeOptimizationStage.usage,
            models.ResumeOptimizationStage.created_at,
            models.ResumeOptimizationStage.completed_at,
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
            occurred_at >= start,
            occurred_at < end,
        )
    )
    if plan:
        statement = statement.where(func.lower(models.User.subscription_plan) == plan)
    if provider:
        statement = statement.where(func.lower(models.ResumeOptimizationRun.provider) == provider)
    if model:
        statement = statement.where(func.lower(models.ResumeOptimizationRun.model) == model)

    platform_scopes = _platform_credential_scopes()
    events: list[UsageEvent] = []
    for (
        _stage_id,
        run_id,
        user_id,
        run_provider,
        run_model,
        credential_scope,
        run_persona,
        stage_key,
        status,
        usage,
        stage_created_at,
        stage_completed_at,
        plan_id,
        resume_settings,
    ) in (await db.execute(statement)).all():
        occurred = _utc(stage_completed_at or stage_created_at)
        persona = _event_persona(run_persona, resume_settings)
        events.append(
            UsageEvent(
                source="resume_optimization_stages",
                occurred_at=occurred,
                user_id=str(user_id) if user_id else None,
                plan=_clean(plan_id, 50, "free"),
                feature=_stage_feature(stage_key),
                provider=_clean(run_provider, 80),
                model=_clean(run_model, 160),
                persona=persona,
                credential_source=_credential_source(credential_scope, platform_scopes),
                outcome=_stage_outcome(status),
                tokens=_stage_tokens(usage),
                latency_ms=_latency_ms(stage_created_at, stage_completed_at),
            )
        )
    return events


async def _run_reconciliation(
    db: AsyncSession,
    *,
    start: datetime,
    end: datetime,
    plan: str | None,
    provider: str | None,
    model: str | None,
    persona: str | None,
    feature: str | None,
) -> dict[str, Any]:
    statement = (
        select(
            models.ResumeOptimizationRun.status,
            models.ResumeOptimizationRun.provider,
            models.ResumeOptimizationRun.model,
            models.ResumeOptimizationRun.created_at,
            models.ResumeOptimizationRun.updated_at,
            models.ResumeOptimizationRun.context_payload["direction"]["persona"].astext,
            models.User.subscription_plan,
            models.Resume.resume_settings,
        )
        .outerjoin(models.User, models.User.id == models.ResumeOptimizationRun.user_id)
        .outerjoin(models.Resume, models.Resume.id == models.ResumeOptimizationRun.resume_id)
        .where(
            models.ResumeOptimizationRun.created_at >= start,
            models.ResumeOptimizationRun.created_at < end,
        )
    )
    if plan:
        statement = statement.where(func.lower(models.User.subscription_plan) == plan)
    if provider:
        statement = statement.where(func.lower(models.ResumeOptimizationRun.provider) == provider)
    if model:
        statement = statement.where(func.lower(models.ResumeOptimizationRun.model) == model)

    by_status: dict[str, int] = defaultdict(int)
    latencies: list[float] = []
    total = 0
    for status, _run_provider, _run_model, created_at, updated_at, run_persona, _plan_id, resume_settings in (
        await db.execute(statement)
    ).all():
        normalized_status = _clean(status, 32)
        candidate_persona = _event_persona(run_persona, resume_settings)
        if persona and candidate_persona != persona:
            continue
        total += 1
        by_status[normalized_status] += 1
        if normalized_status in RUN_TERMINAL_STATUSES:
            latency = _latency_ms(created_at, updated_at)
            if latency is not None:
                latencies.append(latency)

    latency = _latency_summary(latencies)
    return {
        "source": "resume_optimization_runs",
        "runs": total,
        "by_status": dict(sorted(by_status.items())),
        "successes": by_status.get("completed", 0),
        "partial": by_status.get("partial", 0),
        "errors": by_status.get("failed", 0) + by_status.get("cancelled", 0),
        "pending": by_status.get("running", 0),
        "latency_p50_ms": latency["p50_ms"],
        "latency_p95_ms": latency["p95_ms"],
        "latency_avg_ms": latency["average_ms"],
        "latency_samples": latency["samples"],
        "filters_applied": {
            "plan": plan,
            "provider": provider,
            "model": model,
            "persona": persona,
            "feature": None,
        },
        "note": (
            "Run-level reconciliation only. Stage events are the usage unit above so "
            "run and stage tokens are not double counted. The feature filter applies to "
            "stage events, not to run admission rows."
        ),
    }


def _day_window(days: int, now: datetime) -> tuple[date, date, datetime, datetime]:
    days = max(1, min(int(days), 365))
    today = now.date()
    start_day = today - timedelta(days=days - 1)
    start = datetime.combine(start_day, time.min, tzinfo=timezone.utc)
    end = datetime.combine(today + timedelta(days=1), time.min, tzinfo=timezone.utc)
    return start_day, today, start, end


async def ai_usage_snapshot(
    db: AsyncSession,
    *,
    days: int = 30,
    plan: str | None = None,
    feature: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    persona: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = _utc(now)
    start_day, end_day, start, end = _day_window(days, now)
    days = (end_day - start_day).days + 1

    plan_filter = _filter_value(plan, 50)
    feature_filter = _filter_value(feature, 120)
    provider_filter = _filter_value(provider, 80)
    model_filter = _filter_value(model, 160)
    persona_filter = _filter_value(persona, 64)

    optimization_events = await _load_optimization_events(
        db,
        start=start,
        end=end,
        plan=plan_filter,
        provider=provider_filter,
        model=model_filter,
    )
    stage_events = await _load_stage_events(
        db,
        start=start,
        end=end,
        plan=plan_filter,
        provider=provider_filter,
        model=model_filter,
    )

    events = [
        event
        for event in [*optimization_events, *stage_events]
        if (not feature_filter or event.feature == feature_filter)
        and (not persona_filter or event.persona == persona_filter)
    ]

    totals = _Aggregate()
    by_feature: dict[str, _Aggregate] = defaultdict(_Aggregate)
    by_provider: dict[str, _Aggregate] = defaultdict(_Aggregate)
    by_model: dict[tuple[str, str], _Aggregate] = defaultdict(_Aggregate)
    by_persona: dict[str, _Aggregate] = defaultdict(_Aggregate)
    by_plan: dict[str, _Aggregate] = defaultdict(_Aggregate)
    by_credential_source: dict[str, _Aggregate] = defaultdict(_Aggregate)
    by_source: dict[str, _Aggregate] = defaultdict(_Aggregate)

    for event in events:
        totals.add(event)
        by_feature[event.feature].add(event)
        by_provider[event.provider].add(event)
        by_model[(event.provider, event.model)].add(event)
        by_persona[event.persona].add(event)
        by_plan[event.plan].add(event)
        by_credential_source[event.credential_source].add(event)
        by_source[event.source].add(event)

    def _dimension_rows(
        dimension: str,
        groups: dict[Any, _Aggregate],
        make_label,
        make_key_value,
        make_extra=None,
    ) -> tuple[list[dict[str, Any]], int]:
        rows: list[dict[str, Any]] = []
        suppressed = 0
        for group_key, bucket in groups.items():
            if len(bucket.users) < MIN_GROUP_SIZE or bucket.runs < MIN_GROUP_SIZE:
                suppressed += 1
                continue
            value = make_key_value(group_key)
            row = _row(make_label(group_key), bucket, dimension, value)
            if make_extra is not None:
                row.update(make_extra(group_key))
            rows.append(row)
        rows.sort(key=lambda item: (-item["runs"], item["label"]))
        return rows, suppressed

    feature_rows, feature_suppressed = _dimension_rows(
        "feature", by_feature, lambda key: key, lambda key: key
    )
    provider_rows, provider_suppressed = _dimension_rows(
        "provider", by_provider, lambda key: key, lambda key: key
    )
    model_rows, model_suppressed = _dimension_rows(
        "model",
        by_model,
        lambda key: f"{key[0]}/{key[1]}",
        lambda key: f"{key[0]}/{key[1]}",
        lambda key: {"provider": key[0], "model": key[1]},
    )
    persona_rows, persona_suppressed = _dimension_rows(
        "persona", by_persona, lambda key: key, lambda key: key
    )
    plan_rows, plan_suppressed = _dimension_rows("plan", by_plan, lambda key: key, lambda key: key)
    credential_rows, credential_suppressed = _dimension_rows(
        "credential_source", by_credential_source, lambda key: key, lambda key: key
    )

    suppressed_by_dimension = {
        "feature": feature_suppressed,
        "provider": provider_suppressed,
        "model": model_suppressed,
        "persona": persona_suppressed,
        "plan": plan_suppressed,
        "credential_source": credential_suppressed,
    }
    suppressed_groups = sum(suppressed_by_dimension.values())

    source_rows = []
    for source in ("optimizations", "resume_optimization_stages"):
        bucket = by_source.get(source, _Aggregate())
        source_rows.append(
            {
                "source": source,
                "table": source,
                **_metrics(bucket),
            }
        )

    run_summary = await _run_reconciliation(
        db,
        start=start,
        end=end,
        plan=plan_filter,
        provider=provider_filter,
        model=model_filter,
        persona=persona_filter,
        feature=feature_filter,
    )

    return {
        "period_days": days,
        "start_date": start_day.isoformat(),
        "end_date": end_day.isoformat(),
        "generated_at": now.isoformat(),
        "filters": {
            "plan": plan_filter,
            "feature": feature_filter,
            "provider": provider_filter,
            "model": model_filter,
            "persona": persona_filter,
        },
        "minimum_group_size": MIN_GROUP_SIZE,
        "suppressed_groups": suppressed_groups,
        "suppression": {
            "minimum_group_size": MIN_GROUP_SIZE,
            "rule": "Hide a breakdown row with fewer than 5 distinct users or fewer than 5 runs.",
            "suppressed_groups": suppressed_groups,
            "by_dimension": suppressed_by_dimension,
        },
        "totals": _metrics(totals),
        "by_feature": feature_rows,
        "by_provider": provider_rows,
        "by_model": model_rows,
        "by_persona": persona_rows,
        "by_plan": plan_rows,
        "by_credential_source": credential_rows,
        "reconciliation": {
            "sources": source_rows,
            "total_events": totals.runs,
            "total_successes": totals.successes,
            "total_errors": totals.errors,
            "total_tokens": totals.tokens,
            "resume_engine_runs": run_summary,
        },
        "persona_source": (
            "Semantic resume-engine runs use the persisted job-submission persona; "
            "legacy optimization rows use the resume's last saved first-party persona "
            "metadata; otherwise the value is reported as unknown."
        ),
        "credential_source_note": (
            "Credential source is derived from the run's keyed credential fingerprint "
            "compared with configured platform keys. No stored key material is read or "
            "returned. Legacy optimization rows have no persisted source and report unknown."
        ),
        "privacy": {
            "aggregate_only": True,
            "per_user_rows": False,
            "content_fields_read": [
                "resume.metadata.last_persona",
                "resume_optimization_runs.context_payload.direction.persona",
            ],
            "content_fields_excluded": [
                "prompts",
                "job descriptions",
                "resume/LaTeX content",
                "API keys and credential fingerprints",
                "per-user payloads",
            ],
        },
        "notes": [
            "Usage events are legacy optimization rows plus durable resume-engine stage rows.",
            "Success is completed; errors are failed, ambiguous, or cancelled; requesting/running is pending.",
            "Latency is p50/p95/average over measured optimization or stage elapsed time in milliseconds.",
            "Small groups are suppressed in every breakdown; totals remain aggregate-only.",
        ],
    }
