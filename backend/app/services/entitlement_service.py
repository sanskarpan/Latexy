"""Entitlement service — feature access + usage quota resolution.

Two layers:

1. BOOLEAN features (Admin Control Plane) — ``has_feature`` / ``get_state`` /
   ``sync_has_feature``. Source of truth = DB (feature_flags kill-switches +
   plan_features matrix), fanned out through a Redis blob.
2. NUMERIC quotas — ``consume_quota`` / ``enforce_quota`` / ``refund_quota``.
   Source of truth = ``config.PLAN_QUOTAS`` via ``config.get_plan_quota`` /
   ``config.get_plan_quota_window``. Counters live in Redis under
   ``latexy:quota:{dimension}:{user_id}:{period}`` and are incremented with an
   atomic INCR, so concurrent bursts can never exceed the allowance.

Quota window: per dimension AND per plan family — ``day`` (period ``YYYYMMDD``)
or ``month`` (period ``YYYYMM``), both in UTC. The free tier's compile allowance
is daily so a burst of edits cannot lock someone out for the rest of the month.
The counter key embeds the period, so the reset is implicit — no cron, no
backfill. Keys carry a 40-day TTL so an idle account's rows expire on their own.

Feature-flag propagation uses a single Redis JSON blob ``latexy:entitlements``:

    {"kill": {key: bool}, "matrix": {family: {key: bool}}}

Access modes (mirroring feature_flag_service):
- Async ``has_feature`` / ``get_state`` / mutations: DB-backed with a 60s
  in-process TTL cache on the Redis blob. Used by FastAPI routes.
- Sync ``sync_has_feature``: reads the Redis blob (workers, no user context).

Failure policy differs deliberately between the two layers:
- Boolean features fail OPEN on infra error (a Redis blip must not hide the
  product) — consistent with the existing feature flag service.
- Quotas fail CLOSED (a Redis blip must not hand out unmetered LLM spend) —
  consistent with developer_key_service.consume_rate_limit — except on plans
  with no limit, where there is no allowance to protect and denying would be a
  self-inflicted outage.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import (
    QUOTA_DIMENSIONS,
    get_plan_quota,
    get_plan_quota_window,
    resolve_plan_family,
)
from ..core.errors import error_body
from ..core.feature_registry import (
    FEATURE_REGISTRY,
    PLAN_FAMILIES,
    is_gateable,
)
from ..database.models import FeatureFlag, PlanFeature, User

logger = logging.getLogger(__name__)

REDIS_BLOB_KEY = "latexy:entitlements"
_CACHE_TTL = 60  # seconds

# Quota counters outlive their calendar month by a margin so a late refund (or a
# clock skew across instances) can still find the key it incremented.
_QUOTA_TTL = 40 * 86400  # seconds

# INCRBY and EXPIRE as one round-trip, so they cannot come apart.
#
# Done as two calls, a failure between them left the counter incremented with no
# TTL: the caller was charged, the request was denied anyway because the error
# propagated, and the key then never expired — so the charge never rolled over to
# the next period and the user stayed billed for it permanently. Inside a Lua
# script the pair either both apply or neither does, and there is no window for a
# concurrent caller to observe a TTL-less key.
_INCR_WITH_TTL = """
local v = redis.call('INCRBY', KEYS[1], ARGV[1])
if v == tonumber(ARGV[1]) then
  redis.call('EXPIRE', KEYS[1], ARGV[2])
