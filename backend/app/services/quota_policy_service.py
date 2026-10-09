"""Versioned SKU-specific limits; immutable windows preserve existing counters.

This module does not import entitlement_service or touch Redis. Readers use a
fresh database snapshot. Only a missing override falls back to the configured
family policy; an unavailable database never becomes an unlimited grant.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import QUOTA_DIMENSIONS, get_plan_quota, get_plan_quota_window
from ..core.feature_registry import PLAN_KEYS, PLAN_SKU_ALIASES
from ..database.connection import get_async_db_session
from ..database.models import PlanQuotaOverride, PlanQuotaRevision

MAX_QUOTA_LIMIT = 1_000_000_000


class QuotaPolicyConflict(ValueError):
    pass


def canonical_quota_sku(plan: str | None) -> str:
    normalized = (plan or "free").strip().lower()
    sku = PLAN_SKU_ALIASES.get(normalized, normalized)
    if sku not in PLAN_KEYS:
        raise KeyError(f"Unknown plan SKU: {sku!r}")
    return sku


def format_quota_policy(policy: dict) -> str:
    if policy["limit"] is None:
        return "unlimited"
    return f'{policy["limit"]} / {policy["window"]}' if policy["limit"] else "0"


class QuotaPolicyService:
    async def catalog_overrides(self, db: AsyncSession) -> dict[tuple[str, str], PlanQuotaOverride]:
        result = await db.execute(select(PlanQuotaOverride))
        return {(row.sku, row.dimension): row for row in result.scalars().all()}

    def catalog_policy(self, plan: str | None, overrides: dict) -> dict[str, dict[str, Any]]:
        sku = canonical_quota_sku(plan)
        policies = {}
        for dimension in QUOTA_DIMENSIONS:
            row = overrides.get((sku, dimension))
            policies[dimension] = {
                "limit": row.limit_value if row is not None else get_plan_quota(sku, dimension),
                "window": get_plan_quota_window(sku, dimension),
                "version": row.version if row is not None else 1,
                "source": "admin_override" if row is not None else "configured_default",
            }
        return policies

    async def resolve(self, plan: str | None) -> dict[str, dict]:
        sku = canonical_quota_sku(plan)
        async with get_async_db_session() as db:
            result = await db.execute(select(PlanQuotaOverride).where(PlanQuotaOverride.sku == sku))
            rows = {(row.sku, row.dimension): row for row in result.scalars().all()}
        return {
            dimension: {"limit": policy["limit"], "window": policy["window"]}
            for dimension, policy in self.catalog_policy(sku, rows).items()
        }

    async def update(self, db: AsyncSession, plan: str, dimension: str, *, limit: int | None, version: int, admin_id: str) -> None:
        sku = canonical_quota_sku(plan)
        # Admin paths must use canonical SKUs, never silently edit an alias.
        if sku != plan or dimension not in QUOTA_DIMENSIONS:
            raise KeyError("Unknown plan SKU or quota dimension")
        if limit is not None and (type(limit) is not int or not 0 <= limit <= MAX_QUOTA_LIMIT):
            raise ValueError(f"Limit must be an integer from 0 to {MAX_QUOTA_LIMIT}, or null for unlimited")
        if type(version) is not int or version < 1:
            raise ValueError("A positive integer version is required")
        await db.execute(insert(PlanQuotaOverride).values(
            sku=sku, dimension=dimension, limit_value=get_plan_quota(sku, dimension), version=1,
        ).on_conflict_do_nothing(index_elements=["sku", "dimension"]))
        result = await db.execute(select(PlanQuotaOverride).where(
            PlanQuotaOverride.sku == sku, PlanQuotaOverride.dimension == dimension,
        ).with_for_update())
        row = result.scalar_one()
        if row.version != version:
            await db.rollback()
            raise QuotaPolicyConflict("This quota changed. Reload the catalog and review before saving again.")
        row.limit_value = limit
        row.version += 1
        row.updated_by = admin_id
        db.add(PlanQuotaRevision(
            sku=sku, dimension=dimension, version=row.version, limit_value=limit,
            changed_by=admin_id,
        ))
        await db.commit()


quota_policy_service = QuotaPolicyService()


async def resolve_quota_policy(plan: str | None, dimension: str) -> tuple[int | None, str]:
    if dimension not in QUOTA_DIMENSIONS:
        raise KeyError(f"Unknown quota dimension: {dimension!r}")
    policy = (await quota_policy_service.resolve(plan))[dimension]
    return policy["limit"], policy["window"]
