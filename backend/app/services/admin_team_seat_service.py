"""Admin-only team-seat utilization and invite-to-active analytics (issue #2110).

The report is read-only and aggregate-only. It is derived from the existing
``team_seats``, ``users``, ``subscriptions``, ``tenants`` and ``tenant_members``
tables, so no migration or new ledger is required.

Invitee emails and invitee account ids are never selected. Per-owner rows are
aggregates over that owner's seats and are withheld below the five-seat
publication floor. Tenant rows aggregate only the seats of the tenant's owner
and never mix seats from another tenant. Subscription state is reduced to the
plan, status and current period end; provider ids and payment data are out of
scope.
"""

from __future__ import annotations

import statistics
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..database import models

TeamSeat = models.TeamSeat
User = models.User
Subscription = models.Subscription
Tenant = models.Tenant
TenantMember = models.TenantMember

MIN_GROUP_SIZE = 5
MAX_RANGE_DAYS = 366
MAX_SEATS = 100_000
AGING_THRESHOLDS = (7, 14, 30)
TEAM_PLAN_FAMILIES = {"team", "team_member"}
ACTIVE_SUBSCRIPTION_STATUSES = {
    "active",
    "cancel_scheduled",
    "past_due",
    "on_hold",
    "paused",
}


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _pct(value: int | float, total: int | float) -> float | None:
    if total <= 0:
        return None
    return round((float(value) / float(total)) * 100, 2)


def _resolve_period(
    *,
    days: int,
    start_date: date | None,
    end_date: date | None,
    now: datetime | None = None,
) -> tuple[datetime, datetime, int]:
    """Return the UTC [start, end) bounds and the inclusive calendar length."""

    current = now or datetime.now(timezone.utc)
    if end_date is not None:
        end_at = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=timezone.utc)
    else:
        end_at = current
    if start_date is not None:
        start_at = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
    else:
        start_at = end_at - timedelta(days=days)
    if start_at >= end_at:
        raise ValueError("start_date must be before end_date")
    if end_at - start_at > timedelta(days=MAX_RANGE_DAYS):
        raise ValueError("date range cannot exceed 366 days")
    selected_days = max(1, (end_at - start_at).days)
    return start_at, end_at, selected_days