end
return v
"""

# In-process cache of the parsed blob: (blob: dict, expires_at: float)
_cache: Optional[tuple[dict, float]] = None

_ADMIN_ROLES = ("admin", "support")


@dataclass(frozen=True)
class QuotaTicket:
    """Outcome of one quota consumption attempt.

    ``allowed`` is the only thing routes must check; the rest is what we surface
    to the client (and what ``refund_quota`` needs to give the unit back).
    """

    dimension: str
    user_id: str
    period: str          # "YYYYMM" or "YYYYMMDD" — the window the counter belongs to
    used: int            # count AFTER this consumption
    limit: Optional[int]  # None == unlimited
    allowed: bool
    unavailable: bool = False  # counter store down → denied, not "over limit"
    window: str = "month"  # "day" | "month" — how often ``period`` rolls over

    @property
    def remaining(self) -> Optional[int]:
        if self.limit is None:
            return None
        return max(0, self.limit - self.used)

    def refund_payload(self, *, cost: int = 1) -> dict[str, Any]:
        """Return the minimal, JSON-safe data a background worker needs.

        Workers cannot use this dataclass directly because Celery/Modal cross a
        serialization boundary.  The job id is deliberately supplied by the
        worker when refunding, so callers cannot choose the idempotency key.
        """
        return {
            "dimension": self.dimension,
            "user_id": self.user_id,
            "period": self.period,
            "cost": cost,
        }


def _current_period(window: str = "month") -> str:
    """Return the current quota period key for ``window`` (UTC).

    ``day`` → ``YYYYMMDD``, ``month`` → ``YYYYMM``. The two formats have
    different lengths, so ``_period_reset_at`` can infer the window back from a
    stored period without carrying it around.
    """
    now = datetime.now(timezone.utc)
    return now.strftime("%Y%m%d" if window == "day" else "%Y%m")


def _period_reset_at(period: str) -> str:
    """Return the ISO timestamp at which ``period``'s counters reset (UTC).

    Midnight on the day after a daily period, or midnight on the 1st of the
    following month for a monthly one.
    """
    if len(period) == 8:  # YYYYMMDD — daily window
        day = datetime(
            int(period[:4]), int(period[4:6]), int(period[6:]), tzinfo=timezone.utc
        )
        return (day + timedelta(days=1)).isoformat()

    year, month = int(period[:4]), int(period[4:])
    if month == 12:
        year, month = year + 1, 1
    else:
        month += 1
    return datetime(year, month, 1, tzinfo=timezone.utc).isoformat()


class EntitlementService:
    # ---------------------------------------------------------------- #
    #  Blob (re)build + cache                                          #
    # ---------------------------------------------------------------- #

    def _empty_blob(self) -> dict:
        return {"kill": {}, "matrix": {f: {} for f in PLAN_FAMILIES}}

    async def _rebuild_redis_blob(self) -> dict:
        """Read DB state, build the entitlements blob, and push it to Redis.

        Uses a DEDICATED session (never the caller's request session) so
        entitlement reads can never touch or corrupt an in-flight request
        transaction.
        """
        from ..database.connection import get_async_db_session

        blob = self._empty_blob()
        async with get_async_db_session() as db:
            # Kill-switches (feature_flags rows whose key is a gateable feature).
            result = await db.execute(select(FeatureFlag.key, FeatureFlag.enabled))
            for key, enabled in result.all():
                if is_gateable(key):
                    blob["kill"][key] = bool(enabled)

            # Per-plan matrix.
            result = await db.execute(
                select(PlanFeature.plan_family, PlanFeature.feature_key, PlanFeature.enabled)
            )
            for family, key, enabled in result.all():
                if family in blob["matrix"] and is_gateable(key):
                    blob["matrix"][family][key] = bool(enabled)

        await self._push_to_redis(blob)
        _set_cache(blob)
        return blob

    async def _get_blob(self) -> dict:
        """Return the entitlements blob, using cache → Redis → DB rebuild."""
        now = time.monotonic()
        cached = _cache
        if cached and cached[1] > now:
            return cached[0]

        # Try Redis first (cheap, shared across processes).
        blob = await self._read_from_redis()
        if blob is not None:
            _set_cache(blob)
            return blob

        # Fall back to rebuilding from DB (dedicated session).
        return await self._rebuild_redis_blob()

    # ---------------------------------------------------------------- #
    #  Async access (FastAPI routes)                                   #
    # ---------------------------------------------------------------- #

    async def has_feature(self, key: str, *, user: Any, db: AsyncSession | None = None) -> bool:
        """Resolve whether ``user`` may access feature ``key``.

        ``user`` may be a ``User`` ORM object, a user_id string (as returned by
        ``get_current_user_required``), or None (anonymous).

        Resolution order:
          1. Unknown / non-gateable key            → True
          2. role in (admin, support)              → True (bypass)
          3. Global kill-switch off                → False
          4. matrix[resolve_plan_family(plan)][key] (default True)
        Fail-OPEN on infra error.

        NOTE: ``db`` is accepted for backwards compatibility but is NOT used for
        reads — all entitlement lookups run on a dedicated session so the
        caller's request transaction is never touched or rolled back.
        """
        # 1. Unknown or non-gateable → always allowed.
        if not is_gateable(key):
            return True

        try:
            role, plan = await self._resolve_user_role_plan(user)

            # 2. Admin / support bypass.
            if role in _ADMIN_ROLES:
                return True

            blob = await self._get_blob()
            return self._decide(blob, key, plan)
        except Exception as exc:
            logger.warning(f"entitlement_service.has_feature({key}) error: {exc}")
            return True  # fail open (never touches the caller's session)

    def _decide(self, blob: dict, key: str, plan: Optional[str]) -> bool:
        """Pure blob→bool decision (no I/O). Defaults to allowed when absent."""
        # Global kill-switch. Default enabled (True) when absent.
        if blob["kill"].get(key, True) is False:
            return False
        # Per-plan matrix. Default True when absent.
        family = resolve_plan_family(plan or "free")
        return bool(blob["matrix"].get(family, {}).get(key, True))

    async def _resolve_user_role_plan(
        self, user: Any
    ) -> tuple[Optional[str], Optional[str]]:
        """Return (role, subscription_plan) for a User object, id string, or None.

        For a user_id string, loads the row on a DEDICATED session so the
        caller's request transaction is untouched.
        """
        if user is None:
            return None, None

        # ORM object (or anything exposing the attributes).
        role = getattr(user, "role", None)
        plan = getattr(user, "subscription_plan", None)
        if role is not None or plan is not None:
            return role, plan

        # user is a user_id string → load the row on a dedicated session.
        if isinstance(user, str):
            from ..database.connection import get_async_db_session

            async with get_async_db_session() as db:
                result = await db.execute(
                    select(User.role, User.subscription_plan).where(User.id == user)
                )
                row = result.first()
            if row:
                return row[0], row[1]

        return None, None

    async def get_state(self, db: AsyncSession | None = None) -> dict:
        """Return full entitlement state for the admin API.

        Shape: {registry, kill_switches, matrix, plan_families}. Registry and
        matrix are filled with defaults (True) for anything absent in the DB.
        ``db`` is accepted for signature compatibility but unused (reads run on
        a dedicated session).
        """
        blob = await self._rebuild_redis_blob()

        registry = [
            {"key": f.key, "label": f.label, "category": f.category, "gateable": f.gateable}
            for f in FEATURE_REGISTRY
        ]

        gateable = [f.key for f in FEATURE_REGISTRY if f.gateable]
        kill_switches = {k: bool(blob["kill"].get(k, True)) for k in gateable}
        matrix = {
            family: {k: bool(blob["matrix"].get(family, {}).get(k, True)) for k in gateable}
            for family in PLAN_FAMILIES
        }

        return {
            "registry": registry,
            "kill_switches": kill_switches,
            "matrix": matrix,
            "plan_families": list(PLAN_FAMILIES),
        }

    async def set_kill_switch(self, key: str, enabled: bool, db: AsyncSession) -> None:
        """Upsert a kill-switch row, rebuild the Redis blob, and clear cache."""
        if not is_gateable(key):
            raise KeyError(f"Unknown or non-gateable feature: {key!r}")

        result = await db.execute(select(FeatureFlag).where(FeatureFlag.key == key))
        flag = result.scalar_one_or_none()
        if flag is None:
            from ..core.feature_registry import get_feature

            feature = get_feature(key)
            flag = FeatureFlag(
                key=key,
                enabled=enabled,
                label=feature.label if feature else key,
                description=feature.description if feature else None,
            )
            db.add(flag)
        else:
            flag.enabled = enabled
        await db.commit()

        _clear_cache()
        await self._rebuild_redis_blob()

    async def set_matrix_cell(
        self, family: str, key: str, enabled: bool, db: AsyncSession
    ) -> None:
        """Upsert a matrix cell, rebuild the Redis blob, and clear cache."""
        if family not in PLAN_FAMILIES:
            raise KeyError(f"Unknown plan family: {family!r}")
        if not is_gateable(key):
            raise KeyError(f"Unknown or non-gateable feature: {key!r}")

        result = await db.execute(
            select(PlanFeature).where(
                PlanFeature.plan_family == family,
                PlanFeature.feature_key == key,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = PlanFeature(plan_family=family, feature_key=key, enabled=enabled)
            db.add(row)
        else:
            row.enabled = enabled
        await db.commit()

        _clear_cache()
        await self._rebuild_redis_blob()

    async def effective_features(self, user: Any, db: AsyncSession | None = None) -> dict[str, bool]:
        """Return the per-feature allow map for a user (drives frontend gating).

        Resolves role/plan and the blob ONCE, then decides purely — avoids a
        per-feature query. ``db`` is unused (reads run on a dedicated session).
        """
        try:
            role, plan = await self._resolve_user_role_plan(user)
            bypass = role in _ADMIN_ROLES
            blob = None if bypass else await self._get_blob()
        except Exception as exc:
            logger.warning(f"entitlement_service.effective_features error: {exc}")
            bypass, blob = True, None  # fail open

        result: dict[str, bool] = {}
        for feature in FEATURE_REGISTRY:
            if not feature.gateable or bypass or blob is None:
                result[feature.key] = True
            else:
                result[feature.key] = self._decide(blob, feature.key, plan)
        return result

    # ---------------------------------------------------------------- #
    #  Usage quotas (numeric, per daily/monthly window)                #
    # ---------------------------------------------------------------- #

    async def consume_quota(
        self,
        dimension: str,
        *,
        user_id: str,
        plan: Optional[str],
        cost: int = 1,
    ) -> QuotaTicket:
        """Atomically consume ``cost`` units of ``dimension`` for ``user_id``.

        Uses a single Redis INCRBY on the period key, so N concurrent callers get
        N distinct counter values and only the first ``limit`` of them are allowed
        — there is no read-modify-write window to race.

        Unlimited plans are still counted (usage reporting) but never denied.
        Fails CLOSED: if the counter store is unavailable we cannot account for
        the spend, so we refuse rather than hand out unmetered LLM/compile time.
        The single exception is an unlimited plan — there is no allowance to
        protect, so a counter outage degrades usage *reporting* only and must not
        deny the highest-paying tiers.
        """
        limit = get_plan_quota(plan, dimension)
        window = get_plan_quota_window(plan, dimension)
        period = _current_period(window)
        key = f"latexy:quota:{dimension}:{user_id}:{period}"

        try:
            from ..core.redis import get_redis_cache_client

            redis = await get_redis_cache_client()
            used = int(await redis.eval(_INCR_WITH_TTL, 1, key, cost, _QUOTA_TTL))
        except Exception as exc:
            # Nothing to meter on an unlimited plan → the counter is pure
            # reporting, so let the request through instead of manufacturing an
            # outage on endpoints that have no other Redis dependency.
            fail_open = limit is None
            logger.error(
                f"Quota counter unavailable for {dimension}/{user_id}, "
                f"failing {'open (unlimited plan)' if fail_open else 'closed'}: {exc}"
            )
            return QuotaTicket(
                dimension=dimension,
                user_id=user_id,
                period=period,
                used=0 if fail_open else (limit or 0),
                limit=limit,
                allowed=fail_open,
                unavailable=True,
                window=window,
            )

        allowed = limit is None or used <= limit
        if not allowed:
            # Roll the rejected increment back so a client hammering an exhausted
            # quota cannot inflate the counter without bound. The INCR above is
            # still the arbiter of who got a slot, so this cannot let anyone in.
            try:
                used = int(await redis.decrby(key, cost))
            except Exception as exc:
                logger.warning(f"Quota rollback failed for {key}: {exc}")

        return QuotaTicket(
            dimension=dimension,
            user_id=user_id,
            period=period,
            used=used,
            limit=limit,
            allowed=allowed,
            window=window,
        )

    async def refund_quota(self, ticket: QuotaTicket, cost: int = 1) -> None:
        """Give back units consumed by a ticket whose work never happened.

        Called when the metered spend is abandoned AFTER consumption (queue
        submit failed, LLM call errored). Best-effort: a lost refund only ever
        costs the user one unit, whereas a lost consumption costs us money.
        """
        if ticket.unavailable:
            return
        key = f"latexy:quota:{ticket.dimension}:{ticket.user_id}:{ticket.period}"
        try:
            from ..core.redis import get_redis_cache_client

            redis = await get_redis_cache_client()
            await redis.decrby(key, cost)
        except Exception as exc:
            logger.warning(f"Quota refund failed for {key}: {exc}")

    async def enforce_quota(
        self,
        dimension: str,
        *,
        user_id: str,
        plan: Optional[str],
        cost: int = 1,
    ) -> QuotaTicket:
        """Consume quota and raise the standard error envelope when denied.

        402 Payment Required when the plan's allowance is spent (the client's cue
        to show an upgrade prompt); 503 when the counter store is down.
        """
        ticket = await self.consume_quota(dimension, user_id=user_id, plan=plan, cost=cost)
        if ticket.allowed:
            return ticket

        if ticket.unavailable:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=error_body(
                    "quota_unavailable",
                    "Usage metering is temporarily unavailable. Please retry shortly.",
                    None,
                    details={"dimension": dimension},
                ),
            )

        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=error_body(
                "quota_exceeded",
                f"Your plan's {dimension} allowance "
                f"({ticket.limit} per {ticket.window}) is used up. "
                "Upgrade your plan to continue.",
                None,
                details={
                    "dimension": dimension,
                    "limit": ticket.limit,
                    "used": ticket.used,
                    "remaining": 0,
                    "plan_family": resolve_plan_family(plan),
                    "period": ticket.period,
                    "window": ticket.window,
                    "resets_at": _period_reset_at(ticket.period),
                },
            ),
        )

    async def quota_snapshot(self, user_id: str, plan: Optional[str]) -> dict:
        """Return the user's current usage/limit per dimension (read-only).

        Drives the frontend's usage meters. Never mutates a counter; a Redis
        outage reports ``used: null`` rather than failing the request.
        """
        windows = {d: get_plan_quota_window(plan, d) for d in QUOTA_DIMENSIONS}
        periods = {d: _current_period(w) for d, w in windows.items()}
        counts: dict[str, Optional[int]] = {d: None for d in QUOTA_DIMENSIONS}
        try:
            from ..core.redis import get_redis_cache_client

            redis = await get_redis_cache_client()
            for dimension in QUOTA_DIMENSIONS:
                raw = await redis.get(
                    f"latexy:quota:{dimension}:{user_id}:{periods[dimension]}"
                )
                counts[dimension] = int(raw or 0)
        except Exception as exc:
            logger.warning(f"Quota snapshot unavailable for {user_id}: {exc}")

        # Top-level period/resets_at describe the monthly billing window; each
        # dimension carries its own because the windows differ per plan.
        month_period = _current_period("month")
        return {
            "period": month_period,
            "resets_at": _period_reset_at(month_period),
            "dimensions": {
                dimension: {
                    "used": counts[dimension],
                    "limit": get_plan_quota(plan, dimension),
                    "window": windows[dimension],
                    "period": periods[dimension],
                    "resets_at": _period_reset_at(periods[dimension]),
                }
                for dimension in QUOTA_DIMENSIONS
            },
        }

    # ---------------------------------------------------------------- #
    #  Sync access (Celery workers)                                    #
    # ---------------------------------------------------------------- #

    def sync_has_feature(self, key: str, plan_family: str) -> bool:
        """Worker path: resolve a feature for a plan family via the Redis blob.

        No user/admin context — workers act on a job's plan family. Fail-open.
        """
        if not is_gateable(key):
            return True

        blob = self._sync_read_from_redis()
        if blob is None:
            return True  # fail open

        try:
            if blob.get("kill", {}).get(key, True) is False:
                return False
            family = resolve_plan_family(plan_family or "free")
            return bool(blob.get("matrix", {}).get(family, {}).get(key, True))
        except Exception as exc:
            logger.debug(f"sync_has_feature({key}) blob error: {exc}")
            return True  # fail open

    # ---------------------------------------------------------------- #
    #  Redis I/O                                                       #
    # ---------------------------------------------------------------- #

    async def _read_from_redis(self) -> Optional[dict]:
        """Read + parse the entitlements blob from Redis (async). None on miss/error."""
        try:
            import redis.asyncio as aioredis

            from ..core.config import settings
            r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            raw = await r.get(REDIS_BLOB_KEY)
            await r.aclose()
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as exc:
            logger.debug(f"entitlement_service._read_from_redis error: {exc}")
            return None

    async def _push_to_redis(self, blob: dict) -> None:
        """Write the entitlements blob to Redis (async, best-effort)."""
        try:
            import redis.asyncio as aioredis

            from ..core.config import settings
            r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            await r.set(REDIS_BLOB_KEY, json.dumps(blob))
            await r.aclose()
        except Exception as exc:
            logger.debug(f"entitlement_service._push_to_redis error: {exc}")

    def _sync_read_from_redis(self) -> Optional[dict]:
        """Read + parse the entitlements blob from Redis (sync). None on miss/error."""
        # 1. Worker-local client (Celery context).
        try:
            from ..workers.event_publisher import get_worker_redis

            r = get_worker_redis()
            raw = r.get(REDIS_BLOB_KEY)
            if raw is not None:
                return json.loads(raw)
        except Exception:
            pass

        # 2. Direct sync connection (non-worker context).
        try:
            import redis as _redis

            from ..core.config import settings
            r = _redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
            raw = r.get(REDIS_BLOB_KEY)
            r.close()
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as exc:
            logger.debug(f"entitlement_service._sync_read_from_redis error: {exc}")
            return None


# ---------------------------------------------------------------------- #
#  Module-level cache helpers                                            #
# ---------------------------------------------------------------------- #

def _set_cache(blob: dict) -> None:
    global _cache
    _cache = (blob, time.monotonic() + _CACHE_TTL)


def _clear_cache() -> None:
    global _cache
    _cache = None


# Module-level singleton
entitlement_service = EntitlementService()
