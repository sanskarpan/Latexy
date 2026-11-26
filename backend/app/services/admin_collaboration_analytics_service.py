"""Admin-only aggregate collaboration usage analytics.

The service reads the existing collaboration and tenancy tables only:

* ``resume_comments`` / ``resume_comment_mentions`` for workspace comments
* ``resume_review_comments`` for anonymous review-link feedback
* ``resume_views`` for review-capable share-link opens
* ``workspaces`` / ``workspace_members`` / ``workspace_resumes`` for cohorts
* ``tenants`` / ``tenant_members`` for tenant reconciliation

Only counts leave this module. Comment bodies, reviewer labels, author or
mentioned-user identifiers, emails, resume text and raw share tokens are never
selected into the response. Tenant and cohort rows below the five-member
threshold are suppressed together with every activity metric they carry.
"""

from __future__ import annotations

import math
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import and_, distinct, false, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import models

MIN_GROUP_SIZE = 5
MAX_RANGE_DAYS = 365
TIMEZONE = "UTC"

_REVIEW_CAPABILITY = func.coalesce(
    models.Resume.resume_settings["share_review_comments"].as_boolean(),
    false(),
).is_(True)


def _resolve_range(
    *,
    days: int,
    start_date: date | str | None,
    end_date: date | str | None,
) -> tuple[date, date, datetime, datetime]:
    """Return inclusive day bounds plus the UTC half-open event range."""
    today = datetime.now(timezone.utc).date()

    def _as_date(value: date | str | None) -> date | None:
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


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator * 100, 2)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[lower], 2)
    weight = position - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 2)


def _hours_between(start: datetime, end: datetime) -> float:
    return max(0.0, (end - start).total_seconds() / 3600)


def _empty_activity() -> dict[str, Any]:
    return {
        "comment_ids": set(),
        "comment_authors": set(),
        "comment_mentions": set(),
        "mentioned_users": set(),
        "review_comment_ids": set(),
        "reviewers": set(),
        "review_comment_links": set(),
        "review_link_views": set(),
        "review_view_links": set(),
        "first_review_rows": [],
    }


def _distinct(raw: dict[str, Any], set_key: str, count_key: str) -> int:
    values = raw.get(set_key)
    if values is not None:
        return len(values)
    return int(raw.get(count_key, 0))


def _activity_payload(raw: dict[str, Any]) -> dict[str, Any]:
    comments_total = _distinct(raw, "comment_ids", "comments_total")
    comments_resolved = int(raw.get("comments_resolved", 0))
    mentions_total = _distinct(raw, "comment_mentions", "mentions_total")
    mentions_delivered = int(raw.get("mentions_delivered", 0))
    review_total = _distinct(raw, "review_comment_ids", "review_comments_total")
    review_resolved = int(raw.get("review_comments_resolved", 0))
    eligible, reviewed, median_hours, p90_hours = _time_to_review(raw["first_review_rows"])
    return {
        "comments": {
            "total": comments_total,
            "resolved": comments_resolved,
            "resolution_rate": _rate(comments_resolved, comments_total),
            "resolution_denominator": comments_total,
            "distinct_authors": _distinct(raw, "comment_authors", "comment_authors_total"),
        },
        "mentions": {
            "total": mentions_total,
            "delivered": mentions_delivered,
            "pending": max(0, mentions_total - mentions_delivered),
            "delivery_rate": _rate(mentions_delivered, mentions_total),
            "delivery_denominator": mentions_total,
            "delivery_attempts": int(raw.get("mention_attempts", 0)),
            "distinct_mentioned_users": _distinct(
                raw, "mentioned_users", "mentioned_users_total"
            ),
        },
        "review_comments": {
            "total": review_total,
            "resolved": review_resolved,
            "resolution_rate": _rate(review_resolved, review_total),
            "resolution_denominator": review_total,
            "distinct_reviewers": _distinct(raw, "reviewers", "reviewers_total"),
            "distinct_review_links": _distinct(
                raw, "review_comment_links", "review_comment_links_total"
            ),
        },
        "review_links": {
            "opens": _distinct(
                raw, "review_link_views", "review_link_opens_total"
            ),
            "distinct_links_opened": _distinct(
                raw, "review_view_links", "review_view_links_total"
            ),
        },
        "time_to_first_review": {
            "eligible_submissions": eligible,
            "reviewed_submissions": reviewed,
            "denominator": eligible,
            "median_hours": median_hours,
            "p90_hours": p90_hours,
            "suppressed": bool(reviewed) and reviewed < MIN_GROUP_SIZE,
            "suppression_threshold": MIN_GROUP_SIZE,
        },
    }


