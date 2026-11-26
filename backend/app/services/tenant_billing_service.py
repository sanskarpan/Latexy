"""Read-only tenant billing and seat-utilization snapshot.

The tenant schema intentionally has no tenant-to-subscription link.  A
subscription is owned by a user, while a tenant is owned by a user too; joining
those two facts would guess that the owner's personal subscription pays for the
tenant.  This module therefore reports tenant plan/seats from explicit,
tenant-scoped rows and returns an explicit unavailable subscription state
instead of inventing a link.

Seat counts come from two existing, tenant-scoped sources:

* ``tenant_members`` for active/occupied seats.
* Pending ``tenant_invite:*`` cache entries for invited seats.

``team_seats`` is deliberately excluded: its rows are keyed by
``owner_user_id`` and carry no ``tenant_id``, so attributing them to a tenant
would be a guess.  No migration or new table is required.

The only mutation in this module is the opt-in upgrade-intent audit event.  It
is written to ``usage_analytics.event_metadata`` (JSONB) and contains aggregate
seat/plan facts only: no email, name, document, card or provider credential.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.redis import get_redis_cache_client
from ..database.models import Tenant, TenantMember, UsageAnalytics

logger = logging.getLogger(__name__)

# Display labels only. The authoritative seat cap is the tenant row's
# server-managed ``max_members`` value, never a client-supplied number.
TENANT_PLAN_LABELS: dict[str, str] = {"agency": "Agency", "university": "University"}
TENANT_PLAN_UPGRADES: dict[str, str] = {"agency": "university"}

UPGRADE_CTA_THRESHOLD_PERCENT = 80
MIN_CONVERSION_COHORT = 5
MAX_INVITE_SCAN = 5_000
INVITE_SCAN_BATCH = 100
UPGRADE_INTENT_ACTION = "tenant_billing_upgrade_intent"
UPGRADE_INTENT_RESOURCE = "tenant"

SUBSCRIPTION_UNAVAILABLE_REASON = "tenant_subscription_link_missing"
TEAM_SEAT_UNAVAILABLE_REASON = "owner_scoped_not_tenant_scoped"
SUBSCRIPTION_UNAVAILABLE_DETAIL = (
    "Subscriptions are user-scoped and the tenants table has no subscription "
    "identifier, so renewal and paid status cannot be attributed safely."
)
TEAM_SEAT_UNAVAILABLE_DETAIL = (
    "Team seats are keyed by the team owner and carry no tenant identifier, "
    "so they cannot be attributed to this tenant without guessing."
)


def _pct(value: int | float, total: int | float) -> float:
    if not total:
        return 0.0
    return round((float(value) / float(total)) * 100, 2)


def _as_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def compute_seat_usage(
    *, active: int, invited: int | None, max_seats: int
) -> dict[str, Any]:
    """Return deterministic seat arithmetic for one tenant.

    ``invited`` is ``None`` when the invitation store could not be read.  In
    that case ``available`` and ``used`` are based on active seats only and the
    response says so, rather than pretending there are no pending invites.
    """

    active_count = _as_int(active)
    max_count = _as_int(max_seats)
    invited_available = invited is not None
    invited_count = _as_int(invited)
    used = active_count + invited_count
    if not invited_available:
        used = active_count
    available = max(0, max_count - used)
    over_capacity = max(0, used - max_count)
    return {
        "active": active_count,
        "invited": invited_count if invited_available else None,
        "available": available,
        "used": used,
        "max": max_count,
        "utilization_percent": _pct(used, max_count),
        "over_capacity": over_capacity,
        "invited_available": invited_available,
        "invited_reason": None if invited_available else "invitation_store_unavailable",
        "basis": "active_and_invited" if invited_available else "active_only",
    }


def compute_invite_conversion(
    *, accepted_members: int, invited: int | None
) -> dict[str, Any]:
    """Current invited-to-accepted conversion with five-user suppression.

    Accepted counts exclude the tenant owner because the owner did not accept an
    invitation.  The denominator is accepted invitees plus currently pending
    invitations.  Counts and the rate are withheld when that denominator is
    below the five-user floor.
    """

    accepted = _as_int(accepted_members)
    if invited is None:
        return {
            "available": False,
            "reason": "invitation_store_unavailable",
            "minimum_cohort_size": MIN_CONVERSION_COHORT,
            "accepted": None,
            "invited": None,
            "conversion_percent": None,
        }
    pending = _as_int(invited)
    cohort = accepted + pending
    if cohort < MIN_CONVERSION_COHORT:
        return {
            "available": False,
            "reason": "suppressed_small_cohort",
            "minimum_cohort_size": MIN_CONVERSION_COHORT,
            "accepted": None,
            "invited": None,
            "conversion_percent": None,
        }
    return {
        "available": True,
        "reason": None,
        "minimum_cohort_size": MIN_CONVERSION_COHORT,
        "accepted": accepted,
        "invited": pending,
        "conversion_percent": _pct(accepted, cohort),
    }


def build_upgrade_prompt(
    *,
    plan_id: str,
    used_seats: int,
    max_seats: int,
    tenant_active: bool,
) -> dict[str, Any]:
    """Server-side upgrade threshold and target plan."""

    used = _as_int(used_seats)
    max_count = _as_int(max_seats)
    threshold_seats = (
        math.ceil(max_count * UPGRADE_CTA_THRESHOLD_PERCENT / 100)
        if max_count
        else 0
    )
    target_plan_id = TENANT_PLAN_UPGRADES.get(plan_id)
    target_name = TENANT_PLAN_LABELS.get(target_plan_id or "", target_plan_id)
    utilization = _pct(used, max_count)

    if not tenant_active:
        reason = "tenant_inactive"
    elif max_count <= 0:
        reason = "seat_limit_unavailable"
    elif target_plan_id is None:
        reason = "no_higher_tenant_plan"
    elif used < threshold_seats:
        reason = "below_threshold"
    else:
        reason = "seat_threshold_reached"

    visible = reason == "seat_threshold_reached"
    return {
        "cta_visible": visible,
        "threshold_percent": UPGRADE_CTA_THRESHOLD_PERCENT,
        "threshold_seats": threshold_seats,
        "utilization_percent": utilization,
        "target_plan_id": target_plan_id,
        "target_plan_name": target_name,
        "cta_label": f"Upgrade to {target_name}" if visible and target_name else None,
        "reason": reason,
    }


async def count_pending_invites(
    tenant_id: str, *, redis_client: Any | None = None
) -> tuple[int | None, str | None]:
    """Count live tenant invitations without exposing invitee details.

    Invitations are stored under ``tenant_invite:<token>`` with a seven-day TTL.
    The payload is parsed only to match the tenant id; email/role/cohort values
    never leave this function.  A Redis outage or an unexpectedly large scan is
    reported as unavailable so the rest of the billing view remains usable.
    """

    try:
        redis = redis_client or await get_redis_cache_client()
        keys: list[str] = []
        async for key in redis.scan_iter(match="tenant_invite:*", count=INVITE_SCAN_BATCH):
            keys.append(key.decode("utf-8", errors="replace") if isinstance(key, bytes) else str(key))
            if len(keys) > MAX_INVITE_SCAN:
                return None, "invitation_scan_limit"
        if not keys:
            return 0, None

        pending = 0
        for offset in range(0, len(keys), INVITE_SCAN_BATCH):
            batch = keys[offset : offset + INVITE_SCAN_BATCH]
            raw_values = await redis.mget(batch)
            for raw in raw_values or []:
                if raw is None:
                    continue
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")
                try:
                    payload = json.loads(raw)
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                if not isinstance(payload, dict):
                    continue
                if str(payload.get("tenant_id") or "") != str(tenant_id):
                    continue
                if payload.get("role") not in {"admin", "member"}:
                    continue
                pending += 1
        return pending, None
    except Exception as exc:  # pragma: no cover - exact client errors vary
        logger.warning(
            "Tenant billing invitation count unavailable for tenant %s (%s)",
            tenant_id,
            type(exc).__name__,
        )
        return None, "invitation_store_unavailable"


def _subscription_unavailable() -> dict[str, Any]:
    return {
        "available": False,
        "status": None,
        "renewal_at": None,
        "reason": SUBSCRIPTION_UNAVAILABLE_REASON,
        "detail": SUBSCRIPTION_UNAVAILABLE_DETAIL,
    }


def _mapping_state() -> dict[str, Any]:
    return {
        "seats": {
            "status": "derived",
            "source": "tenant_members+tenant_invitations",
        },
        "subscription": {
            "status": "unavailable",
            "reason": SUBSCRIPTION_UNAVAILABLE_REASON,
        },
        "team_seats": {
            "status": "unavailable",
            "reason": TEAM_SEAT_UNAVAILABLE_REASON,
            "detail": TEAM_SEAT_UNAVAILABLE_DETAIL,
        },
    }


async def build_tenant_billing_snapshot(
    db: AsyncSession,
    tenant: Tenant,
    *,
    now: datetime | None = None,
    redis_client: Any | None = None,
) -> dict[str, Any]:
    """Build the read-only billing view for an already-authorized tenant."""

    generated_at = now or datetime.now(timezone.utc)

    member_rows = (
        await db.execute(
            select(TenantMember.user_id, TenantMember.role).where(
                TenantMember.tenant_id == tenant.id
            )
        )
    ).all()
    active_seats = len(member_rows)
    accepted_members = sum(
        1 for row in member_rows if str(row.user_id) != str(tenant.owner_id)
    )

    invited, invite_reason = await count_pending_invites(
        str(tenant.id), redis_client=redis_client
    )
    seats = compute_seat_usage(
        active=active_seats, invited=invited, max_seats=tenant.max_members
    )
    if invite_reason and not seats["invited_available"]:
        seats["invited_reason"] = invite_reason

    conversion = compute_invite_conversion(
        accepted_members=accepted_members, invited=invited
    )
    upgrade = build_upgrade_prompt(
        plan_id=tenant.plan_id,
        used_seats=seats["used"],
        max_seats=tenant.max_members,
        tenant_active=bool(tenant.active),
    )

    plan_id = str(tenant.plan_id)
    return {
        "tenant_id": str(tenant.id),
        "generated_at": generated_at,
        "plan": {
            "plan_id": plan_id,
            "name": TENANT_PLAN_LABELS.get(plan_id, plan_id),
            "max_seats": _as_int(tenant.max_members),
            "tenant_status": "active" if tenant.active else "inactive",
            "status_source": "tenant_record",
        },
        "seats": seats,
        "invite_conversion": conversion,
        "subscription": _subscription_unavailable(),
        "upgrade": upgrade,
        "mapping": _mapping_state(),
    }


def _audit_metadata(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Allowlisted aggregate metadata for the upgrade-intent click."""

    seats = snapshot["seats"]
    upgrade = snapshot["upgrade"]
    plan = snapshot["plan"]
    return {
        "event_version": 1,
        "tenant_id": str(snapshot["tenant_id"]),
        "plan_id": str(plan["plan_id"]),
        "target_plan_id": upgrade["target_plan_id"],
        "max_seats": _as_int(seats["max"]),
        "used_seats": _as_int(seats["used"]),
        "active_seats": _as_int(seats["active"]),
        "invited_seats": None if seats["invited"] is None else _as_int(seats["invited"]),
        "utilization_percent": float(upgrade["utilization_percent"]),
        "threshold_percent": UPGRADE_CTA_THRESHOLD_PERCENT,
        "seat_basis": seats["basis"],
        "source": "tenant_billing_view",
    }


