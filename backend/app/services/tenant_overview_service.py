"""Aggregate-only tenant overview analytics.

The tenant dashboard needs seat, activation and submission rollups without
inferring institution ownership of private documents. This module therefore:

* reads only existing first-party tables (``tenants``, ``tenant_members``,
  ``workspaces``, ``workspace_members``, ``workspace_resumes`` and
  ``usage_analytics``) — no migration or new table is required;
* counts a submission only when a resume was explicitly shared into a
  tenant-owned cohort (``workspace_resumes``), never a personal document;
* returns aggregate counts and daily totals only, with no email, name, resume
  title, document content, cohort id or cohort name in the payload;
* suppresses itemised cohort rows below five members; only tenant-level totals
  include small cohorts, and the count of suppressed cohorts is reported.

Pending invitations are ephemeral Redis keys written by the existing invitation
flow. They are counted best-effort and never returned with their email payload.
A cache outage degrades the invitation count to zero and marks it unavailable
rather than failing the whole dashboard.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable, Mapping

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.redis import get_redis_cache_client
from ..database.models import (
    Resume,
    Tenant,
    TenantMember,
    UsageAnalytics,
    Workspace,
    WorkspaceMember,
    WorkspaceResume,
)

logger = logging.getLogger(__name__)

MINIMUM_COHORT_SIZE = 5
TREND_PERIODS: tuple[int, ...] = (7, 30, 90)
ACTIVE_MEMBERS_WINDOW_DAYS = 30
_MAX_INVITATION_KEYS = 5000


def _utc_day_start(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def _utc_day(column: Any) -> Any:
    """Group a timezone-aware timestamp by its UTC calendar date."""
    return func.date(func.timezone("UTC", column))


def _count_by_day(rows: Iterable[Any]) -> dict[date, int]:
    counts: dict[date, int] = {}
    for day, count in rows:
        if day is None:
            continue
        counts[day] = int(count or 0)
    return counts


async def _count_pending_invitations(tenant_id: str) -> tuple[int, bool]:
    """Count this tenant's live invitation keys without returning their payloads."""
    try:
        redis = await get_redis_cache_client()
        if redis is None:
            return 0, False
        count = 0
        scanned = 0
        truncated = False
        async for key in redis.scan_iter(match="tenant_invite:*", count=250):
            scanned += 1
            if scanned > _MAX_INVITATION_KEYS:
                truncated = True
                logger.warning(
                    "Tenant overview invitation scan truncated at %s keys",
                    _MAX_INVITATION_KEYS,
                )
                break
            raw = await redis.get(key)
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(payload, Mapping) and payload.get("tenant_id") == tenant_id:
                count += 1
        return count, not truncated
    except Exception as exc:  # pragma: no cover - cache outage path
        logger.warning(
            "Tenant overview invitation count unavailable (%s)",
            type(exc).__name__,
        )
        return 0, False


def _daily_points(
    members_joined: Mapping[date, int],
    submissions: Mapping[date, int],
    active_members: Mapping[date, int],
    today: date,
    days: int,
) -> list[dict[str, Any]]:
    start = today - timedelta(days=days - 1)
    points: list[dict[str, Any]] = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        points.append(
            {
                "date": day.isoformat(),
                "members_joined": int(members_joined.get(day, 0)),
                "submissions": int(submissions.get(day, 0)),
                "active_members": int(active_members.get(day, 0)),
            }
        )
    return points