def _time_to_review(rows: Iterable[tuple[datetime, datetime | None]]) -> tuple[int, int, float | None, float | None]:
    eligible = 0
    durations: list[float] = []
    for shared_at, first_review_at in rows:
        eligible += 1
        if first_review_at is not None and first_review_at >= shared_at:
            durations.append(_hours_between(shared_at, first_review_at))
    reviewed = len(durations)
    if reviewed < MIN_GROUP_SIZE:
        return eligible, reviewed, None, None
    return eligible, reviewed, _percentile(durations, 0.5), _percentile(durations, 0.9)


class AdminCollaborationAnalyticsService:
    async def collaboration_usage(
        self,
        db: AsyncSession,
        *,
        days: int = 30,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        """Return platform collaboration metrics plus tenant/cohort drill-down."""
        days = max(1, min(int(days), MAX_RANGE_DAYS))
        start_day, end_day, start_at, end_at = _resolve_range(
            days=days, start_date=start_date, end_date=end_date
        )

        selected_tenant_id: str | None = None
        if tenant_id is not None:
            try:
                selected_tenant_id = str(uuid.UUID(str(tenant_id)))
            except (ValueError, AttributeError, TypeError) as exc:
                raise ValueError("tenant_id must be a UUID") from exc

        tenants = (
            await db.execute(
                select(
                    models.Tenant.id,
                    models.Tenant.name,
                    models.Tenant.slug,
                    models.Tenant.plan_id,
                    models.Tenant.active,
                ).order_by(models.Tenant.name)
            )
        ).all()
        tenant_ids = [str(row.id) for row in tenants]
        if selected_tenant_id is not None and selected_tenant_id not in tenant_ids:
            raise LookupError("Tenant not found")

        tenant_member_counts = {
            str(tenant_id): int(count or 0)
            for tenant_id, count in (
                await db.execute(
                    select(models.TenantMember.tenant_id, func.count(models.TenantMember.user_id))
                    .group_by(models.TenantMember.tenant_id)
                )
            ).all()
        }
        distinct_tenant_members = int(
            (
                await db.execute(select(func.count(distinct(models.TenantMember.user_id))))
            ).scalar()
            or 0
        )
        tenant_cohort_counts = {
            str(tenant_id): int(count or 0)
            for tenant_id, count in (
                await db.execute(
                    select(models.Workspace.tenant_id, func.count(models.Workspace.id))
                    .where(models.Workspace.tenant_id.is_not(None))
                    .group_by(models.Workspace.tenant_id)
                )
            ).all()
        }
        tenant_cohort_member_counts = {
            str(tenant_id): int(count or 0)
            for tenant_id, count in (
                await db.execute(
                    select(models.Workspace.tenant_id, func.count(models.WorkspaceMember.user_id))
                    .select_from(models.Workspace)
                    .join(models.WorkspaceMember, models.WorkspaceMember.workspace_id == models.Workspace.id)
                    .where(models.Workspace.tenant_id.is_not(None))
                    .group_by(models.Workspace.tenant_id)
                )
            ).all()
        }
        tenant_submission_counts = {
            str(tenant_id): int(count or 0)
            for tenant_id, count in (
                await db.execute(
                    select(models.Workspace.tenant_id, func.count(models.WorkspaceResume.resume_id))
                    .select_from(models.Workspace)
                    .join(models.WorkspaceResume, models.WorkspaceResume.workspace_id == models.Workspace.id)
                    .where(models.Workspace.tenant_id.is_not(None))
                    .group_by(models.Workspace.tenant_id)
                )
            ).all()
        }

        tenant_activity: dict[str, dict[str, Any]] = {
            tenant_id: _empty_activity() for tenant_id in tenant_ids
        }

        # Comments in a tenant-owned workspace.
        comment_rows = (
            await db.execute(
                select(
                    models.Workspace.tenant_id,
                    models.ResumeComment.id,
                    models.ResumeComment.author_id,
                    models.ResumeComment.resolved,
                )
                .select_from(models.ResumeComment)
                .join(models.Workspace, models.Workspace.id == models.ResumeComment.workspace_id)
                .where(
                    models.Workspace.tenant_id.is_not(None),
                    models.ResumeComment.created_at >= start_at,
                    models.ResumeComment.created_at < end_at,
                )
            )
        ).all()
        for row in comment_rows:
            bucket = tenant_activity.get(str(row.tenant_id))
            if bucket is None:
                continue
            bucket["comment_ids"].add(str(row.id))
            bucket["comment_authors"].add(str(row.author_id))
            if bool(row.resolved):
                bucket["comments_resolved"] = bucket.get("comments_resolved", 0) + 1

        # Mentions resolved from comments in a tenant-owned workspace.
        mention_rows = (
            await db.execute(
                select(
                    models.Workspace.tenant_id,
                    models.ResumeCommentMention.id,
                    models.ResumeCommentMention.mentioned_user_id,
                    models.ResumeCommentMention.delivery_sent_at,
                    models.ResumeCommentMention.delivery_attempts,
                )
                .select_from(models.ResumeCommentMention)
                .join(models.ResumeComment, models.ResumeComment.id == models.ResumeCommentMention.comment_id)
                .join(models.Workspace, models.Workspace.id == models.ResumeComment.workspace_id)
                .where(
                    models.Workspace.tenant_id.is_not(None),
                    models.ResumeCommentMention.created_at >= start_at,
                    models.ResumeCommentMention.created_at < end_at,
                )
            )
        ).all()
        for row in mention_rows:
            bucket = tenant_activity.get(str(row.tenant_id))
            if bucket is None:
                continue
            bucket["comment_mentions"].add(str(row.id))
            bucket["mentioned_users"].add(str(row.mentioned_user_id))
            bucket["mention_attempts"] = bucket.get("mention_attempts", 0) + int(
                row.delivery_attempts or 0
            )
            if row.delivery_sent_at is not None:
                bucket["mentions_delivered"] = bucket.get("mentions_delivered", 0) + 1

        # Anonymous review comments on resumes submitted to a tenant cohort.
        review_rows = (
            await db.execute(
                select(
                    models.Workspace.tenant_id,
                    models.ResumeReviewComment.id,
                    models.ResumeReviewComment.share_token_hash,
                    models.ResumeReviewComment.reviewer_label,
                    models.ResumeReviewComment.resolved,
                )
                .select_from(models.ResumeReviewComment)
                .join(
                    models.WorkspaceResume,
                    models.WorkspaceResume.resume_id == models.ResumeReviewComment.resume_id,
                )
                .join(models.Workspace, models.Workspace.id == models.WorkspaceResume.workspace_id)
                .where(
                    models.Workspace.tenant_id.is_not(None),
                    models.ResumeReviewComment.created_at >= start_at,
                    models.ResumeReviewComment.created_at < end_at,
                )
            )
        ).all()
        for row in review_rows:
            bucket = tenant_activity.get(str(row.tenant_id))
            if bucket is None:
                continue
            comment_id = str(row.id)
            bucket["review_comment_ids"].add(comment_id)
            bucket["reviewers"].add(f"{row.share_token_hash}:{row.reviewer_label}")
            bucket["review_comment_links"].add(str(row.share_token_hash))
            if bool(row.resolved):
                bucket["review_comments_resolved"] = (
                    bucket.get("review_comments_resolved", 0) + 1
                )

        # Opens of review-capable share links for resumes submitted to a cohort.
        view_rows = (
            await db.execute(
                select(
                    models.Workspace.tenant_id,
                    models.ResumeView.id,
                    models.ResumeView.share_token,
                )
                .select_from(models.ResumeView)
                .join(models.Resume, models.Resume.id == models.ResumeView.resume_id)
                .join(
                    models.WorkspaceResume,
                    models.WorkspaceResume.resume_id == models.ResumeView.resume_id,
                )
                .join(models.Workspace, models.Workspace.id == models.WorkspaceResume.workspace_id)
                .where(
                    models.Workspace.tenant_id.is_not(None),
                    models.ResumeView.viewed_at >= start_at,
                    models.ResumeView.viewed_at < end_at,
                    _REVIEW_CAPABILITY,
                )
            )
        ).all()
        for row in view_rows:
            bucket = tenant_activity.get(str(row.tenant_id))
            if bucket is None:
                continue
            bucket["review_link_views"].add(str(row.id))
            bucket["review_view_links"].add(str(row.share_token))

        # First review per cohort submission. The outer join only sees review
        # comments created after the submission and inside the selected window,
        # so unreviewed submissions stay in the denominator with a null value.
        first_review_rows = (
            await db.execute(
                select(
                    models.Workspace.tenant_id,
                    models.WorkspaceResume.workspace_id,
                    models.WorkspaceResume.resume_id,
                    models.WorkspaceResume.shared_at,
                    func.min(models.ResumeReviewComment.created_at).label("first_review_at"),
                )
                .select_from(models.WorkspaceResume)
                .join(models.Workspace, models.Workspace.id == models.WorkspaceResume.workspace_id)
                .outerjoin(
                    models.ResumeReviewComment,
                    and_(
                        models.ResumeReviewComment.resume_id == models.WorkspaceResume.resume_id,
                        models.ResumeReviewComment.created_at >= models.WorkspaceResume.shared_at,
                        models.ResumeReviewComment.created_at < end_at,
                    ),
                )
                .where(
                    models.Workspace.tenant_id.is_not(None),
                    models.WorkspaceResume.shared_at >= start_at,
                    models.WorkspaceResume.shared_at < end_at,
                )
                .group_by(
                    models.Workspace.tenant_id,
                    models.WorkspaceResume.workspace_id,
                    models.WorkspaceResume.resume_id,
                    models.WorkspaceResume.shared_at,
                )
            )
        ).all()
        for row in first_review_rows:
            bucket = tenant_activity.get(str(row.tenant_id))
            if bucket is None:
                continue
            bucket["first_review_rows"].append((row.shared_at, row.first_review_at))

        # Platform-wide collaboration totals (all scopes, not just tenants).
        comment_totals = (
            await db.execute(
                select(
                    func.count(models.ResumeComment.id),
                    func.count(models.ResumeComment.id).filter(models.ResumeComment.resolved.is_(True)),
                    func.count(distinct(models.ResumeComment.author_id)),
                ).where(
                    models.ResumeComment.created_at >= start_at,
                    models.ResumeComment.created_at < end_at,
                )
            )
        ).one()
        mention_totals = (
            await db.execute(
                select(
                    func.count(models.ResumeCommentMention.id),
                    func.count(models.ResumeCommentMention.id).filter(
                        models.ResumeCommentMention.delivery_sent_at.is_not(None)
                    ),
                    func.count(distinct(models.ResumeCommentMention.mentioned_user_id)),
                    func.coalesce(func.sum(models.ResumeCommentMention.delivery_attempts), 0),
                ).where(
                    models.ResumeCommentMention.created_at >= start_at,
                    models.ResumeCommentMention.created_at < end_at,
                )
            )
        ).one()
        review_totals = (
            await db.execute(
                select(
                    func.count(models.ResumeReviewComment.id),
                    func.count(models.ResumeReviewComment.id).filter(
                        models.ResumeReviewComment.resolved.is_(True)
                    ),
                    func.count(distinct(models.ResumeReviewComment.share_token_hash)),
                    func.count(
                        distinct(
                            func.concat(
                                models.ResumeReviewComment.share_token_hash,
                                ":",
                                models.ResumeReviewComment.reviewer_label,
                            )
                        )
                    ),
                ).where(
                    models.ResumeReviewComment.created_at >= start_at,
                    models.ResumeReviewComment.created_at < end_at,
                )
            )
        ).one()
        view_totals = (
            await db.execute(
                select(
                    func.count(models.ResumeView.id),
                    func.count(distinct(models.ResumeView.share_token)),
                )
                .select_from(models.ResumeView)
                .join(models.Resume, models.Resume.id == models.ResumeView.resume_id)
                .where(
                    models.ResumeView.viewed_at >= start_at,
                    models.ResumeView.viewed_at < end_at,
                    _REVIEW_CAPABILITY,
                )
            )
        ).one()

        platform_activity: dict[str, Any] = {}
        platform_comment_total, platform_resolved, platform_authors = comment_totals
        platform_activity["comments_total"] = int(platform_comment_total or 0)
        platform_activity["comments_resolved"] = int(platform_resolved or 0)
        platform_activity["comment_authors_total"] = int(platform_authors or 0)
        (
            platform_mention_total,
            platform_delivered,
            platform_mentioned_users,
            platform_attempts,
        ) = mention_totals
        platform_activity["mentions_total"] = int(platform_mention_total or 0)
        platform_activity["mentions_delivered"] = int(platform_delivered or 0)
        platform_activity["mentioned_users_total"] = int(platform_mentioned_users or 0)
        platform_activity["mention_attempts"] = int(platform_attempts or 0)
        (
            platform_review_total,
            platform_review_resolved,
            platform_review_links,
            platform_reviewers,
        ) = review_totals
        platform_activity["review_comments_total"] = int(platform_review_total or 0)
        platform_activity["review_comments_resolved"] = int(platform_review_resolved or 0)
        platform_activity["review_comment_links_total"] = int(platform_review_links or 0)
        platform_activity["reviewers_total"] = int(platform_reviewers or 0)
        platform_view_total, platform_view_links = view_totals
        platform_activity["review_link_opens_total"] = int(platform_view_total or 0)
        platform_activity["review_view_links_total"] = int(platform_view_links or 0)
        platform_activity["first_review_rows"] = [
            (row.shared_at, row.first_review_at) for row in first_review_rows
        ]

        activity_by_tenant = {
            tenant_id: _activity_payload(raw) for tenant_id, raw in tenant_activity.items()
        }

        tenant_rows: list[dict[str, Any]] = []
        visible_tenant_member_count = 0
        suppressed_tenant_member_count = 0
        visible_tenant_count = 0
        suppressed_tenant_count = 0
        for tenant in tenants:
            tid = str(tenant.id)
            member_count = int(tenant_member_counts.get(tid, 0))
            suppressed = member_count < MIN_GROUP_SIZE
            row: dict[str, Any] = {
                "tenant_id": tid,
                "name": tenant.name,
                "slug": tenant.slug,
                "plan_id": tenant.plan_id,
                "active": bool(tenant.active),
                "suppressed": suppressed,
                "suppression_reason": "fewer_than_minimum_members" if suppressed else None,
                "member_count": None if suppressed else member_count,
                "cohort_count": None if suppressed else int(tenant_cohort_counts.get(tid, 0)),
                "cohort_member_count": (
                    None if suppressed else int(tenant_cohort_member_counts.get(tid, 0))
                ),
                "submitted_resume_count": (
                    None if suppressed else int(tenant_submission_counts.get(tid, 0))
                ),
                "activity": None if suppressed else activity_by_tenant.get(tid),
            }
            tenant_rows.append(row)
            if suppressed:
                suppressed_tenant_count += 1
                suppressed_tenant_member_count += member_count
            else:
                visible_tenant_count += 1
                visible_tenant_member_count += member_count

        tenant_rows.sort(
            key=lambda item: (
                not item["active"],
                -(item["member_count"] or 0),
                str(item["name"]).lower(),
            )
        )

        # Cohort reconciliation. Cohorts of suppressed tenants are suppressed
        # too, even when the cohort itself has enough members.
        all_cohorts = (
            await db.execute(
                select(
                    models.Workspace.id,
                    models.Workspace.tenant_id,
                    models.Workspace.name,
                )
                .where(models.Workspace.tenant_id.is_not(None))
                .order_by(models.Workspace.name)
            )
        ).all()
        cohort_member_counts = {
            str(cohort_id): int(count or 0)
            for cohort_id, count in (
                await db.execute(
                    select(models.WorkspaceMember.workspace_id, func.count(models.WorkspaceMember.user_id))
                    .join(models.Workspace, models.Workspace.id == models.WorkspaceMember.workspace_id)
                    .where(models.Workspace.tenant_id.is_not(None))
                    .group_by(models.WorkspaceMember.workspace_id)
                )
            ).all()
        }
        cohort_submission_counts = {
            str(cohort_id): int(count or 0)
            for cohort_id, count in (
                await db.execute(
                    select(models.WorkspaceResume.workspace_id, func.count(models.WorkspaceResume.resume_id))
                    .join(models.Workspace, models.Workspace.id == models.WorkspaceResume.workspace_id)
                    .where(models.Workspace.tenant_id.is_not(None))
                    .group_by(models.WorkspaceResume.workspace_id)
                )
            ).all()
        }
        tenant_member_count_total = sum(tenant_member_counts.values())
        cohort_member_count_total = sum(cohort_member_counts.values())
        cohort_submission_count_total = sum(cohort_submission_counts.values())
        visible_cohort_count = 0
        suppressed_cohort_count = 0
        visible_cohort_member_count = 0
        suppressed_cohort_member_count = 0
        visible_cohort_submission_count = 0
        suppressed_cohort_submission_count = 0
        visible_tenant_ids = {
            str(tenant.id)
            for tenant in tenants
            if int(tenant_member_counts.get(str(tenant.id), 0)) >= MIN_GROUP_SIZE
        }
        for cohort in all_cohorts:
            cohort_id = str(cohort.id)
            tenant_id = str(cohort.tenant_id)
            member_count = int(cohort_member_counts.get(cohort_id, 0))
            submission_count = int(cohort_submission_counts.get(cohort_id, 0))
            if tenant_id in visible_tenant_ids and member_count >= MIN_GROUP_SIZE:
                visible_cohort_count += 1
                visible_cohort_member_count += member_count
                visible_cohort_submission_count += submission_count
            else:
                suppressed_cohort_count += 1
                suppressed_cohort_member_count += member_count
                suppressed_cohort_submission_count += submission_count

        selected_tenant: dict[str, Any] | None = None
        if selected_tenant_id is not None:
            selected_row = next(
                row for row in tenant_rows if row["tenant_id"] == selected_tenant_id
            )
            selected_tenant = dict(selected_row)
            if selected_row["suppressed"]:
                selected_tenant["cohorts"] = []
                selected_tenant["suppressed_cohort_count"] = None
                selected_tenant["reconciliation"] = None
            else:
                cohort_rows = await self._cohort_rows(
                    db,
                    tenant_id=selected_tenant_id,
                    start_at=start_at,
                    end_at=end_at,
                    all_cohorts=[cohort for cohort in all_cohorts if str(cohort.tenant_id) == selected_tenant_id],
                    cohort_member_counts=cohort_member_counts,
                    cohort_submission_counts=cohort_submission_counts,
                )
                visible_cohorts = [row for row in cohort_rows if not row["suppressed"]]
                suppressed_cohorts = [row for row in cohort_rows if row["suppressed"]]
                selected_tenant["cohorts"] = cohort_rows
                selected_tenant["suppressed_cohort_count"] = len(suppressed_cohorts)
                selected_tenant["reconciliation"] = {
                    "member_count": selected_row["member_count"],
                    "cohort_count": len(cohort_rows),
                    "visible_cohort_count": len(visible_cohorts),
                    "suppressed_cohort_count": len(suppressed_cohorts),
                    "cohort_member_count": selected_row["cohort_member_count"],
                    "visible_cohort_member_count": sum(
                        int(row["member_count"] or 0) for row in visible_cohorts
                    ),
                    "suppressed_cohort_member_count": sum(
                        int(cohort_member_counts.get(row["cohort_id"], 0))
                        for row in suppressed_cohorts
                    ),
                    "submitted_resume_count": selected_row["submitted_resume_count"],
                    "visible_cohort_submission_count": sum(
                        int(row["submission_count"] or 0) for row in visible_cohorts
                    ),
                    "suppressed_cohort_submission_count": sum(
                        int(cohort_submission_counts.get(row["cohort_id"], 0))
                        for row in suppressed_cohorts
                    ),
                }

        now = datetime.now(timezone.utc)
        return {
            "days": (end_day - start_day).days + 1,
            "start_date": start_day.isoformat(),
            "end_date": end_day.isoformat(),
            "timezone": TIMEZONE,
            "date_range": {
                "start": start_at.isoformat(),
                "end": end_at.isoformat(),
                "days": (end_day - start_day).days + 1,
                "timezone": TIMEZONE,
            },
            "filters": {
                "days": (end_day - start_day).days + 1,
                "start_date": start_day.isoformat(),
                "end_date": end_day.isoformat(),
                "tenant_id": selected_tenant_id,
                "timezone": TIMEZONE,
            },
            "minimum_group_size": MIN_GROUP_SIZE,
            "summary": _activity_payload(platform_activity),
            "tenants": tenant_rows,
            "suppressed_tenants": suppressed_tenant_count,
            "reconciliation": {
                "tenant_count": len(tenants),
                "active_tenant_count": sum(1 for tenant in tenants if bool(tenant.active)),
                "visible_tenant_count": visible_tenant_count,
                "suppressed_tenant_count": suppressed_tenant_count,
                "tenant_member_count": tenant_member_count_total,
                "visible_tenant_member_count": visible_tenant_member_count,
                "suppressed_tenant_member_count": suppressed_tenant_member_count,
                "distinct_tenant_members": distinct_tenant_members,
                "cohort_count": len(all_cohorts),
                "visible_cohort_count": visible_cohort_count,
                "suppressed_cohort_count": suppressed_cohort_count,
                "cohort_member_count": cohort_member_count_total,
                "visible_cohort_member_count": visible_cohort_member_count,
                "suppressed_cohort_member_count": suppressed_cohort_member_count,
                "cohort_submission_count": cohort_submission_count_total,
                "visible_cohort_submission_count": visible_cohort_submission_count,
                "suppressed_cohort_submission_count": suppressed_cohort_submission_count,
            },
            "selected_tenant": selected_tenant,
            "definitions": {
                "comments": (
                    "Inline resume comments created in the selected range. Resolution rate is "
                    "resolved comments divided by comments created in the range; resolution is "
                    "the current state and may have changed after the range ended."
                ),
                "mentions": (
                    "Resolved collaborator mentions on comments created in the range. Delivery "
                    "rate is mentions with a recorded delivery timestamp divided by those mentions."
                ),
                "review_comments": (
                    "Anonymous review-link comments created in the range. Reviewer counts use "
                    "the opaque token/label pair and never expose the label or an identity."
                ),
                "review_links": (
                    "Recorded opens of review-capable share links (resumes whose current settings "
                    "enable review comments) in the range. Raw share tokens are never returned."
                ),
                "time_to_first_review": (
                    "Cohort submissions created in the range form the denominator. Reviewed "
                    "submissions have at least one review comment created between submission and "
                    "the end of the range; median and p90 hours use only reviewed submissions and "
                    f"are hidden below {MIN_GROUP_SIZE} reviewed submissions."
                ),
                "suppression": (
                    f"Tenants and cohorts with fewer than {MIN_GROUP_SIZE} members are hidden "
                    "along with every activity metric they carry."
                ),
                "tenant_reconciliation": (
                    "Tenant and cohort counts come from tenant_members, workspaces and "
                    "workspace_members. Visible plus suppressed member totals reconcile to the "
                    "same source tables."
                ),
            },
            "generated_at": now.isoformat(),
        }

    async def _cohort_rows(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        start_at: datetime,
        end_at: datetime,
        all_cohorts: list[Any],
        cohort_member_counts: dict[str, int],
        cohort_submission_counts: dict[str, int],
    ) -> list[dict[str, Any]]:
        cohort_ids = [str(cohort.id) for cohort in all_cohorts]
        activity: dict[str, dict[str, Any]] = {
            cohort_id: _empty_activity() for cohort_id in cohort_ids
        }

        comment_rows = (
            await db.execute(
                select(
                    models.ResumeComment.workspace_id,
                    models.ResumeComment.id,
                    models.ResumeComment.author_id,
                    models.ResumeComment.resolved,
                )
                .select_from(models.ResumeComment)
                .join(models.Workspace, models.Workspace.id == models.ResumeComment.workspace_id)
                .where(
                    models.Workspace.tenant_id == tenant_id,
                    models.ResumeComment.created_at >= start_at,
                    models.ResumeComment.created_at < end_at,
                )
            )
        ).all()
        for row in comment_rows:
            bucket = activity.get(str(row.workspace_id))
            if bucket is None:
                continue
            bucket["comment_ids"].add(str(row.id))
            bucket["comment_authors"].add(str(row.author_id))
            if bool(row.resolved):
                bucket["comments_resolved"] = bucket.get("comments_resolved", 0) + 1

        mention_rows = (
            await db.execute(
                select(
                    models.ResumeComment.workspace_id,
                    models.ResumeCommentMention.id,
                    models.ResumeCommentMention.mentioned_user_id,
                    models.ResumeCommentMention.delivery_sent_at,
                    models.ResumeCommentMention.delivery_attempts,
                )
                .select_from(models.ResumeCommentMention)
                .join(models.ResumeComment, models.ResumeComment.id == models.ResumeCommentMention.comment_id)
                .join(models.Workspace, models.Workspace.id == models.ResumeComment.workspace_id)
                .where(
                    models.Workspace.tenant_id == tenant_id,
                    models.ResumeCommentMention.created_at >= start_at,
                    models.ResumeCommentMention.created_at < end_at,
                )
            )
        ).all()
        for row in mention_rows:
            bucket = activity.get(str(row.workspace_id))
            if bucket is None:
                continue
            bucket["comment_mentions"].add(str(row.id))
            bucket["mentioned_users"].add(str(row.mentioned_user_id))
            bucket["mention_attempts"] = bucket.get("mention_attempts", 0) + int(
                row.delivery_attempts or 0
            )
            if row.delivery_sent_at is not None:
                bucket["mentions_delivered"] = bucket.get("mentions_delivered", 0) + 1

        review_rows = (
            await db.execute(
                select(
                    models.WorkspaceResume.workspace_id,
                    models.ResumeReviewComment.id,
                    models.ResumeReviewComment.share_token_hash,
                    models.ResumeReviewComment.reviewer_label,
                    models.ResumeReviewComment.resolved,
                )
                .select_from(models.ResumeReviewComment)
                .join(
                    models.WorkspaceResume,
                    models.WorkspaceResume.resume_id == models.ResumeReviewComment.resume_id,
                )
                .join(models.Workspace, models.Workspace.id == models.WorkspaceResume.workspace_id)
                .where(
                    models.Workspace.tenant_id == tenant_id,
                    models.ResumeReviewComment.created_at >= start_at,
                    models.ResumeReviewComment.created_at < end_at,
                )
            )
        ).all()
        for row in review_rows:
            bucket = activity.get(str(row.workspace_id))
            if bucket is None:
                continue
            bucket["review_comment_ids"].add(str(row.id))
            bucket["reviewers"].add(f"{row.share_token_hash}:{row.reviewer_label}")
            bucket["review_comment_links"].add(str(row.share_token_hash))
            if bool(row.resolved):
                bucket["review_comments_resolved"] = (
                    bucket.get("review_comments_resolved", 0) + 1
                )

        view_rows = (
            await db.execute(
                select(
                    models.WorkspaceResume.workspace_id,
                    models.ResumeView.id,
                    models.ResumeView.share_token,
                )
                .select_from(models.ResumeView)
                .join(models.Resume, models.Resume.id == models.ResumeView.resume_id)
                .join(
                    models.WorkspaceResume,
                    models.WorkspaceResume.resume_id == models.ResumeView.resume_id,
                )
                .join(models.Workspace, models.Workspace.id == models.WorkspaceResume.workspace_id)
                .where(
                    models.Workspace.tenant_id == tenant_id,
                    models.ResumeView.viewed_at >= start_at,
                    models.ResumeView.viewed_at < end_at,
                    _REVIEW_CAPABILITY,
                )
            )
        ).all()
        for row in view_rows:
            bucket = activity.get(str(row.workspace_id))
            if bucket is None:
                continue
            bucket["review_link_views"].add(str(row.id))
            bucket["review_view_links"].add(str(row.share_token))

        first_review_rows = (
            await db.execute(
                select(
                    models.WorkspaceResume.workspace_id,
                    models.WorkspaceResume.resume_id,
                    models.WorkspaceResume.shared_at,
                    func.min(models.ResumeReviewComment.created_at).label("first_review_at"),
                )
                .select_from(models.WorkspaceResume)
                .join(models.Workspace, models.Workspace.id == models.WorkspaceResume.workspace_id)
                .outerjoin(
                    models.ResumeReviewComment,
                    and_(
                        models.ResumeReviewComment.resume_id == models.WorkspaceResume.resume_id,
                        models.ResumeReviewComment.created_at >= models.WorkspaceResume.shared_at,
                        models.ResumeReviewComment.created_at < end_at,
                    ),
                )
                .where(
                    models.Workspace.tenant_id == tenant_id,
                    models.WorkspaceResume.shared_at >= start_at,
                    models.WorkspaceResume.shared_at < end_at,
                )
                .group_by(
                    models.WorkspaceResume.workspace_id,
                    models.WorkspaceResume.resume_id,
                    models.WorkspaceResume.shared_at,
                )
            )
        ).all()
        for row in first_review_rows:
            bucket = activity.get(str(row.workspace_id))
            if bucket is None:
                continue
            bucket["first_review_rows"].append((row.shared_at, row.first_review_at))

        rows: list[dict[str, Any]] = []
        for cohort in all_cohorts:
            cohort_id = str(cohort.id)
            member_count = int(cohort_member_counts.get(cohort_id, 0))
            suppressed = member_count < MIN_GROUP_SIZE
            rows.append(
                {
                    "cohort_id": cohort_id,
                    "name": cohort.name,
                    "suppressed": suppressed,
                    "suppression_reason": "fewer_than_minimum_members" if suppressed else None,
                    "member_count": None if suppressed else member_count,
                    "submission_count": (
                        None if suppressed else int(cohort_submission_counts.get(cohort_id, 0))
                    ),
                    "activity": None if suppressed else _activity_payload(activity[cohort_id]),
                }
            )
        rows.sort(key=lambda item: (-(item["member_count"] or 0), str(item["name"]).lower()))
        return rows


admin_collaboration_analytics_service = AdminCollaborationAnalyticsService()