def _validate_uuid(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a valid UUID") from exc


def _bucket(status: str | None) -> str:
    normalized = (status or "").strip().lower()
    if normalized in {"active", "accepted"}:
        return "active"
    if normalized in {"invited", "pending"}:
        return "pending"
    if normalized == "removed":
        return "removed"
    return "other"


def _team_plan_active(owner_plan: str, subscription: dict[str, Any] | None) -> bool:
    if owner_plan in TEAM_PLAN_FAMILIES:
        return True
    return bool(
        subscription is not None
        and subscription.get("plan_id") in TEAM_PLAN_FAMILIES
        and subscription.get("status") in ACTIVE_SUBSCRIPTION_STATUSES
    )


@dataclass(frozen=True)
class _Seat:
    owner_user_id: str
    status: str
    accepted: bool
    invited_at: datetime | None
    joined_at: datetime | None


@dataclass
class _Stats:
    seats: int = 0
    accepted_ever: int = 0
    active: int = 0
    pending: int = 0
    removed: int = 0
    other: int = 0
    invited_total: int = 0
    invited_accepted: int = 0
    invited_active: int = 0
    invited_pending: int = 0
    invited_removed: int = 0
    invited_other: int = 0
    accept_seconds: list[float] = field(default_factory=list)
    aging: dict[int, int] = field(default_factory=lambda: {threshold: 0 for threshold in AGING_THRESHOLDS})
    oldest_pending_days: int = 0

    def add_current(self, seat: _Seat, now: datetime) -> None:
        self.seats += 1
        bucket = _bucket(seat.status)
        setattr(self, bucket, getattr(self, bucket) + 1)
        if seat.accepted:
            self.accepted_ever += 1
        if bucket != "pending":
            return
        invited = _as_utc(seat.invited_at)
        if invited is None:
            return
        age_days = max(0, int((now - invited).total_seconds() // 86400))
        self.oldest_pending_days = max(self.oldest_pending_days, age_days)
        for threshold in AGING_THRESHOLDS:
            if age_days > threshold:
                self.aging[threshold] += 1

    def add_period(self, seat: _Seat, start_at: datetime, end_at: datetime) -> None:
        invited = _as_utc(seat.invited_at)
        if invited is None or not (start_at <= invited < end_at):
            return
        self.invited_total += 1
        bucket = _bucket(seat.status)
        setattr(self, f"invited_{bucket}", getattr(self, f"invited_{bucket}") + 1)
        if seat.accepted:
            self.invited_accepted += 1
        joined = _as_utc(seat.joined_at)
        if seat.accepted and joined is not None:
            self.accept_seconds.append(max(0.0, (joined - invited).total_seconds()))

    def merge(self, other: "_Stats") -> None:
        for name in (
            "seats",
            "accepted_ever",
            "active",
            "pending",
            "removed",
            "other",
            "invited_total",
            "invited_accepted",
            "invited_active",
            "invited_pending",
            "invited_removed",
            "invited_other",
        ):
            setattr(self, name, getattr(self, name) + getattr(other, name))
        self.accept_seconds.extend(other.accept_seconds)
        for threshold in AGING_THRESHOLDS:
            self.aging[threshold] += other.aging.get(threshold, 0)
        self.oldest_pending_days = max(self.oldest_pending_days, other.oldest_pending_days)

    def median_accept_hours(self) -> float | None:
        if len(self.accept_seconds) < MIN_GROUP_SIZE:
            return None
        return round(statistics.median(self.accept_seconds) / 3600, 2)


@dataclass(frozen=True)
class _Tenant:
    id: str
    name: str
    plan_id: str
    max_members: int
    owner_id: str
    created_at: datetime | None


def _tenant_from_row(row: Any) -> _Tenant:
    tenant_id, name, plan_id, max_members, owner_id, created_at = row
    return _Tenant(
        id=str(tenant_id),
        name=str(name or "Unnamed tenant"),
        plan_id=str(plan_id or "agency"),
        max_members=int(max_members or 0),
        owner_id=str(owner_id),
        created_at=_as_utc(created_at),
    )


def _aging_payload(stats: _Stats) -> dict[str, Any]:
    return {
        "pending": stats.pending,
        "over_7_days": stats.aging.get(7, 0),
        "over_14_days": stats.aging.get(14, 0),
        "over_30_days": stats.aging.get(30, 0),
        "oldest_pending_days": stats.oldest_pending_days,
    }


def _current_payload(stats: _Stats, *, owner_count: int, seat_cap: int) -> dict[str, Any]:
    capacity = max(0, owner_count * seat_cap)
    return {
        "owners": owner_count,
        "seats": stats.seats,
        "accepted_ever": stats.accepted_ever,
        "active": stats.active,
        "pending": stats.pending,
        "removed": stats.removed,
        "other": stats.other,
        "seat_cap": seat_cap,
        "seat_capacity": capacity,
        "utilization_pct": _pct(stats.active, capacity),
        "over_capacity": max(0, stats.active - capacity),
        "at_or_over_cap": capacity > 0 and stats.active >= capacity,
        "aging_invites": _aging_payload(stats),
    }


def _invitation_payload(stats: _Stats) -> dict[str, Any]:
    return {
        "invited": stats.invited_total,
        "accepted_ever": stats.invited_accepted,
        "active_now": stats.invited_active,
        "pending_now": stats.invited_pending,
        "removed_now": stats.invited_removed,
        "other_now": stats.invited_other,
        "invite_to_accept_pct": _pct(stats.invited_accepted, stats.invited_total),
        "invite_to_active_pct": _pct(stats.invited_active, stats.invited_total),
        "median_accept_hours": stats.median_accept_hours(),
        "accept_samples": len(stats.accept_seconds),
        "median_accept_suppressed": 0 < len(stats.accept_seconds) < MIN_GROUP_SIZE,
    }


def _invitation_visible(stats: _Stats) -> bool:
    return stats.invited_total == 0 or stats.invited_total >= MIN_GROUP_SIZE


def _seats_visible(stats: _Stats) -> bool:
    return stats.seats == 0 or stats.seats >= MIN_GROUP_SIZE


async def _load_tenants(
    db: AsyncSession,
    owner_ids: Iterable[str],
) -> tuple[dict[str, _Tenant], dict[str, int], dict[str, int]]:
    """Return primary tenant per owner, tenant details and multi-tenant counts.

    An owner is attributed to at most one owned tenant so seat totals never
    duplicate across tenant rows. The earliest created tenant wins. Counts of
    owners with more than one tenant are returned only as an aggregate
    reconciliation value.
    """

    ids = [str(owner_id) for owner_id in dict.fromkeys(owner_ids)]
    if not ids:
        return {}, {}, {}

    owned_rows = (
        await db.execute(
            select(
                Tenant.id,
                Tenant.name,
                Tenant.plan_id,
                Tenant.max_members,
                Tenant.owner_id,
                Tenant.created_at,
            )
            .where(Tenant.owner_id.in_(ids))
            .order_by(Tenant.created_at.asc(), Tenant.id.asc())
        )
    ).all()

    candidates: dict[str, list[_Tenant]] = defaultdict(list)
    for row in owned_rows:
        tenant = _tenant_from_row(row)
        candidates[tenant.owner_id].append(tenant)

    primary: dict[str, _Tenant] = {}
    details: dict[str, _Tenant] = {}
    multi_tenant_counts: dict[str, int] = {}
    for owner_id, tenants in candidates.items():
        unique = {tenant.id: tenant for tenant in tenants}
        if not unique:
            continue
        ordered = sorted(
            unique.values(),
            key=lambda tenant: (
                tenant.created_at or datetime.max.replace(tzinfo=timezone.utc),
                tenant.id,
            ),
        )
        primary[owner_id] = ordered[0]
        details[ordered[0].id] = ordered[0]
        if len(unique) > 1:
            multi_tenant_counts[owner_id] = len(unique)
    return primary, details, multi_tenant_counts


async def _load_subscriptions(
    db: AsyncSession,
    owner_ids: Iterable[str],
) -> dict[str, dict[str, Any]]:
    ids = [str(owner_id) for owner_id in dict.fromkeys(owner_ids)]
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(
                Subscription.user_id,
                Subscription.plan_id,
                Subscription.status,
                Subscription.current_period_end,
                Subscription.created_at,
            )
            .where(Subscription.user_id.in_(ids))
            .order_by(Subscription.user_id.asc(), Subscription.created_at.desc(), Subscription.id.desc())
        )
    ).all()
    latest: dict[str, dict[str, Any]] = {}
    for user_id, plan_id, status, period_end, created_at in rows:
        uid = str(user_id)
        if uid in latest:
            continue
        latest[uid] = {
            "plan_id": str(plan_id or "unknown"),
            "status": str(status or "unknown"),
            "current_period_end": _as_utc(period_end).isoformat() if period_end else None,
            "created_at": _as_utc(created_at).isoformat() if created_at else None,
        }
    return latest


async def _load_tenant_member_counts(db: AsyncSession, tenant_ids: Iterable[str]) -> dict[str, int]:
    ids = [str(tenant_id) for tenant_id in dict.fromkeys(tenant_ids)]
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(TenantMember.tenant_id, func.count(TenantMember.user_id))
            .where(TenantMember.tenant_id.in_(ids))
            .group_by(TenantMember.tenant_id)
        )
    ).all()
    return {str(tenant_id): int(count or 0) for tenant_id, count in rows}


