"""Database-authoritative product capabilities and independent usage quotas.

Every authorization reads a dedicated database snapshot. Neither process-local
caches nor Redis snapshots may grant product access, so legacy/admin mutations
are effective across processes without a stale-allow window. Missing/unknown
controls and lookup failures deny optional capabilities. Explicit recovery and
security baselines remain available. Numeric quota accounting stays independent.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import String, cast, func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import (
    QUOTA_DIMENSIONS,
    get_plan_quota,
    get_plan_quota_window,
    resolve_plan_family,
)
from ..core.errors import error_body
from ..core.feature_registry import (
    CAPABILITY_ROLES,
    FEATURE_REGISTRY,
    PLAN_FAMILIES,
    PLAN_KEYS,
    PLAN_MATRIX_KEYS,
    PLAN_SKU_ALIASES,
    feature_ancestry,
    get_feature,
    is_gateable,
)
from ..core.logging import get_logger
from ..database.models import FeatureFlag, PlanFeature, RoleFeature, User

logger = get_logger(__name__)

REDIS_BLOB_KEY = "latexy:entitlements"
_CACHE_TTL = 60  # seconds

# Quota counters outlive their calendar month by a margin so a late refund (or a
# clock skew across instances) can still find the key it incremented.
_QUOTA_TTL = 40 * 86400  # seconds

# INCRBY, EXPIRE, and the over-limit rollback as one round-trip, so they cannot
# come apart.
#
# Done as two calls, a failure between them left the counter incremented with no
# TTL: the caller was charged, the request was denied anyway because the error
# propagated, and the key then never expired — so the charge never rolled over to
# the next period and the user stayed billed for it permanently. Inside a Lua
# script the pair either both apply or neither does, and there is no window for a
# concurrent caller to observe a TTL-less key.
_CONSUME_WITH_TTL = """
local v = redis.call('INCRBY', KEYS[1], ARGV[1])
-- Repair counters left without expiry by an interrupted deployment of the old
-- two-command implementation as well as assigning expiry to brand-new keys.
if redis.call('TTL', KEYS[1]) < 0 then
  redis.call('EXPIRE', KEYS[1], ARGV[2])
end
local limit = tonumber(ARGV[3])
if limit >= 0 and v > limit then
  -- Reject and restore this exact increment before another Redis command can
  -- observe it. A separate DECRBY races with refunds and other rejected costs.
  redis.call('DECRBY', KEYS[1], ARGV[1])
  return -1
end
if #KEYS > 1 then
  -- The receipt's age is used by recovery workers.  Stamp it from this
  -- Redis server, rather than trusting the submitting process' wall clock;
  -- otherwise a skewed API host can make a fresh receipt look stale (or keep
  -- an orphan alive indefinitely).  cjson is provided by Redis' Lua runtime.
  local receipt = cjson.decode(ARGV[4])
  local clock = redis.call('TIME')
  receipt.created_at = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
  receipt.created_at_clock = 'redis'
  redis.call('SET', KEYS[2], cjson.encode(receipt), 'NX', 'EX', ARGV[2])