async def build_tenant_overview(
    db: AsyncSession,
    tenant: Tenant,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the aggregate tenant overview payload for owner/admin reads.

    The caller must already have performed the owner/admin authorization check.
    """
    tenant_id = tenant.id
    current = now or datetime.now(timezone.utc)
    today = current.astimezone(timezone.utc).date()
    trend_start = _utc_day_start(today - timedelta(days=max(TREND_PERIODS) - 1))
    active_start = _utc_day_start(today - timedelta(days=ACTIVE_MEMBERS_WINDOW_DAYS - 1))

    member_rows = await db.execute(
        select(TenantMember.user_id).where(TenantMember.tenant_id == tenant_id)
    )
    member_ids = {row[0] for row in member_rows.all()}
    accepted_members = len(member_ids)

    cohort_result = await db.execute(
        select(Workspace.id).where(Workspace.tenant_id == tenant_id)
    )
    cohort_ids = [row[0] for row in cohort_result.all()]

    cohort_member_counts: dict[str, int] = {}
    cohort_submission_counts: dict[str, int] = {}
    cohort_count = len(cohort_ids)
    if cohort_ids:
        member_count_rows = await db.execute(
            select(WorkspaceMember.workspace_id, func.count())
            .where(WorkspaceMember.workspace_id.in_(cohort_ids))
            .group_by(WorkspaceMember.workspace_id)
        )
        cohort_member_counts = {
            workspace_id: int(count or 0)
            for workspace_id, count in member_count_rows.all()
        }
        submission_count_rows = await db.execute(
            select(WorkspaceResume.workspace_id, func.count())
            .where(WorkspaceResume.workspace_id.in_(cohort_ids))
            .group_by(WorkspaceResume.workspace_id)
        )
        cohort_submission_counts = {
            workspace_id: int(count or 0)
            for workspace_id, count in submission_count_rows.all()
        }

    cohort_members = sum(cohort_member_counts.values())
    submission_count = sum(cohort_submission_counts.values())
    cohorts_with_submissions = sum(
        1 for count in cohort_submission_counts.values() if count > 0
    )
    suppressed_cohorts = sum(
        1
        for cohort_id in cohort_ids
        if cohort_member_counts.get(cohort_id, 0) < MINIMUM_COHORT_SIZE
    )

    # Explicit submissions are the only document-derived activation source.
    # The joined Resume row supplies the submitting member id only (aggregate);
    # no title, content or student identity leaves this query.
    activation_result = await db.execute(
        select(
            func.count(),
            func.count(WorkspaceResume.opened_at),
            func.count(WorkspaceResume.downloaded_at),
            func.count(func.distinct(Resume.user_id)),
        )
        .select_from(WorkspaceResume)
        .join(Workspace, Workspace.id == WorkspaceResume.workspace_id)
        .join(Resume, Resume.id == WorkspaceResume.resume_id)
        .where(Workspace.tenant_id == tenant_id)
    )
    submitted, opened, downloaded, submitting_members = (
        int(value or 0) for value in activation_result.one()
    )
    activation_rate = (
        min(1.0, round(submitting_members / accepted_members, 4))
        if accepted_members
        else 0.0
    )

    member_day_expr = _utc_day(TenantMember.joined_at)
    member_day_rows = await db.execute(
        select(member_day_expr, func.count())
        .where(
            TenantMember.tenant_id == tenant_id,
            TenantMember.joined_at >= trend_start,
        )
        .group_by(member_day_expr)
    )
    members_joined_by_day = _count_by_day(member_day_rows.all())

    submission_day_expr = _utc_day(WorkspaceResume.shared_at)
    submission_day_rows = await db.execute(
        select(submission_day_expr, func.count())
        .join(Workspace, Workspace.id == WorkspaceResume.workspace_id)
        .where(
            Workspace.tenant_id == tenant_id,
            WorkspaceResume.shared_at >= trend_start,
        )
        .group_by(submission_day_expr)
    )
    submissions_by_day = _count_by_day(submission_day_rows.all())

    active_day_expr = _utc_day(UsageAnalytics.created_at)
    active_day_rows = await db.execute(
        select(
            active_day_expr,
            func.count(func.distinct(UsageAnalytics.user_id)),
        )
        .join(TenantMember, TenantMember.user_id == UsageAnalytics.user_id)
        .where(
            TenantMember.tenant_id == tenant_id,
            UsageAnalytics.user_id.is_not(None),
            UsageAnalytics.created_at >= trend_start,
        )
        .group_by(active_day_expr)
    )
    active_members_by_day = _count_by_day(active_day_rows.all())

    active_result = await db.execute(
        select(func.count(func.distinct(UsageAnalytics.user_id)))
        .join(TenantMember, TenantMember.user_id == UsageAnalytics.user_id)
        .where(
            TenantMember.tenant_id == tenant_id,
            UsageAnalytics.user_id.is_not(None),
            UsageAnalytics.created_at >= active_start,
        )
    )
    active_members = int(active_result.scalar() or 0)

    invited_members, pending_invites_available = await _count_pending_invitations(
        tenant_id
    )

    seat_limit = int(tenant.max_members or 0)
    seats_used = accepted_members
    seats_available = max(0, seat_limit - seats_used)
    seat_utilization = (
        round(seats_used / seat_limit, 4) if seat_limit > 0 else 0.0
    )

    trends = {
        str(period): _daily_points(
            members_joined_by_day,
            submissions_by_day,
            active_members_by_day,
            today,
            period,
        )
        for period in TREND_PERIODS
    }

    return {
        # Kept for callers that only read the original payload field.
        "member_count": accepted_members,
        "seats_used": seats_used,
        "seats_available": seats_available,
        "seat_limit": seat_limit,
        "seat_utilization": seat_utilization,
        "invited_members": invited_members,
        "pending_invites_available": pending_invites_available,
        "accepted_members": accepted_members,
        "active_members": active_members,
        "active_members_window_days": ACTIVE_MEMBERS_WINDOW_DAYS,
        "cohort_count": cohort_count,
        "cohort_member_count": cohort_members,
        "cohorts_with_submissions": cohorts_with_submissions,
        "submission_count": submission_count,
        "activation": {
            "submitted": submitted,
            "opened": opened,
            "downloaded": downloaded,
            "submitting_members": submitting_members,
            "activation_rate": activation_rate,
        },
        "trends": trends,
        "suppression": {
            "minimum_cohort_size": MINIMUM_COHORT_SIZE,
            "suppressed_cohorts": suppressed_cohorts,
            "cohort_breakdown_visible": False,
            "note": (
                "Cohorts below five members are included in tenant totals only "
                "and are never itemised."
            ),
        },
        "generated_at": current.isoformat(),
    }