class AdminTeamSeatService:
    """Read-only team-seat utilization report for the Revenue tab."""

    async def snapshot(
        self,
        db: AsyncSession,
        *,
        days: int = 30,
        start_date: date | None = None,
        end_date: date | None = None,
        owner_id: str | None = None,
        tenant_id: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        start_at, end_at, selected_days = _resolve_period(
            days=days,
            start_date=start_date,
            end_date=end_date,
            now=now,
        )
        owner_filter = _validate_uuid(owner_id, "owner_id")
        tenant_filter = _validate_uuid(tenant_id, "tenant_id")
        current_time = _as_utc(now) or datetime.now(timezone.utc)

        tenant_focus: _Tenant | None = None
        if tenant_filter is not None:
            row = (
                await db.execute(
                    select(
                        Tenant.id,
                        Tenant.name,
                        Tenant.plan_id,
                        Tenant.max_members,
                        Tenant.owner_id,
                        Tenant.created_at,
                    ).where(Tenant.id == tenant_filter)
                )
            ).first()
            if row is None:
                raise ValueError("tenant_id was not found")
            tenant_focus = _tenant_from_row(row)

        seat_query = select(
            TeamSeat.owner_user_id,
            TeamSeat.status,
            (TeamSeat.member_user_id.is_not(None) | TeamSeat.joined_at.is_not(None)).label("accepted"),
            TeamSeat.invited_at,
            TeamSeat.joined_at,
        ).order_by(TeamSeat.invited_at.asc(), TeamSeat.id.asc())
        if owner_filter is not None:
            seat_query = seat_query.where(TeamSeat.owner_user_id == owner_filter)
        if tenant_focus is not None:
            # Tenant ownership is the isolation boundary. A tenant report never
            # includes seats owned by another tenant's owner.
            seat_query = seat_query.where(TeamSeat.owner_user_id == tenant_focus.owner_id)

        seat_rows = (await db.execute(seat_query.limit(MAX_SEATS + 1))).all()
        rows_truncated = len(seat_rows) > MAX_SEATS
        seat_rows = seat_rows[:MAX_SEATS]

        if tenant_focus is not None:
            seat_rows = [row for row in seat_rows if str(row[0]) == tenant_focus.owner_id]

        seats = [
            _Seat(
                owner_user_id=str(owner_user_id),
                status=str(status or ""),
                accepted=bool(accepted),
                invited_at=_as_utc(invited_at),
                joined_at=_as_utc(joined_at),
            )
            for owner_user_id, status, accepted, invited_at, joined_at in seat_rows
        ]
        seat_owner_ids = {seat.owner_user_id for seat in seats}

        owner_rows: list[Any] = []
        if seat_owner_ids:
            owner_rows = (
                await db.execute(
                    select(User.id, User.subscription_plan, User.subscription_status).where(User.id.in_(seat_owner_ids))
                )
            ).all()
        owners = {
            str(user_id): {
                "plan": str(plan or "unknown"),
                "status": str(status or "unknown"),
            }
            for user_id, plan, status in owner_rows
        }

        primary_tenant, tenant_details, multi_tenant_counts = await _load_tenants(db, seat_owner_ids)
        if tenant_focus is not None:
            # Only the tenant's primary owner is included, so a tenant-filtered
            # report is an exact subset of the global report and never mixes
            # another tenant's seats.
            allowed_owners = {
                owner
                for owner, tenant in primary_tenant.items()
                if tenant.id == tenant_focus.id and tenant.owner_id == owner
            }
            seats = [seat for seat in seats if seat.owner_user_id in allowed_owners]
            seat_owner_ids = allowed_owners
            primary_tenant = {owner: tenant_focus for owner in allowed_owners}
            tenant_details = {tenant_focus.id: tenant_focus}
            multi_tenant_counts = {
                owner: count for owner, count in multi_tenant_counts.items() if owner in allowed_owners
            }
        subscriptions = await _load_subscriptions(db, seat_owner_ids)

        stats_by_owner: dict[str, _Stats] = defaultdict(_Stats)
        for seat in seats:
            stats = stats_by_owner[seat.owner_user_id]
            stats.add_current(seat, current_time)
            stats.add_period(seat, start_at, end_at)

        owner_records: list[dict[str, Any]] = []
        suppressed_owner_rows = 0
        suppressed_invitation_sections = 0
        for owner, stats in stats_by_owner.items():
            if stats.seats < MIN_GROUP_SIZE:
                suppressed_owner_rows += 1
                continue
            owner_plan = owners.get(owner, {}).get("plan", "unknown")
            owner_subscription_status = owners.get(owner, {}).get("status", "unknown")
            subscription = subscriptions.get(owner)
            team_plan_active = _team_plan_active(owner_plan, subscription)
            tenant = primary_tenant.get(owner)
            invitation_visible = _invitation_visible(stats)
            if not invitation_visible:
                suppressed_invitation_sections += 1
            owner_records.append(
                {
                    "owner_user_id": owner,
                    "owner_plan": owner_plan,
                    "owner_subscription_status": owner_subscription_status,
                    "team_plan_active": team_plan_active,
                    "subscription": subscription,
                    "tenant": (
                        {
                            "tenant_id": tenant.id,
                            "tenant_name": tenant.name,
                            "tenant_plan_id": tenant.plan_id,
                            "tenant_max_members": tenant.max_members,
                        }
                        if tenant is not None
                        else None
                    ),
                    "current": _current_payload(
                        stats,
                        owner_count=1,
                        seat_cap=settings.TEAM_PLAN_MAX_SEATS,
                    ),
                    "invitations": _invitation_payload(stats) if invitation_visible else None,
                    "invitation_suppressed": not invitation_visible,
                }
            )
        owner_records.sort(
            key=lambda row: (
                -int(row["current"]["active"]),
                -int(row["current"]["seats"]),
                str(row["owner_user_id"]),
            )
        )

        tenant_stats: dict[str, _Stats] = defaultdict(_Stats)
        tenant_owner_counts: dict[str, int] = defaultdict(int)
        unassigned_owner_ids: set[str] = set()
        for owner, stats in stats_by_owner.items():
            tenant = primary_tenant.get(owner)
            if tenant is None:
                unassigned_owner_ids.add(owner)
                continue
            tenant_stats[tenant.id].merge(stats)
            tenant_owner_counts[tenant.id] += 1

        tenant_ids_for_members = list(tenant_details)
        member_counts = await _load_tenant_member_counts(db, tenant_ids_for_members)
        tenant_records: list[dict[str, Any]] = []
        suppressed_tenant_rows = 0
        suppressed_seat_sections = 0
        for tenant_id, tenant in tenant_details.items():
            stats = tenant_stats.get(tenant_id, _Stats())
            members = member_counts.get(tenant_id, 0)
            if 0 < stats.seats < MIN_GROUP_SIZE and members < MIN_GROUP_SIZE:
                suppressed_tenant_rows += 1
                continue
            seat_visible = _seats_visible(stats)
            member_visible = members == 0 or members >= MIN_GROUP_SIZE
            if not seat_visible:
                suppressed_seat_sections += 1
            tenant_records.append(
                {
                    "tenant_id": tenant.id,
                    "tenant_name": tenant.name,
                    "tenant_plan_id": tenant.plan_id,
                    "tenant_max_members": tenant.max_members,
                    "team_owners": tenant_owner_counts.get(tenant_id, 0),
                    "team_seat_cap": tenant_owner_counts.get(tenant_id, 0) * settings.TEAM_PLAN_MAX_SEATS,
                    "current": (
                        _current_payload(
                            stats,
                            owner_count=tenant_owner_counts.get(tenant_id, 0),
                            seat_cap=settings.TEAM_PLAN_MAX_SEATS,
                        )
                        if seat_visible
                        else None
                    ),
                    "invitations": (
                        _invitation_payload(stats) if seat_visible and _invitation_visible(stats) else None
                    ),
                    "seat_section_suppressed": not seat_visible,
                    "tenant_members": (
                        {
                            "active_members": members,
                            "member_cap": tenant.max_members,
                            "utilization_pct": _pct(members, tenant.max_members),
                            "at_or_over_cap": tenant.max_members > 0 and members >= tenant.max_members,
                        }
                        if member_visible
                        else None
                    ),
                    "member_section_suppressed": not member_visible,
                }
            )
        tenant_records.sort(
            key=lambda row: (
                -int((row["current"] or {}).get("active") or 0),
                -int((row["current"] or {}).get("seats") or 0),
                str(row["tenant_name"]),
            )
        )

        summary_stats = _Stats()
        for stats in stats_by_owner.values():
            summary_stats.merge(stats)
        team_plan_active_owners = {
            owner
            for owner in stats_by_owner
            if _team_plan_active(
                owners.get(owner, {}).get("plan", "unknown"),
                subscriptions.get(owner),
            )
        }
        team_plan_owners = len(team_plan_active_owners)

        summary_visible = _seats_visible(summary_stats)
        invitation_visible = _invitation_visible(summary_stats)
        summary = {
            "current": (
                _current_payload(
                    summary_stats,
                    owner_count=len(stats_by_owner),
                    seat_cap=settings.TEAM_PLAN_MAX_SEATS,
                )
                if summary_visible
                else None
            ),
            "invitations": _invitation_payload(summary_stats) if invitation_visible else None,
            "team_plan_owners": team_plan_owners,
            "inactive_plan_owners_with_seats": len(stats_by_owner) - team_plan_owners,
            "owners_at_or_over_cap": sum(
                1 for stats in stats_by_owner.values() if stats.active >= settings.TEAM_PLAN_MAX_SEATS
            ),
        }

        owner_seat_total = sum(stats.seats for stats in stats_by_owner.values())
        tenant_seat_total = sum(stats.seats for stats in tenant_stats.values())
        unassigned_seat_total = sum(stats_by_owner[owner].seats for owner in unassigned_owner_ids)
        period_bucket_total = sum(stats.invited_total for stats in stats_by_owner.values())
        period_counts_total = sum(
            stats.invited_active + stats.invited_pending + stats.invited_removed + stats.invited_other
            for stats in stats_by_owner.values()
        )
        checks = [
            {
                "key": "owner_seat_totals",
                "ok": sum(stats.seats for stats in stats_by_owner.values()) == summary_stats.seats,
            },
            {
                "key": "current_status_buckets",
                "ok": (
                    summary_stats.active + summary_stats.pending + summary_stats.removed + summary_stats.other
                    == summary_stats.seats
                ),
            },
            {
                "key": "period_status_buckets",
                "ok": period_bucket_total == period_counts_total,
            },
            {
                "key": "tenant_seat_partition",
                "ok": tenant_seat_total + unassigned_seat_total == owner_seat_total,
            },
        ]

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "days": selected_days,
            "date_range": {
                "start": start_at.isoformat(),
                "end": end_at.isoformat(),
                "start_date": start_at.date().isoformat(),
                "end_date": (end_at - timedelta(microseconds=1)).date().isoformat(),
                "days": selected_days,
                "timezone": "UTC",
            },
            "filters": {
                "owner_id": owner_filter,
                "tenant_id": tenant_filter,
                "tenant_name": tenant_focus.name if tenant_focus else None,
                "days": selected_days,
                "start_date": start_at.date().isoformat(),
                "end_date": (end_at - timedelta(microseconds=1)).date().isoformat(),
                "timezone": "UTC",
            },
            "minimum_group_size": MIN_GROUP_SIZE,
            "suppressed": not summary_visible or summary["invitations"] is None,
            "suppression": {
                "minimum_group_size": MIN_GROUP_SIZE,
                "rule": (
                    "Owner rows below five seats are withheld; invitation counts and rates "
                    "below five invitations are suppressed; tenant seat sections below five "
                    "seats are suppressed unless tenant membership keeps the row publishable."
                ),
                "summary_suppressed": not summary_visible,
                "invitation_section_suppressed": summary["invitations"] is None,
                "suppressed_owner_rows": suppressed_owner_rows,
                "suppressed_tenant_rows": suppressed_tenant_rows,
                "suppressed_invitation_sections": suppressed_invitation_sections,
                "suppressed_seat_sections": suppressed_seat_sections,
            },
            "summary": summary,
            "owners": owner_records,
            "tenants": tenant_records,
            "reconciliation": {
                "source_tables": [
                    "team_seats",
                    "users",
                    "subscriptions",
                    "tenants",
                    "tenant_members",
                ],
                "seats_scanned": len(seat_rows),
                "seats_after_filters": owner_seat_total,
                "rows_truncated": rows_truncated,
                "owner_rows_published": len(owner_records),
                "tenant_rows_published": len(tenant_records),
                "owners_with_multiple_tenants": len(multi_tenant_counts),
                "subscriptions_scanned": len(subscriptions),
                "unassigned_owners": len(unassigned_owner_ids),
                "unassigned_seats": unassigned_seat_total,
                "tenant_attributed_seats": tenant_seat_total,
                "period_invitations": period_bucket_total,
                "period_bucket_total": period_counts_total,
                "checks": checks,
                "all_checks_passed": all(check["ok"] for check in checks),
            },
            "privacy": {
                "aggregate_only": True,
                "invitee_emails_included": False,
                "invitee_user_ids_included": False,
                "owner_user_ids_included": True,
                "tenant_ids_included": True,
                "fields_read": [
                    "team_seats.owner_user_id",
                    "team_seats.status",
                    "team_seats.invited_at",
                    "team_seats.joined_at",
                    "users.subscription_plan",
                    "users.subscription_status",
                    "subscriptions.plan_id",
                    "subscriptions.status",
                    "subscriptions.current_period_end",
                    "tenants.id",
                    "tenants.name",
                    "tenants.plan_id",
                    "tenants.max_members",
                    "tenants.owner_id",
                    "tenant_members.tenant_id",
                    "tenant_members.user_id (count only)",
                ],
                "fields_excluded": [
                    "team_seats.member_email",
                    "team_seats.member_user_id",
                    "user emails and names",
                    "invite tokens and URLs",
                    "payment and provider identifiers",
                    "document and prompt content",
                ],
            },
            "notes": [
                "Seat status is normalized to active, pending (invited), removed and other.",
                "Current utilization counts seats that are active now; period invitation rates count seats invited in the selected window.",
                "Aging invites are current pending invitations older than 7, 14 and 30 days.",
                "Median accept time uses accepted seats with both invited_at and joined_at in the selected invite window.",
                "An owner is attributed to at most one owned tenant (earliest created) so seats are not double-counted across tenant rows.",
                "A tenant filter is scoped to seats owned by that tenant's owner; invitee emails and member ids are never returned.",
                "Team seat capacity uses TEAM_PLAN_MAX_SEATS; tenant member capacity uses tenants.max_members.",
                "No migration is required: the report reads existing tables only.",
            ],
        }


admin_team_seat_service = AdminTeamSeatService()