end
return v
"""

# Legacy compatibility state only. Authorization never reads this cache.
_cache: Optional[tuple[dict, float]] = None

def _snapshot_query(keys: tuple[str, ...] | None = None):
    # One statement gives kill switches and grants the same committed snapshot.
    switches = select(literal("kill"), FeatureFlag.key, literal(""), FeatureFlag.enabled)
    grants = select(literal("matrix"), PlanFeature.feature_key, PlanFeature.plan_family, PlanFeature.enabled)
    roles = select(literal("role"), RoleFeature.feature_key, RoleFeature.role, RoleFeature.enabled)
    if keys is not None:
        roles = roles.where(RoleFeature.feature_key.in_(keys))
        switches = switches.where(FeatureFlag.key.in_(keys))
        grants = grants.where(PlanFeature.feature_key.in_(keys))
    return union_all(switches, grants, roles)


def _blob_from_rows(rows) -> dict:
    blob = {"kill": {}, "matrix": {p: {} for p in PLAN_MATRIX_KEYS}, "roles": {r: {} for r in CAPABILITY_ROLES}}
    for kind, key, plan, enabled in rows:
        if not is_gateable(key):
            continue
        if kind == "kill":
            blob["kill"][key] = enabled is True
        elif kind == "role" and plan in blob["roles"]:
            blob["roles"][plan][key] = enabled is True
        elif kind == "matrix" and plan in blob["matrix"]:
            blob["matrix"][plan][key] = enabled is True
    return blob


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
    # A ticket can pass through several exception/cancellation handlers. Keep a
    # stable receipt so a synchronous caller cannot refund the same consumption
    # twice if more than one handler runs. Worker refunds use their job-scoped
    # marker instead, but carrying this value in the serialized payload keeps
    # the receipt available for diagnostics and future worker paths.
    receipt_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    # Present for background submissions so synchronous compensation can remove
    # the matching pending receipt after refunding the counter.
    job_id: Optional[str] = None

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
            "receipt_id": self.receipt_id,
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
    #  Database-authoritative feature snapshot                         #
    # ---------------------------------------------------------------- #

    def _empty_blob(self) -> dict:
        return {"kill": {}, "matrix": {p: {} for p in PLAN_MATRIX_KEYS}, "roles": {r: {} for r in CAPABILITY_ROLES}}

    async def _rebuild_redis_blob(self) -> dict:
        """Compatibility name: read the authoritative DB snapshot, never Redis.

        Keeping this seam avoids breaking internal callers during a rolling
        upgrade. Redis/process caches are intentionally not consulted or written.
        """
        from ..database.connection import get_async_db_session

        async with get_async_db_session() as db:
            result = await db.execute(_snapshot_query())
            return _blob_from_rows(result.all())

    async def _get_blob(self) -> dict:
        return await self._rebuild_redis_blob()

    async def _subject_snapshot(self, user_ids: tuple[str, ...], keys: tuple[str, ...] | None = None):
        """Read current subjects and all relevant restrictions in one SQL snapshot."""
        from ..database.connection import get_async_db_session

        identities = select(
            literal("identity"), cast(User.id, String),
            cast(func.json_build_array(User.role, User.subscription_plan), String), literal(True),
        ).where(User.id.in_(user_ids))
        statement = union_all(*_snapshot_query(keys).selects, identities)
        async with get_async_db_session() as db:
            rows = (await db.execute(statement)).all()
        subjects = {key: tuple(json.loads(value)) for kind, key, value, _ in rows if kind == "identity"}
        if set(subjects) != set(user_ids):
            raise LookupError("Entitlement owner no longer exists")
        return subjects, _blob_from_rows(rows)

    async def _snapshot_for_user(self, user: Any):
        # ORM instances can outlive a role/plan change; their ID is authoritative,
        # never the attributes retained by a request, task or identity cache.
        user_id = user if isinstance(user, str) else getattr(user, "id", None)
        if isinstance(user_id, str) and user_id:
            subjects, blob = await self._subject_snapshot((user_id,))
            role, plan = subjects[user_id]
            return role, plan, blob
        role, plan = await self._resolve_user_role_plan(user)
        return role, plan, await self._get_blob()

    async def has_feature(self, key: str, *, user: Any, db: AsyncSession | None = None) -> bool:
        """Resolve one capability without touching the caller's transaction.

        Administrative roles authorize the control plane, never bypass a product
        kill switch. Unknown keys cannot silently turn a typo into permission.
        """
        feature = get_feature(key)
        if feature is None:
            return False
        if not feature.gateable:
            return True
        try:
            role, plan, blob = await self._snapshot_for_user(user)
            return self._decide(blob, key, plan, role)
        except Exception:
            logger.warning("entitlement_service.has_feature(%s) unavailable", key, exc_info=True)
            return False

    async def has_feature_for_plan(self, key: str, *, user: Any, plan: str) -> bool:
        """Check a new offer with the current purchaser role and target SKU.

        This does not change the user's subscription or make its current free
        family a prerequisite for buying a permitted paid offer.
        """
        try:
            role, _, blob = await self._snapshot_for_user(user)
            return self._decide(blob, key, plan, role)
        except Exception:
            logger.warning("Target-plan entitlement unavailable", exc_info=True)
            return False

    async def users_have_feature(self, key: str, user_ids: tuple[str, ...]) -> bool:
        """Authorize collaboration participants from one small, uncached snapshot.

        Only the requested capability and ancestors are loaded, rather than the
        entire catalog for every WebSocket frame. Missing owners deny access.
        """
        feature = get_feature(key)
        if feature is None:
            return False
        if not feature.gateable:
            return True
        ids = set(user_ids)
        if not ids or any(not isinstance(user_id, str) or not user_id for user_id in ids):
            return False
        try:
            keys = tuple(item.key for item in feature_ancestry(key) if item.gateable)
            subjects, blob = await self._subject_snapshot(tuple(ids), keys)
            return all(self._decide(blob, key, plan, role) for role, plan in subjects.values())
        except Exception:
            logger.warning("Batch entitlement authorization unavailable", exc_info=True)
            return False

    def _decide(self, blob: dict, key: str, plan: Optional[str], role: Optional[str] = "anonymous") -> bool:
        """Intersect global, account-role, family, SKU and every ancestor grant."""
        feature = get_feature(key)
        if feature is None:
            return False
        if not feature.gateable:
            return True
        if role not in CAPABILITY_ROLES:
            return False
        normalized = (plan or "free").strip().lower()
        sku = PLAN_SKU_ALIASES.get(normalized, normalized)
        if sku not in PLAN_KEYS:
            return False
        family = resolve_plan_family(sku)
        try:
            for item in feature_ancestry(key):
                if not item.gateable:
                    continue
                if blob["roles"].get(role, {}).get(item.key) is not True:
                    return False
                if blob["kill"].get(item.key) is not True:
                    return False
                if blob["matrix"].get(family, {}).get(item.key) is not True:
                    return False
                if sku != family and blob["matrix"].get(sku, {}).get(item.key) is not True:
                    return False
            return True
        except (KeyError, TypeError, AttributeError, ValueError):
            return False

    async def _resolve_user_role_plan(
        self, user: Any
    ) -> tuple[Optional[str], Optional[str]]:
        """Return (role, subscription_plan) for a User object, id string, or None.

        For a user_id string, loads the row on a DEDICATED session so the
        caller's request transaction is untouched.
        """
        if user is None:
            return "anonymous", None

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
            raise LookupError("Entitlement owner no longer exists")

        raise TypeError("Unsupported entitlement owner")

    async def get_state(self, db: AsyncSession | None = None) -> dict:
        """Return the complete inventory and explicit family/SKU grant matrix."""
        blob = await self._get_blob()
        registry = [
            {"key": f.key, "label": f.label, "category": f.category,
             "description": f.description, "gateable": f.gateable,
             "parent_key": f.parent_key, "inventory_id": f.inventory_id,
             "always_on_reason": f.always_on_reason}
            for f in FEATURE_REGISTRY
        ]
        keys = [f.key for f in FEATURE_REGISTRY if f.gateable]
        return {
            "registry": registry,
            "kill_switches": {k: blob["kill"].get(k) is True for k in keys},
            "matrix": {p: {k: blob["matrix"].get(p, {}).get(k) is True for k in keys}
                       for p in PLAN_MATRIX_KEYS},
            "roles": list(CAPABILITY_ROLES),
            "role_matrix": {r: {k: blob["roles"].get(r, {}).get(k) is True for k in keys}
                            for r in CAPABILITY_ROLES},
            "plan_families": list(PLAN_FAMILIES),
            "plan_keys": list(PLAN_KEYS),
            "plan_family_by_key": {p: resolve_plan_family(p) for p in PLAN_KEYS},
        }

    async def _write_cell(
        self, model: Any, identity: dict, values: dict, db: AsyncSession,
        *, expected_enabled: bool | None = None,
    ) -> None:
        """Serialize a cell and optionally reject stale admin intent.

        Separate cells do not overwrite each other. The advisory lock also
        covers creation of a missing, fail-closed grant. Legacy API callers
        without a comparison retain explicit last-writer-wins compatibility.
        """
        from sqlalchemy.dialects.postgresql import insert

        lock_key = f"capability:{model.__tablename__}:" + ":".join(str(v) for v in identity.values())
        await db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(lock_key, 0))))
        if expected_enabled is not None:
            current = await db.scalar(select(model.enabled).filter_by(**identity))
            if (current is True) is not expected_enabled:
                await db.rollback()
                raise HTTPException(
                    status_code=409,
                    detail=error_body(
                        "capability_conflict",
                        "This control changed since you loaded it. Refresh and review the current setting.",
                        None,
                    ),
                )
        stmt = insert(model).values(**identity, **values).on_conflict_do_update(
            index_elements=[getattr(model, column) for column in identity],
            set_={"enabled": values["enabled"], "updated_at": datetime.now(timezone.utc)},
        )
        await db.execute(stmt)
        await db.commit()
        _clear_cache()

    async def set_kill_switch(
        self, key: str, enabled: bool, db: AsyncSession, *, expected_enabled: bool | None = None,
    ) -> None:
        """Atomically upsert an explicit product switch in the shared source."""
        feature = get_feature(key)
        if feature is None or not feature.gateable:
            raise KeyError(f"Unknown or non-gateable feature: {key!r}")
        await self._write_cell(
            FeatureFlag, {"key": key},
            {"enabled": enabled, "label": feature.label, "description": feature.description}, db,
            expected_enabled=expected_enabled,
        )

    async def set_matrix_cell(
        self, family: str, key: str, enabled: bool, db: AsyncSession, *, expected_enabled: bool | None = None,
    ) -> None:
        """Restrict a family or concrete SKU; child/SKU grants never override denial."""
        if family not in PLAN_MATRIX_KEYS:
            raise KeyError(f"Unknown plan family or SKU: {family!r}")
        if not is_gateable(key):
            raise KeyError(f"Unknown or non-gateable feature: {key!r}")
        await self._write_cell(
            PlanFeature, {"plan_family": family, "feature_key": key}, {"enabled": enabled}, db,
            expected_enabled=expected_enabled,
        )

    async def set_role_cell(
        self, role: str, key: str, enabled: bool, db: AsyncSession, *, expected_enabled: bool | None = None,
    ) -> None:
        """Role restrictions narrow product use without granting administrative authority."""
        if role not in CAPABILITY_ROLES:
            raise KeyError(f"Unknown account role/context: {role!r}")
        if not is_gateable(key):
            raise KeyError(f"Unknown or non-gateable feature: {key!r}")
        await self._write_cell(
            RoleFeature, {"role": role, "feature_key": key}, {"enabled": enabled}, db,
            expected_enabled=expected_enabled,
        )

    async def effective_snapshot(self, user: Any, db: AsyncSession | None = None) -> dict:
        """Return grants plus availability without disguising an outage as a plan limit."""
        available = True
        try:
            role, plan, blob = await self._snapshot_for_user(user)
        except Exception:
            logger.warning("entitlement_service.effective_features unavailable", exc_info=True)
            blob, role, plan, available = self._empty_blob(), None, None, False
        return {
            "features": {f.key: self._decide(blob, f.key, plan, role) for f in FEATURE_REGISTRY},
            "available": available,
        }

    async def effective_features(self, user: Any, db: AsyncSession | None = None) -> dict[str, bool]:
        """Compatibility map; unknown optional features fail closed on lookup failure."""
        return (await self.effective_snapshot(user, db))["features"]

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
        job_id: Optional[str] = None,
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
        # Validate the dimension first, then resolve the current versioned limit.
        # Windows/counter keys never change during an admin limit edit, so old
        # usage and every refund receipt keep their original accounting identity.
        limit = get_plan_quota(plan, dimension)
        window = get_plan_quota_window(plan, dimension)
        try:
            from .quota_policy_service import resolve_quota_policy

            limit, window = await resolve_quota_policy(plan, dimension)
        except Exception:
            logger.warning("Quota policy unavailable", exc_info=True)
            return QuotaTicket(
                dimension=dimension, user_id=user_id, period=_current_period(window),
                used=0, limit=limit, allowed=False, unavailable=True,
                window=window, job_id=job_id,
            )
        period = _current_period(window)
        key = f"latexy:quota:{dimension}:{user_id}:{period}"
        receipt_id = uuid.uuid4().hex
        receipt_key = f"latexy:quota-refund-pending:{job_id}" if job_id else None
        receipt_payload = json.dumps(
            {
                "dimension": dimension,
                "user_id": user_id,
                "period": period,
                "cost": cost,
                "receipt_id": receipt_id,
                "created_at": time.time(),
            }
        )

        try:
            from ..core.redis import get_redis_cache_client

            redis = await get_redis_cache_client()
            # ``-1`` means this exact increment was rejected and restored by
            # the Lua script. Unlimited plans pass -1 as their script limit.
            eval_args = [cost, _QUOTA_TTL, limit if limit is not None else -1, receipt_payload]
            if receipt_key:
                eval_args.insert(0, receipt_key)
            raw_used = int(await redis.eval(_CONSUME_WITH_TTL, 2 if receipt_key else 1, key, *eval_args))
            if raw_used < 0:
                used = limit or 0
            else:
                used = raw_used
        except Exception as exc:
            # Nothing to meter on an unlimited plan → the counter is pure
            # reporting, so let the request through instead of manufacturing an
            # outage on endpoints that have no other Redis dependency.
            fail_open = limit is None
            logger.error(
                "Quota counter unavailable, failing %s",
                "open (unlimited plan)" if fail_open else "closed",
                extra={"error_type": type(exc).__name__},
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
                receipt_id=receipt_id,
                job_id=job_id,
            )

        allowed = limit is None or raw_used >= 0

        return QuotaTicket(
            dimension=dimension,
            user_id=user_id,
            period=period,
            used=used,
            limit=limit,
            allowed=allowed,
            window=window,
            receipt_id=receipt_id,
            job_id=job_id,
        )

    async def refund_quota(self, ticket: QuotaTicket, cost: int = 1) -> bool:
        """Give back units consumed by a ticket whose work never happened.

        Called when the metered spend is abandoned AFTER consumption (queue
        submit failed, LLM call errored). Best-effort: a lost refund only ever
        costs the user one unit, whereas a lost consumption costs us money.
        """
        if ticket.unavailable:
            # No counter increment was confirmed, so there is nothing to
            # compensate.  Treat this as successful cleanup for callers that
            # gate receipt removal on the return value.
            return True
        key = f"latexy:quota:{ticket.dimension}:{ticket.user_id}:{ticket.period}"
        # Background jobs use the same job-scoped marker as the worker-side
        # refund path.  This closes the enqueue exception race where a worker
        # can terminalize and refund a task while the submitting process is
        # still deciding whether to compensate its own failed dispatch call.
        # Synchronous callers retain receipt-scoped idempotency.
        marker_key = (
            f"latexy:quota-refund:{ticket.dimension}:{ticket.job_id}"
            if ticket.job_id
            else (
                f"latexy:quota-refund:{ticket.dimension}:{ticket.user_id}:"
                f"{ticket.period}:{ticket.receipt_id}"
            )
        )
        # A refund is compensating work and can be reached by multiple
        # exception/cancellation paths. SET-NX makes it exactly-once per
        # consumption receipt; clamping at zero prevents an oversized or
        # duplicated refund from creating a negative balance that bypasses the
        # quota on later requests. Both operations are one atomic script.
        refund_script = """
        if not redis.call('SET', KEYS[2], '1', 'NX', 'EX', ARGV[2]) then
          return 0
        end
        local current = tonumber(redis.call('GET', KEYS[1]) or '0')
        local refund = tonumber(ARGV[1])
        if current <= 0 then
          return 1
        elseif current <= refund then
          redis.call('SET', KEYS[1], '0', 'KEEPTTL')
        else
          redis.call('DECRBY', KEYS[1], refund)
        end
        return 1
        """
        try:
            from ..core.redis import get_redis_cache_client

            redis = await get_redis_cache_client()
            # A zero result means the marker already existed: the prior refund
            # completed atomically, so it is still safe to remove the receipt.
            await redis.eval(refund_script, 2, key, marker_key, cost, _QUOTA_TTL)
            if ticket.job_id:
                await redis.delete(f"latexy:quota-refund-pending:{ticket.job_id}")
            return True
        except Exception:
            logger.warning("Quota refund failed for %s", key, exc_info=True)
            # Keep a job-scoped pending receipt on failure.  Cleanup/recovery
            # can retry it after Redis becomes available.
            return False

    async def enforce_quota(
        self,
        dimension: str,
        *,
        user_id: str,
        plan: Optional[str],
        cost: int = 1,
        job_id: Optional[str] = None,
    ) -> QuotaTicket:
        """Consume quota and raise the standard error envelope when denied.

        402 Payment Required when the plan's allowance is spent (the client's cue
        to show an upgrade prompt); 503 when the counter store is down.
        """
        ticket = await self.consume_quota(
            dimension, user_id=user_id, plan=plan, cost=cost, job_id=job_id
        )
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
        from .quota_policy_service import quota_policy_service

        policy_available = True
        try:
            policies = await quota_policy_service.resolve(plan)
        except Exception:
            # Keep billing/history reads available. Unknown limits are reported
            # explicitly, never represented as an unlimited allowance.
            policy_available = False
            policies = {d: {"limit": 0, "window": get_plan_quota_window(plan, d)} for d in QUOTA_DIMENSIONS}
            logger.warning("Quota snapshot policy unavailable", exc_info=True)
        windows = {d: policies[d]["window"] for d in QUOTA_DIMENSIONS}
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
            logger.warning(
                "Quota snapshot unavailable for %s",
                user_id,
                extra={"error_type": type(exc).__name__},
            )

        # Top-level period/resets_at describe the monthly billing window; each
        # dimension carries its own because the windows differ per plan.
        month_period = _current_period("month")
        return {
            "period": month_period,
            "resets_at": _period_reset_at(month_period),
            "policy_available": policy_available,
            "dimensions": {
                dimension: {
                    "used": counts[dimension],
                    "limit": policies[dimension]["limit"],
                    "policy_available": policy_available,
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

    def sync_has_feature(self, key: str, plan_family: str, *, user_id: str | None = None) -> bool:
        """Worker authorization uses the same DB source, never an old Redis grant."""
        feature = get_feature(key)
        if feature is None:
            return False
        if not feature.gateable:
            return True
        try:
            blob = self._sync_get_blob(user_id=user_id) if user_id else self._sync_get_blob()
            role, plan = blob["identity"] if user_id else ("anonymous", plan_family)
            return self._decide(blob, key, plan, role)
        except Exception:
            logger.warning("sync_has_feature(%s) unavailable", key, exc_info=True)
            return False

    def _sync_get_blob(self, *, user_id: str | None = None) -> dict:
        import psycopg2
        from sqlalchemy.engine import make_url

        from ..core.config import settings

        url = make_url(settings.DATABASE_URL).set(drivername="postgresql")
        query = dict(url.query)
        if "ssl" in query:
            query["sslmode"] = query.pop("ssl")
        url = url.set(query=query)
        # This short-lived read-only connection cannot mutate a worker's request
        # transaction or reuse an event-loop-bound async engine.
        connection = psycopg2.connect(
            url.render_as_string(hide_password=False), connect_timeout=2,
            options="-c statement_timeout=2000 -c default_transaction_read_only=on",
        )
        try:
            connection.set_session(isolation_level="REPEATABLE READ", readonly=True)
            with connection.cursor() as cursor:
                identity = None
                if user_id is not None:
                    cursor.execute("SELECT role, subscription_plan FROM users WHERE id = %s", (user_id,))
                    identity = cursor.fetchone()
                    if identity is None:
                        raise LookupError("Entitlement owner no longer exists")
                cursor.execute(
                    "SELECT 'kill', key, '', enabled FROM feature_flags "
                    "UNION ALL SELECT 'matrix', feature_key, plan_family, enabled FROM plan_features "
                    "UNION ALL SELECT 'role', feature_key, role, enabled FROM role_features"
                )
                blob = _blob_from_rows(cursor.fetchall())
                if identity is not None:
                    blob["identity"] = identity
                return blob
        finally:
            connection.close()


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