async def record_upgrade_intent(
    db: AsyncSession,
    tenant: Tenant,
    *,
    actor_user_id: str,
    now: datetime | None = None,
    redis_client: Any | None = None,
) -> dict[str, Any]:
    """Persist one audited upgrade-CTA click; never touches billing providers.

    The client cannot select the target plan or seat numbers: both are derived
    again from server-owned rows.  The click is refused unless the same
    threshold that renders the CTA is currently satisfied.
    """

    snapshot = await build_tenant_billing_snapshot(
        db, tenant, now=now, redis_client=redis_client
    )
    upgrade = snapshot["upgrade"]
    if not upgrade["cta_visible"]:
        raise ValueError("Upgrade prompt is not currently available")

    db.add(
        UsageAnalytics(
            user_id=actor_user_id,
            device_fingerprint=None,
            action=UPGRADE_INTENT_ACTION,
            resource_type=UPGRADE_INTENT_RESOURCE,
            event_metadata=_audit_metadata(snapshot),
            ip_address=None,
            user_agent=None,
        )
    )
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return {
        "recorded": True,
        "action": UPGRADE_INTENT_ACTION,
        "tenant_id": str(tenant.id),
        "target_plan_id": upgrade["target_plan_id"],
        "target_plan_name": upgrade["target_plan_name"],
        "threshold_percent": UPGRADE_CTA_THRESHOLD_PERCENT,
        "utilization_percent": upgrade["utilization_percent"],
        "message": "Upgrade request recorded for review",
    }
