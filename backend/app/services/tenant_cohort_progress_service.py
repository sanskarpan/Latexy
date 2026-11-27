"""Aggregate-only cohort progress analytics for tenant dashboards.

The tenant cohort dashboard already exposes roster and explicit-submission
counts.  This module adds reviewer-engagement progress without turning the
tenant dashboard into a per-student review feed:

* submissions are only ``workspace_resumes`` rows in tenant-owned cohorts;
* a submission counts as reviewed when a recruiter note (``recruiter_notes``)
  or a workspace comment (``resume_comments`` with the cohort's workspace id)
  authored by someone other than the candidate exists after the share time;
* candidate self-milestones (``opened_at`` / ``downloaded_at``) are reported in
  a separate funnel block and never folded into reviewer actions;
* no comment text, note text, student email, user id or resume title leaves
  this module - only counts, rates, a median duration and UTC daily totals;
* cohorts below five members or five submissions are suppressed.  Explicit
  submission counts already shown by the tenant cohort endpoint stay visible,
  but reviewer engagement, stale counts and trends are withheld.

The metric is expressed with SQL aggregates (``percentile_cont`` for the
median and UTC daily buckets for trends) so the same numbers can be reproduced
directly against PostgreSQL.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy import Float, and_, case, func, select, text, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import (
    RecruiterNote,
    Resume,
    ResumeComment,
    Workspace,
    WorkspaceMember,
    WorkspaceResume,
)

MINIMUM_COHORT_SIZE = 5
MINIMUM_SUBMISSIONS = 5
STALE_AFTER_DAYS = 7
TREND_PERIODS: tuple[int, ...] = (7, 30, 90)


def _utc_day_start(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def _utc_day(column: Any) -> Any:
    """Group a timezone-aware timestamp by its UTC calendar date."""
    return func.date(func.timezone("UTC", column))


def _count_by_day(rows: Iterable[Any]) -> dict[tuple[str, date], int]:
    counts: dict[tuple[str, date], int] = {}
    for cohort_id, day, count in rows:
        if day is None:
            continue
        counts[(cohort_id, day)] = int(count or 0)
    return counts


def _suppression_reason(member_count: int, submission_count: int) -> str | None:
    below_members = member_count < MINIMUM_COHORT_SIZE
    below_submissions = submission_count < MINIMUM_SUBMISSIONS
    if below_members and below_submissions:
        return "cohort_and_submissions_below_minimum"
    if below_members:
        return "cohort_below_minimum"
    if below_submissions:
        return "submissions_below_minimum"
    return None


def _empty_summary(
    cohort_id: str,
    *,
    member_count: int,
    submission_count: int,
    generated_at: datetime,
) -> dict[str, Any]:
    reason = _suppression_reason(member_count, submission_count)
    return {
        "cohort_id": cohort_id,
        "generated_at": generated_at,
        "suppressed": reason is not None,
        "suppression": {
            "suppressed": reason is not None,
            "reason": reason,
            "minimum_cohort_size": MINIMUM_COHORT_SIZE,
            "minimum_submissions": MINIMUM_SUBMISSIONS,
            "cohort_size": member_count,
            "submissions": submission_count,
            "note": (
                "Cohort progress is hidden below five members or five "
                "submissions to prevent small-group re-identification."
            ),
        },
        "submissions": submission_count,
        "reviewed": None,
        "unreviewed": None,
        "reviewer_count": None,
        "reviewer_actions": None,
        "reviewer_coverage": None,
        "median_time_to_review_hours": None,
        "stale_submissions": None,
        "stale_after_days": STALE_AFTER_DAYS,
        "funnel": None,
    }


def _trend_points(
    submissions_by_day: Mapping[tuple[str, date], int],
    reviewed_by_day: Mapping[tuple[str, date], int],
    actions_by_day: Mapping[tuple[str, date], int],
    cohort_id: str,
    today: date,
    days: int,
) -> list[dict[str, Any]]:
    start = today - timedelta(days=days - 1)
    return [
        {
            "date": day.isoformat(),
            "submissions": int(submissions_by_day.get((cohort_id, day), 0)),
            "reviewed": int(reviewed_by_day.get((cohort_id, day), 0)),
            "reviewer_actions": int(actions_by_day.get((cohort_id, day), 0)),
        }
        for day in (start + timedelta(days=offset) for offset in range(days))
    ]


async def build_cohort_progress(
    db: AsyncSession,
    tenant_id: str,
    cohort_ids: Sequence[str],
    *,
    include_trends: bool = False,
    now: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    """Return aggregate engagement progress keyed by cohort id.

    The caller must already have verified that the tenant exists and that the
    current actor is the tenant owner or an admin member.  Every query joins
    ``workspaces`` and filters on ``tenant_id`` so a cohort id from another
    tenant can never contribute rows here.
    """
    ids = [str(cohort_id) for cohort_id in cohort_ids]
    if not ids:
        return {}

    current = now or datetime.now(timezone.utc)
    generated_at = current.astimezone(timezone.utc)
    today = generated_at.date()
    trend_start = _utc_day_start(today - timedelta(days=max(TREND_PERIODS) - 1))
    stale_before = current - timedelta(days=STALE_AFTER_DAYS)

    member_rows = await db.execute(
        select(WorkspaceMember.workspace_id, func.count())
        .where(WorkspaceMember.workspace_id.in_(ids))
        .group_by(WorkspaceMember.workspace_id)
    )
    member_counts = {workspace_id: int(count or 0) for workspace_id, count in member_rows.all()}

    # Explicit cohort submissions, joined to the tenant to keep isolation at
    # the SQL layer even if a caller supplies a foreign cohort id.
    submissions = (
        select(
            WorkspaceResume.workspace_id.label("cohort_id"),
            WorkspaceResume.resume_id.label("resume_id"),
            WorkspaceResume.shared_at.label("shared_at"),
            WorkspaceResume.opened_at.label("opened_at"),
            WorkspaceResume.downloaded_at.label("downloaded_at"),
            Resume.user_id.label("candidate_id"),
        )
        .select_from(WorkspaceResume)
        .join(Workspace, Workspace.id == WorkspaceResume.workspace_id)
        .join(Resume, Resume.id == WorkspaceResume.resume_id)
        .where(
            Workspace.tenant_id == tenant_id,
            WorkspaceResume.workspace_id.in_(ids),
        )
        .subquery("cohort_submissions")
    )

    note_events = (
        select(
            RecruiterNote.workspace_id.label("cohort_id"),
            RecruiterNote.resume_id.label("resume_id"),
            RecruiterNote.author_id.label("author_id"),
            RecruiterNote.created_at.label("created_at"),
        )
        .select_from(RecruiterNote)
        .join(Workspace, Workspace.id == RecruiterNote.workspace_id)
        .where(
            Workspace.tenant_id == tenant_id,
            RecruiterNote.workspace_id.in_(ids),
        )
    )
    comment_events = (
        select(
            ResumeComment.workspace_id.label("cohort_id"),
            ResumeComment.resume_id.label("resume_id"),
            ResumeComment.author_id.label("author_id"),
            ResumeComment.created_at.label("created_at"),
        )
        .select_from(ResumeComment)
        .join(Workspace, Workspace.id == ResumeComment.workspace_id)
        .where(
            ResumeComment.workspace_id.is_not(None),
            Workspace.tenant_id == tenant_id,
            ResumeComment.workspace_id.in_(ids),
        )
    )
    review_events = union_all(note_events, comment_events).subquery("cohort_review_events")

    # Only actions on a still-shared submission count, and a candidate's own
    # note/comment is candidate self-activity rather than reviewer coverage.
    reviewer_events = (
        select(
            review_events.c.cohort_id,
            review_events.c.resume_id,
            review_events.c.author_id,
            review_events.c.created_at,
        )
        .select_from(
            review_events.join(
                submissions,
                and_(
                    review_events.c.cohort_id == submissions.c.cohort_id,
                    review_events.c.resume_id == submissions.c.resume_id,
                    review_events.c.author_id != submissions.c.candidate_id,
                ),
            )
        )
        .subquery("cohort_reviewer_events")
    )

    first_review = (
        select(
            reviewer_events.c.cohort_id,
            reviewer_events.c.resume_id,
            func.min(reviewer_events.c.created_at).label("first_reviewed_at"),
        )
        .group_by(reviewer_events.c.cohort_id, reviewer_events.c.resume_id)
        .subquery("cohort_first_review")
    )

    # GREATEST/LEAST ignore NULL in PostgreSQL, so unreviewed submissions must
    # be explicitly mapped to NULL rather than zero before the median is taken.
    review_delay_seconds = case(
        (
            first_review.c.first_reviewed_at.is_not(None),
            func.extract(
                "epoch",
                func.greatest(
                    first_review.c.first_reviewed_at - submissions.c.shared_at,
                    text("interval '0'"),
                ),
            ).cast(Float),
        ),
        else_=None,
    )

    totals_result = await db.execute(
        select(
            submissions.c.cohort_id,
            func.count().label("submissions"),
            func.count(submissions.c.opened_at).label("candidate_opened"),
            func.count(submissions.c.downloaded_at).label("candidate_downloaded"),
            func.count(first_review.c.first_reviewed_at).label("reviewed"),
            func.percentile_cont(0.5).within_group(review_delay_seconds).label("median_review_seconds"),
            func.count()
            .filter(
                and_(
                    first_review.c.first_reviewed_at.is_(None),
                    submissions.c.shared_at <= stale_before,
                )
            )
            .label("stale_submissions"),
        )
        .select_from(
            submissions.outerjoin(
                first_review,
                and_(
                    first_review.c.cohort_id == submissions.c.cohort_id,
                    first_review.c.resume_id == submissions.c.resume_id,
                ),
            )
        )
        .group_by(submissions.c.cohort_id)
    )
    totals_by_cohort = {
        row.cohort_id: {
            "submissions": int(row.submissions or 0),
            "candidate_opened": int(row.candidate_opened or 0),
            "candidate_downloaded": int(row.candidate_downloaded or 0),
            "reviewed": int(row.reviewed or 0),
            "median_review_seconds": row.median_review_seconds,
            "stale_submissions": int(row.stale_submissions or 0),
        }
        for row in totals_result.all()
    }

    reviewer_result = await db.execute(
        select(
            reviewer_events.c.cohort_id,
            func.count(func.distinct(reviewer_events.c.author_id)).label("reviewer_count"),
            func.count().label("reviewer_actions"),
        ).group_by(reviewer_events.c.cohort_id)
    )
    reviewers_by_cohort = {
        row.cohort_id: {
            "reviewer_count": int(row.reviewer_count or 0),
            "reviewer_actions": int(row.reviewer_actions or 0),
        }
        for row in reviewer_result.all()
    }

    submissions_by_day: dict[tuple[str, date], int] = {}
    reviewed_by_day: dict[tuple[str, date], int] = {}
    actions_by_day: dict[tuple[str, date], int] = {}
    if include_trends:
        submission_day = _utc_day(submissions.c.shared_at)
        submission_day_rows = await db.execute(
            select(submissions.c.cohort_id, submission_day, func.count())
            .where(submissions.c.shared_at >= trend_start)
            .group_by(submissions.c.cohort_id, submission_day)
        )
        submissions_by_day = _count_by_day(submission_day_rows.all())

        reviewed_day = _utc_day(first_review.c.first_reviewed_at)
        reviewed_day_rows = await db.execute(
            select(first_review.c.cohort_id, reviewed_day, func.count())
            .where(first_review.c.first_reviewed_at >= trend_start)
            .group_by(first_review.c.cohort_id, reviewed_day)
        )
        reviewed_by_day = _count_by_day(reviewed_day_rows.all())

        action_day = _utc_day(reviewer_events.c.created_at)
        action_day_rows = await db.execute(
            select(reviewer_events.c.cohort_id, action_day, func.count())
            .where(reviewer_events.c.created_at >= trend_start)
            .group_by(reviewer_events.c.cohort_id, action_day)
        )
        actions_by_day = _count_by_day(action_day_rows.all())

    progress: dict[str, dict[str, Any]] = {}
    for cohort_id in ids:
        member_count = int(member_counts.get(cohort_id, 0))
        totals = totals_by_cohort.get(
            cohort_id,
            {
                "submissions": 0,
                "candidate_opened": 0,
                "candidate_downloaded": 0,
                "reviewed": 0,
                "median_review_seconds": None,
                "stale_submissions": 0,
            },
        )
        summary = _empty_summary(
            cohort_id,
            member_count=member_count,
            submission_count=totals["submissions"],
            generated_at=generated_at,
        )
        if summary["suppressed"]:
            progress[cohort_id] = {
                "summary": summary,
                "trends": None,
            }
            continue

        reviewers = reviewers_by_cohort.get(cohort_id, {"reviewer_count": 0, "reviewer_actions": 0})
        reviewed = min(totals["reviewed"], totals["submissions"])
        median_seconds = totals["median_review_seconds"]
        summary.update(
            {
                "reviewed": reviewed,
                "unreviewed": totals["submissions"] - reviewed,
                "reviewer_count": reviewers["reviewer_count"],
                "reviewer_actions": reviewers["reviewer_actions"],
                "reviewer_coverage": (round(reviewed / totals["submissions"], 4) if totals["submissions"] else 0.0),
                "median_time_to_review_hours": (
                    round(float(median_seconds) / 3600, 2) if median_seconds is not None else None
                ),
                "stale_submissions": totals["stale_submissions"],
                "funnel": {
                    "submitted": totals["submissions"],
                    "candidate_opened": totals["candidate_opened"],
                    "candidate_downloaded": totals["candidate_downloaded"],
                    "reviewed": reviewed,
                },
            }
        )
        trends = None
        if include_trends:
            trends = {
                str(period): _trend_points(
                    submissions_by_day,
                    reviewed_by_day,
                    actions_by_day,
                    cohort_id,
                    today,
                    period,
                )
                for period in TREND_PERIODS
            }
        progress[cohort_id] = {"summary": summary, "trends": trends}

    return progress
