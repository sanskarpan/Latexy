"""Aggregate BYOK vs platform-key usage and estimated cost mix.

The rollup is built from the same two first-party AI ledgers as the AI usage
breakdown:

* ``optimizations`` for legacy per-run token totals, and
* ``resume_optimization_stages`` for durable resume-engine stage usage.

Credential source comes from the persisted, non-secret label on new semantic
runs or from the existing keyed-fingerprint classification for older runs.  A
legacy optimization row has no trustworthy source and is reported as
``unknown``.  No API key, ciphertext, key name, fingerprint, prompt, job
description, résumé or LaTeX content is read or returned.

Every breakdown row is suppressed when it contains fewer than five distinct
users or fewer than five calls.  Totals remain aggregate-only; source shares
are computed over all events so the mix percentages reconcile to 100%.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import models
from .admin_ai_cost_service import _minor, _pricing_book, _utc
from .admin_ai_usage_service import (
    MIN_GROUP_SIZE,
    UsageEvent,
    _day_window,
    _filter_value,
    _load_optimization_events,
    _load_stage_events,
)
from .credential_source import CREDENTIAL_SOURCE_ORDER, CREDENTIAL_SOURCES

SOURCE_TABLES = {
    "optimizations": "optimizations",
    "resume_optimization_stages": "resume_optimization_stages",
}


@dataclass
class _MixBucket:
    calls: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    users: set[str] = field(default_factory=set)
    estimated_calls: int = 0
    unknown_pricing_calls: int = 0

    def add(self, event: UsageEvent, cost: float, *, estimated: bool, unknown_pricing: bool) -> None:
        self.calls += 1
        self.tokens += max(0, int(event.tokens))
        self.cost_usd += max(0.0, float(cost))
        if event.user_id:
            self.users.add(event.user_id)
        if estimated:
            self.estimated_calls += 1
        if unknown_pricing:
            self.unknown_pricing_calls += 1

    def merge(self, other: "_MixBucket") -> None:
        self.calls += other.calls
        self.tokens += other.tokens
        self.cost_usd += other.cost_usd
        self.users.update(other.users)
        self.estimated_calls += other.estimated_calls
        self.unknown_pricing_calls += other.unknown_pricing_calls


def _pct(part: float, whole: float) -> float:
    if whole <= 0:
        return 0.0
    return round(part / whole * 100, 2)


def _normalized_shares(parts: dict[str, float]) -> dict[str, float]:
    """Largest-remainder percentages so the source mix always totals 100.00."""
    total = sum(max(0.0, value) for value in parts.values())
    if total <= 0:
        return {key: 0.0 for key in parts}
    units = {key: max(0.0, value) / total * 10_000 for key, value in parts.items()}
    floors = {key: int(math.floor(value)) for key, value in units.items()}
    remainder = 10_000 - sum(floors.values())
    ranked = sorted(
        units,
        key=lambda key: (-(units[key] - floors[key]), CREDENTIAL_SOURCE_ORDER.get(key, 99), key),
    )
    for key in ranked[:remainder]:
        floors[key] += 1
    return {key: round(value / 100, 2) for key, value in floors.items()}


def _event_cost(event: UsageEvent, pricing) -> tuple[float, bool, bool]:
    """Return (estimated cost, estimated flag, unknown pricing flag)."""
    quote = pricing.quote(event.provider, event.model)
    unknown_pricing = not quote.known
    if event.recorded_cost_usd is not None:
        return event.recorded_cost_usd, False, unknown_pricing
    input_tokens = max(0, int(event.input_tokens))
    output_tokens = max(0, int(event.output_tokens))
    if input_tokens or output_tokens:
        cost = (input_tokens * quote.input_per_million + output_tokens * quote.output_per_million) / 1_000_000
    else:
        cost = max(0, int(event.tokens)) / 1_000_000 * quote.blended_per_million
    return cost, True, unknown_pricing


def _mix_metrics(bucket: _MixBucket, totals: _MixBucket) -> dict[str, Any]:
    return {
        "calls": bucket.calls,
        "tokens": bucket.tokens,
        "cost_usd": round(bucket.cost_usd, 6),
        "cost_usd_minor": _minor(bucket.cost_usd),
        "users": len(bucket.users),
        "estimated_calls": bucket.estimated_calls,
        "unknown_pricing_calls": bucket.unknown_pricing_calls,
        "call_share_pct": _pct(bucket.calls, totals.calls),
        "token_share_pct": _pct(bucket.tokens, totals.tokens),
        "cost_share_pct": _pct(bucket.cost_usd, totals.cost_usd),
    }


def _is_visible(bucket: _MixBucket) -> bool:
    return len(bucket.users) >= MIN_GROUP_SIZE and bucket.calls >= MIN_GROUP_SIZE


def _dimension_rows(
    value_key: str,
    groups: dict[tuple[str, str], _MixBucket],
    totals: _MixBucket,
) -> tuple[list[dict[str, Any]], int, _MixBucket]:
    rows: list[dict[str, Any]] = []
    suppressed = 0
    hidden = _MixBucket()
    for (value, source), bucket in groups.items():
        if not _is_visible(bucket):
            suppressed += 1
            hidden.merge(bucket)
            continue
        rows.append(
            {
                value_key: value,
                "credential_source": source,
                **_mix_metrics(bucket, totals),
            }
        )
    rows.sort(
        key=lambda item: (
            -item["calls"],
            item[value_key],
            CREDENTIAL_SOURCE_ORDER.get(item["credential_source"], 99),
        )
    )
    return rows, suppressed, hidden


async def _key_ownership(db: AsyncSession, *, plan: str | None) -> dict[str, Any]:
    """Count key ownership only; never select key material or key identities."""
    statement = select(
        models.UserAPIKey.user_id,
        models.UserAPIKey.provider,
        models.UserAPIKey.is_active,
        models.User.subscription_plan,
    ).outerjoin(models.User, models.User.id == models.UserAPIKey.user_id)
    if plan:
        statement = statement.where(func.lower(models.User.subscription_plan) == plan)

    active_users: set[str] = set()
    any_users: set[str] = set()
    active_keys = 0
    inactive_keys = 0
    provider_active_keys: dict[str, int] = defaultdict(int)
    provider_inactive_keys: dict[str, int] = defaultdict(int)
    provider_users: dict[str, set[str]] = defaultdict(set)
    plan_active_keys: dict[str, int] = defaultdict(int)
    plan_inactive_keys: dict[str, int] = defaultdict(int)
    plan_users: dict[str, set[str]] = defaultdict(set)

    for user_id, provider, is_active, plan_id in (await db.execute(statement)).all():
        if not user_id:
            continue
        provider_name = (provider or "unknown").strip().lower()[:50] or "unknown"
        plan_name = (plan_id or "free").strip().lower()[:50] or "free"
        any_users.add(str(user_id))
        if is_active:
            active_users.add(str(user_id))
            active_keys += 1
            provider_active_keys[provider_name] += 1
            provider_users[provider_name].add(str(user_id))
            plan_active_keys[plan_name] += 1
            plan_users[plan_name].add(str(user_id))
        else:
            inactive_keys += 1
            provider_inactive_keys[provider_name] += 1
            plan_inactive_keys[plan_name] += 1

    by_provider: list[dict[str, Any]] = []
    suppressed_provider_groups = 0
    for provider_name in sorted(set(provider_active_keys) | set(provider_inactive_keys)):
        users = provider_users.get(provider_name, set())
        if len(users) < MIN_GROUP_SIZE:
            suppressed_provider_groups += 1
            continue
        by_provider.append(
            {
                "provider": provider_name,
                "active_keys": provider_active_keys.get(provider_name, 0),
                "inactive_keys": provider_inactive_keys.get(provider_name, 0),
                "users": len(users),
            }
        )
    by_provider.sort(key=lambda row: (-row["active_keys"], -row["users"], row["provider"]))

    by_plan: list[dict[str, Any]] = []
    suppressed_plan_groups = 0
    for plan_name in sorted(set(plan_active_keys) | set(plan_inactive_keys)):
        users = plan_users.get(plan_name, set())
        if len(users) < MIN_GROUP_SIZE:
            suppressed_plan_groups += 1
            continue
        by_plan.append(
            {
                "plan": plan_name,
                "active_keys": plan_active_keys.get(plan_name, 0),
                "inactive_keys": plan_inactive_keys.get(plan_name, 0),
                "users": len(users),
            }
        )
    by_plan.sort(key=lambda row: (-row["active_keys"], -row["users"], row["plan"]))

    return {
        "active_keys": active_keys,
        "inactive_keys": inactive_keys,
        "users_with_active_keys": len(active_users),
        "users_with_any_keys": len(any_users),
        "minimum_group_size": MIN_GROUP_SIZE,
        "suppressed_groups": suppressed_provider_groups + suppressed_plan_groups,
        "by_provider": by_provider,
        "by_plan": by_plan,
        "note": (
            "Ownership counts only. Key material, ciphertext, key names, key IDs and "
            "per-key fingerprints are never selected or returned."
        ),
    }


async def credential_mix_snapshot(
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

    pricing = _pricing_book()
    totals = _MixBucket()
    by_source: dict[str, _MixBucket] = defaultdict(_MixBucket)
    by_ledger: dict[str, _MixBucket] = defaultdict(_MixBucket)
    by_feature: dict[tuple[str, str], _MixBucket] = defaultdict(_MixBucket)
    by_plan: dict[tuple[str, str], _MixBucket] = defaultdict(_MixBucket)
    by_provider: dict[tuple[str, str], _MixBucket] = defaultdict(_MixBucket)
    by_model: dict[tuple[str, str], _MixBucket] = defaultdict(_MixBucket)
    by_persona: dict[tuple[str, str], _MixBucket] = defaultdict(_MixBucket)
    by_day: dict[tuple[str, str], _MixBucket] = defaultdict(_MixBucket)

    for event in events:
        cost, estimated, unknown_pricing = _event_cost(event, pricing)
        source = event.credential_source
        if source not in CREDENTIAL_SOURCE_ORDER:
            source = "unknown"
        totals.add(event, cost, estimated=estimated, unknown_pricing=unknown_pricing)
        by_source[source].add(event, cost, estimated=estimated, unknown_pricing=unknown_pricing)
        by_ledger[event.source].add(event, cost, estimated=estimated, unknown_pricing=unknown_pricing)
        by_feature[(event.feature, source)].add(event, cost, estimated=estimated, unknown_pricing=unknown_pricing)
        by_plan[(event.plan, source)].add(event, cost, estimated=estimated, unknown_pricing=unknown_pricing)
        by_provider[(event.provider, source)].add(event, cost, estimated=estimated, unknown_pricing=unknown_pricing)
        by_model[(f"{event.provider}/{event.model}", source)].add(
            event, cost, estimated=estimated, unknown_pricing=unknown_pricing
        )
        by_persona[(event.persona, source)].add(event, cost, estimated=estimated, unknown_pricing=unknown_pricing)
        day = event.occurred_at.date().isoformat()
        by_day[(day, source)].add(event, cost, estimated=estimated, unknown_pricing=unknown_pricing)

    call_shares = _normalized_shares(
        {source: by_source[source].calls if source in by_source else 0 for source in CREDENTIAL_SOURCES}
    )
    token_shares = _normalized_shares(
        {source: by_source[source].tokens if source in by_source else 0 for source in CREDENTIAL_SOURCES}
    )
    cost_shares = _normalized_shares(
        {source: by_source[source].cost_usd if source in by_source else 0 for source in CREDENTIAL_SOURCES}
    )
    mix: dict[str, dict[str, Any]] = {}
    for source in CREDENTIAL_SOURCES:
        bucket = by_source.get(source, _MixBucket())
        row = _mix_metrics(bucket, totals)
        row["call_share_pct"] = call_shares[source]
        row["token_share_pct"] = token_shares[source]
        row["cost_share_pct"] = cost_shares[source]
        mix[source] = row

    source_rows: list[dict[str, Any]] = []
    suppressed_source_groups = 0
    for source in CREDENTIAL_SOURCES:
        bucket = by_source.get(source)
        if bucket is None or bucket.calls == 0:
            continue
        if not _is_visible(bucket):
            suppressed_source_groups += 1
            continue
        source_rows.append(
            {
                "credential_source": source,
                **_mix_metrics(bucket, totals),
            }
        )

    feature_rows, feature_suppressed, _feature_hidden = _dimension_rows("feature", by_feature, totals)
    plan_rows, plan_suppressed, _plan_hidden = _dimension_rows("plan", by_plan, totals)
    provider_rows, provider_suppressed, _provider_hidden = _dimension_rows("provider", by_provider, totals)
    model_rows, model_suppressed, _model_hidden = _dimension_rows("model", by_model, totals)
    persona_rows, persona_suppressed, _persona_hidden = _dimension_rows("persona", by_persona, totals)
    day_rows, day_suppressed, _day_hidden = _dimension_rows("date", by_day, totals)
    day_rows.sort(key=lambda item: (item["date"], CREDENTIAL_SOURCE_ORDER.get(item["credential_source"], 99)))

    suppressed_by_dimension = {
        "credential_source": suppressed_source_groups,
        "feature": feature_suppressed,
        "plan": plan_suppressed,
        "provider": provider_suppressed,
        "model": model_suppressed,
        "persona": persona_suppressed,
        "day": day_suppressed,
    }
    suppressed_groups = sum(suppressed_by_dimension.values())

    ledger_rows = []
    ledger_calls = 0
    for source, table in SOURCE_TABLES.items():
        bucket = by_ledger.get(source, _MixBucket())
        ledger_calls += bucket.calls
        ledger_rows.append(
            {
                "source": source,
                "table": table,
                "calls": bucket.calls,
                "tokens": bucket.tokens,
                "cost_usd": round(bucket.cost_usd, 6),
                "cost_usd_minor": _minor(bucket.cost_usd),
                "users": len(bucket.users),
                "estimated_calls": bucket.estimated_calls,
                "unknown_pricing_calls": bucket.unknown_pricing_calls,
            }
        )

    source_cost_total = sum(mix[source]["cost_usd"] for source in CREDENTIAL_SOURCES)
    source_call_total = sum(mix[source]["calls"] for source in CREDENTIAL_SOURCES)
    source_token_total = sum(mix[source]["tokens"] for source in CREDENTIAL_SOURCES)
    call_share_total = round(sum(call_shares.values()), 2)
    classified_calls = mix["byok"]["calls"] + mix["platform"]["calls"]
    checks = [
        {
            "key": "source_call_sum",
            "label": "Credential-source calls equal total calls",
            "expected": totals.calls,
            "actual": source_call_total,
            "ok": source_call_total == totals.calls,
        },
        {
            "key": "source_token_sum",
            "label": "Credential-source tokens equal total tokens",
            "expected": totals.tokens,
            "actual": source_token_total,
            "ok": source_token_total == totals.tokens,
        },
        {
            "key": "source_cost_sum",
            "label": "Credential-source cost equals total estimated cost",
            "expected": round(totals.cost_usd, 6),
            "actual": round(source_cost_total, 6),
            "ok": abs(source_cost_total - totals.cost_usd) <= 0.00001,
        },
        {
            "key": "ledger_call_sum",
            "label": "Ledger calls equal total calls",
            "expected": totals.calls,
            "actual": ledger_calls,
            "ok": ledger_calls == totals.calls,
        },
        {
            "key": "mix_share_sum",
            "label": "BYOK, platform and unknown shares total 100%",
            "expected": 100.0,
            "actual": call_share_total,
            "ok": call_share_total == 100.0,
        },
    ]

    key_ownership = await _key_ownership(db, plan=plan_filter)

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
        "currency": "USD",
        "minor_unit": "cent",
        "totals": {
            "calls": totals.calls,
            "tokens": totals.tokens,
            "cost_usd": round(totals.cost_usd, 6),
            "cost_usd_minor": _minor(totals.cost_usd),
            "users": len(totals.users),
            "classified_calls": classified_calls,
            "unclassified_calls": mix["unknown"]["calls"],
            "classified_share_pct": _pct(classified_calls, totals.calls),
            "mix": mix,
        },
        "sources": source_rows,
        "by_feature": feature_rows,
        "by_plan": plan_rows,
        "by_provider": provider_rows,
        "by_model": model_rows,
        "by_persona": persona_rows,
        "by_day": day_rows,
        "key_ownership": key_ownership,
        "suppressed_groups": suppressed_groups,
        "suppression": {
            "minimum_group_size": MIN_GROUP_SIZE,
            "rule": (
                "Hide a breakdown row with fewer than 5 distinct users or fewer than 5 calls. "
                "Totals and mix percentages remain aggregate-only."
            ),
            "suppressed_groups": suppressed_groups,
            "by_dimension": suppressed_by_dimension,
        },
        "reconciliation": {
            "ledgers": ledger_rows,
            "total_calls": totals.calls,
            "total_tokens": totals.tokens,
            "total_cost_usd": round(totals.cost_usd, 6),
            "total_cost_usd_minor": _minor(totals.cost_usd),
            "classified_calls": classified_calls,
            "unknown_calls": mix["unknown"]["calls"],
            "call_share_total_pct": call_share_total,
            "checks": checks,
            "unknown_policy": (
                "Legacy optimization rows have no persisted credential scope and are reported as unknown. "
                "New semantic resume-engine runs persist a non-secret source label at admission."
            ),
        },
        "privacy": {
            "aggregate_only": True,
            "per_user_rows": False,
            "content_fields_read": [
                "resume_optimization_runs.credential_scope (in memory only)",
                "resume_optimization_runs.context_payload.credential_source",
                "resume.metadata.last_persona",
                "resume_optimization_runs.context_payload.direction.persona",
            ],
            "content_fields_excluded": [
                "prompts",
                "job descriptions",
                "resume/LaTeX content",
                "API keys and ciphertext",
                "key names and key IDs",
                "credential fingerprints",
                "per-user payloads",
            ],
        },
        "credential_source_note": (
            "New semantic runs persist a non-secret credential source. Older runs are classified by "
            "comparing their keyed fingerprint with configured platform keys in memory; the fingerprint "
            "is never returned. Legacy optimization rows are unknown."
        ),
        "notes": [
            "Calls, tokens and estimated cost reconcile across BYOK, platform and unknown sources.",
            "Estimated cost uses recorded provider usage when present and the active pricing book otherwise.",
            "Key ownership is counts only and is never joined to per-key data.",
            "Small cohorts are suppressed in every breakdown; totals remain aggregate-only.",
        ],
    }
