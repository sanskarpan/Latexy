"""Tenant cohort reviewer-engagement progress (issue #2152).

The tests run against a real PostgreSQL fixture at migration head 0100 and use
only existing tables.  They cover the aggregate metric math, stale detection,
candidate/recruiter separation, suppression, tenant isolation and RBAC.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    RecruiterNote,
    Resume,
    ResumeComment,
    Tenant,
    TenantMember,
    Workspace,
    WorkspaceMember,
    WorkspaceResume,
)
from test.test_admin_control_plane_api import _create_session, _create_user

SECRET_COMMENT = "internal reviewer comment: do not leak this text"
SECRET_NOTE = "private recruiter note: do not leak this text"


def _slug(prefix: str = "test-cohort-progress") -> str:
    return f"{prefix}-{uuid4().hex[:16]}"


async def _seed_tenant(db: AsyncSession, *, owner_id: str) -> Tenant:
    tenant = Tenant(
        id=str(uuid4()),
        slug=_slug(),
        name="Cohort Progress Tenant",
        owner_id=owner_id,
        plan_id="university",
        max_members=50,
        active=True,
    )
    db.add(tenant)
    db.add(TenantMember(tenant_id=tenant.id, user_id=owner_id, role="admin"))
    await db.commit()
    return tenant


async def _add_tenant_member(db: AsyncSession, tenant_id: str, user_id: str, *, role: str = "member") -> None:
    db.add(TenantMember(tenant_id=tenant_id, user_id=user_id, role=role))
    await db.commit()


async def _seed_cohort(
    db: AsyncSession,
    *,
    tenant: Tenant,
    owner_id: str,
    member_ids: list[str],
    name: str = "Cohort Progress",
) -> Workspace:
    cohort = Workspace(
        id=str(uuid4()),
        name=name,
        owner_id=owner_id,
        tenant_id=tenant.id,
        plan_id=tenant.plan_id,
        max_members=tenant.max_members,
    )
    db.add(cohort)
    db.add(
        WorkspaceMember(
            workspace_id=cohort.id,
            user_id=owner_id,
            role="owner",
            joined_at=datetime.now(timezone.utc),
        )
    )
    for member_id in member_ids:
        if member_id == owner_id:
            continue
        db.add(
            WorkspaceMember(
                workspace_id=cohort.id,
                user_id=member_id,
                role="viewer",
                joined_at=datetime.now(timezone.utc),
            )
        )
    await db.commit()
    return cohort


async def _seed_submission(
    db: AsyncSession,
    *,
    cohort: Workspace,
    candidate_id: str,
    shared_at: datetime,
    title: str = "Private submission",
    opened: bool = False,
    downloaded: bool = False,
) -> Resume:
    resume = Resume(
        id=str(uuid4()),
        user_id=candidate_id,
        title=title,
        latex_content="\\documentclass{article}\\begin{document}secret\\end{document}",
        content_source="manual_latex",
    )
    db.add(resume)
    db.add(
        WorkspaceResume(
            workspace_id=cohort.id,
            resume_id=resume.id,
            shared_by=candidate_id,
            shared_at=shared_at,
            opened_at=shared_at if opened else None,
            downloaded_at=shared_at if downloaded else None,
        )
    )
    await db.commit()
    return resume


async def _seed_note(
    db: AsyncSession,
    *,
    cohort: Workspace,
    resume: Resume,
    author_id: str,
    created_at: datetime,
    content: str = SECRET_NOTE,
) -> None:
    db.add(
        RecruiterNote(
            workspace_id=cohort.id,
            resume_id=resume.id,
            author_id=author_id,
            content=content,
            created_at=created_at,
        )
    )
    await db.commit()


async def _seed_comment(
    db: AsyncSession,
    *,
    cohort: Workspace,
    resume: Resume,
    author_id: str,
    created_at: datetime,
    content: str = SECRET_COMMENT,
) -> None:
    db.add(
        ResumeComment(
            resume_id=resume.id,
            workspace_id=cohort.id,
            author_id=author_id,
            content=content,
            created_at=created_at,
        )
    )
    await db.commit()


async def _headers(db: AsyncSession, user_id: str) -> dict[str, str]:
    token = await _create_session(db, user_id)
    return {"Authorization": f"Bearer {token}"}


async def _people(db: AsyncSession) -> dict[str, object]:
    owner_id, owner_email = await _create_user(db, role="user", plan="team", name="Cohort Progress Owner")
    admin_id, admin_email = await _create_user(db, role="user", plan="team", name="Cohort Progress Admin")
    member_ids: list[str] = []
    member_emails: list[str] = []
    for index in range(4):
        member_id, member_email = await _create_user(
            db, role="user", plan="team", name=f"Cohort Progress Member {index}"
        )
        member_ids.append(member_id)
        member_emails.append(member_email)
    outsider_id, outsider_email = await _create_user(db, role="user", plan="team", name="Cohort Progress Outsider")
    platform_admin_id, _ = await _create_user(db, role="admin", plan="team", name="Cohort Progress Platform Admin")
    return {
        "owner_id": owner_id,
        "owner_email": owner_email,
        "admin_id": admin_id,
        "admin_email": admin_email,
        "member_ids": member_ids,
        "member_emails": member_emails,
        "outsider_id": outsider_id,
        "outsider_email": outsider_email,
        "platform_admin_id": platform_admin_id,
    }


@pytest.mark.asyncio
async def test_cohort_progress_metric_math_and_trends(client, db_session: AsyncSession):
    people = await _people(db_session)
    owner_id = people["owner_id"]
    admin_id = people["admin_id"]
    member_ids = people["member_ids"]
    tenant = await _seed_tenant(db_session, owner_id=owner_id)
    await _add_tenant_member(db_session, tenant.id, admin_id, role="admin")
    cohort = await _seed_cohort(
        db_session,
        tenant=tenant,
        owner_id=owner_id,
        member_ids=[admin_id, *member_ids],
    )
    now = datetime.now(timezone.utc)

    # Six submissions. Reviewer actions happen at +2h, +4h and +6h; a later
    # note on an already-reviewed resume must not move the median.
    submission_one = await _seed_submission(
        db_session,
        cohort=cohort,
        candidate_id=member_ids[0],
        shared_at=now - timedelta(days=10),
        opened=True,
    )
    submission_two = await _seed_submission(
        db_session,
        cohort=cohort,
        candidate_id=member_ids[1],
        shared_at=now - timedelta(days=9),
        downloaded=True,
    )
    submission_three = await _seed_submission(
        db_session,
        cohort=cohort,
        candidate_id=member_ids[2],
        shared_at=now - timedelta(days=8),
    )
    submission_four = await _seed_submission(
        db_session,
        cohort=cohort,
        candidate_id=member_ids[3],
        shared_at=now - timedelta(days=8),
    )
    submission_five = await _seed_submission(
        db_session,
        cohort=cohort,
        candidate_id=member_ids[0],
        shared_at=now - timedelta(days=6),
    )
    submission_six = await _seed_submission(
        db_session,
        cohort=cohort,
        candidate_id=member_ids[1],
        shared_at=now - timedelta(days=1),
    )

    await _seed_note(
        db_session,
        cohort=cohort,
        resume=submission_one,
        author_id=owner_id,
        created_at=now - timedelta(days=10) + timedelta(hours=2),
    )
    await _seed_comment(
        db_session,
        cohort=cohort,
        resume=submission_two,
        author_id=admin_id,
        created_at=now - timedelta(days=9) + timedelta(hours=4),
    )
    await _seed_note(
        db_session,
        cohort=cohort,
        resume=submission_three,
        author_id=owner_id,
        created_at=now - timedelta(days=8) + timedelta(hours=6),
    )
    await _seed_note(
        db_session,
        cohort=cohort,
        resume=submission_three,
        author_id=admin_id,
        created_at=now - timedelta(days=8) + timedelta(hours=20),
    )
    # Candidate self-comment and legacy milestones must never count as
    # reviewer engagement.  submission_five stays unreviewed.
    await _seed_comment(
        db_session,
        cohort=cohort,
        resume=submission_five,
        author_id=member_ids[0],
        created_at=now - timedelta(days=6) + timedelta(hours=1),
    )
    await _seed_note(
        db_session,
        cohort=cohort,
        resume=submission_six,
        author_id=admin_id,
        created_at=now - timedelta(hours=12),
    )

    headers = await _headers(db_session, owner_id)

    list_response = await client.get(f"/tenants/{tenant.id}/cohorts", headers=headers)
    assert list_response.status_code == 200, list_response.text
    rows = list_response.json()
    assert len(rows) == 1
    summary = rows[0]["progress"]
    assert summary["suppressed"] is False
    assert summary["submissions"] == 6
    assert summary["reviewed"] == 4
    assert summary["unreviewed"] == 2
    assert summary["reviewer_count"] == 2
    assert summary["reviewer_actions"] == 5
    assert summary["reviewer_coverage"] == pytest.approx(0.6667)
    # First-review delays are 2h, 4h, 6h and 12h; the second note on the
    # same resume is excluded from the median.
    assert summary["median_time_to_review_hours"] == pytest.approx(5.0)
    assert summary["stale_submissions"] == 1
    assert summary["stale_after_days"] == 7
    assert summary["funnel"] == {
        "submitted": 6,
        "candidate_opened": 1,
        "candidate_downloaded": 1,
        "reviewed": 4,
    }

    engagement_response = await client.get(f"/tenants/{tenant.id}/cohorts/{cohort.id}/engagement", headers=headers)
    assert engagement_response.status_code == 200, engagement_response.text
    engagement = engagement_response.json()
    assert engagement["summary"]["cohort_id"] == summary["cohort_id"]
    assert engagement["summary"]["submissions"] == summary["submissions"]
    assert engagement["summary"]["reviewed"] == summary["reviewed"]
    assert engagement["summary"]["reviewer_coverage"] == summary["reviewer_coverage"]
    assert engagement["summary"]["median_time_to_review_hours"] == summary["median_time_to_review_hours"]
    assert engagement["summary"]["stale_submissions"] == summary["stale_submissions"]
    assert set(engagement["trends"]) == {"7", "30", "90"}
    for period in ("7", "30", "90"):
        assert len(engagement["trends"][period]) == int(period)
        assert engagement["trends"][period][-1]["date"] == now.date().isoformat()

    # Two submissions in the last seven days, one of which was first reviewed;
    # only the reviewer note in that window contributes an action.
    week = engagement["trends"]["7"]
    assert sum(point["submissions"] for point in week) == 2
    assert sum(point["reviewed"] for point in week) == 1
    assert sum(point["reviewer_actions"] for point in week) == 1

    month = engagement["trends"]["30"]
    assert sum(point["submissions"] for point in month) == 6
    assert sum(point["reviewed"] for point in month) == 4
    assert sum(point["reviewer_actions"] for point in month) == 5

    serialized = json.dumps({"list": rows, "engagement": engagement})
    for secret in (
        *people["member_emails"],
        people["owner_email"],
        people["admin_email"],
        "Private submission",
        SECRET_COMMENT,
        SECRET_NOTE,
        owner_id,
        admin_id,
        *member_ids,
        "secret\\end{document}",
    ):
        assert secret not in serialized


@pytest.mark.asyncio
async def test_cohort_progress_stale_detection_uses_reviewer_actions_only(client, db_session: AsyncSession):
    people = await _people(db_session)
    owner_id = people["owner_id"]
    admin_id = people["admin_id"]
    member_ids = people["member_ids"]
    tenant = await _seed_tenant(db_session, owner_id=owner_id)
    await _add_tenant_member(db_session, tenant.id, admin_id, role="admin")
    cohort = await _seed_cohort(
        db_session,
        tenant=tenant,
        owner_id=owner_id,
        member_ids=[admin_id, *member_ids],
    )
    now = datetime.now(timezone.utc)

    stale_reviewed = await _seed_submission(
        db_session,
        cohort=cohort,
        candidate_id=member_ids[0],
        shared_at=now - timedelta(days=20),
    )
    await _seed_note(
        db_session,
        cohort=cohort,
        resume=stale_reviewed,
        author_id=owner_id,
        created_at=now - timedelta(days=19),
    )
    await _seed_submission(
        db_session,
        cohort=cohort,
        candidate_id=member_ids[1],
        shared_at=now - timedelta(days=10),
    )
    await _seed_submission(
        db_session,
        cohort=cohort,
        candidate_id=member_ids[2],
        shared_at=now - timedelta(days=7, hours=1),
    )
    await _seed_submission(
        db_session,
        cohort=cohort,
        candidate_id=member_ids[3],
        shared_at=now - timedelta(days=6),
    )
    fresh_reviewed = await _seed_submission(
        db_session,
        cohort=cohort,
        candidate_id=member_ids[0],
        shared_at=now - timedelta(days=1),
        opened=True,
    )
    await _seed_note(
        db_session,
        cohort=cohort,
        resume=fresh_reviewed,
        author_id=admin_id,
        created_at=now - timedelta(hours=12),
    )

    response = await client.get(
        f"/tenants/{tenant.id}/cohorts/{cohort.id}/engagement",
        headers=await _headers(db_session, owner_id),
    )
    assert response.status_code == 200, response.text
    summary = response.json()["summary"]
    assert summary["submissions"] == 5
    assert summary["reviewed"] == 2
    # Two of the three unreviewed submissions are older than seven days.
    assert summary["stale_submissions"] == 2
    assert summary["stale_after_days"] == 7
    # Candidate opening a submission does not make it reviewed or fresh.
    assert summary["funnel"]["candidate_opened"] == 1
    assert summary["funnel"]["reviewed"] == 2


@pytest.mark.asyncio
async def test_cohort_progress_suppresses_small_cohorts(client, db_session: AsyncSession):
    people = await _people(db_session)
    owner_id = people["owner_id"]
    admin_id = people["admin_id"]
    member_ids = people["member_ids"]
    tenant = await _seed_tenant(db_session, owner_id=owner_id)
    await _add_tenant_member(db_session, tenant.id, admin_id, role="admin")

    # Four roster members but five submissions: still suppressed.
    small_members = await _seed_cohort(
        db_session,
        tenant=tenant,
        owner_id=owner_id,
        member_ids=[admin_id, *member_ids[:2]],
    )
    # Five roster members but four submissions: still suppressed.
    small_submissions = await _seed_cohort(
        db_session,
        tenant=tenant,
        owner_id=owner_id,
        member_ids=[admin_id, *member_ids],
    )
    # Eligible cohort for contrast.
    eligible = await _seed_cohort(
        db_session,
        tenant=tenant,
        owner_id=owner_id,
        member_ids=[admin_id, *member_ids],
    )
    now = datetime.now(timezone.utc)
    for index in range(5):
        await _seed_submission(
            db_session,
            cohort=small_members,
            candidate_id=member_ids[index % len(member_ids)],
            shared_at=now - timedelta(days=index),
        )
    for index in range(4):
        await _seed_submission(
            db_session,
            cohort=small_submissions,
            candidate_id=member_ids[index % len(member_ids)],
            shared_at=now - timedelta(days=index),
        )
    for index in range(5):
        await _seed_submission(
            db_session,
            cohort=eligible,
            candidate_id=member_ids[index % len(member_ids)],
            shared_at=now - timedelta(days=index),
        )

    headers = await _headers(db_session, owner_id)
    response = await client.get(f"/tenants/{tenant.id}/cohorts", headers=headers)
    assert response.status_code == 200, response.text
    by_id = {row["id"]: row for row in response.json()}

    member_suppressed = by_id[small_members.id]["progress"]
    assert member_suppressed["suppressed"] is True
    assert member_suppressed["suppression"]["reason"] == "cohort_below_minimum"
    assert member_suppressed["submissions"] == 5
    assert member_suppressed["reviewed"] is None
    assert member_suppressed["median_time_to_review_hours"] is None
    assert member_suppressed["stale_submissions"] is None
    assert member_suppressed["funnel"] is None

    submission_suppressed = by_id[small_submissions.id]["progress"]
    assert submission_suppressed["suppressed"] is True
    assert submission_suppressed["suppression"]["reason"] == "submissions_below_minimum"
    assert submission_suppressed["submissions"] == 4
    assert submission_suppressed["reviewed"] is None

    assert by_id[eligible.id]["progress"]["suppressed"] is False
    assert by_id[eligible.id]["progress"]["submissions"] == 5

    detail = await client.get(
        f"/tenants/{tenant.id}/cohorts/{small_members.id}/engagement",
        headers=headers,
    )
    assert detail.status_code == 200, detail.text
    detail_body = detail.json()
    assert detail_body["summary"]["suppressed"] is True
    assert detail_body["summary"]["reviewed"] is None
    assert detail_body["trends"] is None


@pytest.mark.asyncio
async def test_cohort_progress_tenant_isolation_and_rbac(client, db_session: AsyncSession):
    people = await _people(db_session)
    owner_id = people["owner_id"]
    admin_id = people["admin_id"]
    member_ids = people["member_ids"]
    tenant = await _seed_tenant(db_session, owner_id=owner_id)
    await _add_tenant_member(db_session, tenant.id, admin_id, role="admin")
    for member_id in member_ids:
        await _add_tenant_member(db_session, tenant.id, member_id)
    cohort = await _seed_cohort(
        db_session,
        tenant=tenant,
        owner_id=owner_id,
        member_ids=[admin_id, *member_ids],
    )
    now = datetime.now(timezone.utc)
    own_submissions = []
    for index in range(5):
        own_submissions.append(
            await _seed_submission(
                db_session,
                cohort=cohort,
                candidate_id=member_ids[index % len(member_ids)],
                shared_at=now - timedelta(days=index),
            )
        )
    await _seed_note(
        db_session,
        cohort=cohort,
        resume=own_submissions[0],
        author_id=owner_id,
        created_at=now - timedelta(days=1),
    )

    other_owner_id, _ = await _create_user(db_session, role="user", plan="team", name="Other Cohort Owner")
    other_tenant = await _seed_tenant(db_session, owner_id=other_owner_id)
    other_cohort = await _seed_cohort(
        db_session,
        tenant=other_tenant,
        owner_id=other_owner_id,
        member_ids=[],
    )
    other_submission = await _seed_submission(
        db_session,
        cohort=other_cohort,
        candidate_id=other_owner_id,
        shared_at=now - timedelta(days=1),
    )
    await _seed_note(
        db_session,
        cohort=other_cohort,
        resume=other_submission,
        author_id=other_owner_id,
        created_at=now - timedelta(hours=6),
    )

    response = await client.get(
        f"/tenants/{tenant.id}/cohorts/{cohort.id}/engagement",
        headers=await _headers(db_session, owner_id),
    )
    assert response.status_code == 200, response.text
    summary = response.json()["summary"]
    assert summary["submissions"] == 5
    assert summary["reviewed"] == 1
    assert summary["reviewer_actions"] == 1
    assert summary["reviewer_count"] == 1

    cross_tenant = await client.get(
        f"/tenants/{tenant.id}/cohorts/{other_cohort.id}/engagement",
        headers=await _headers(db_session, owner_id),
    )
    assert cross_tenant.status_code == 404

    # Tenant admin member may read; plain members, outsiders and platform
    # admins who are not members of this tenant may not.
    admin_response = await client.get(
        f"/tenants/{tenant.id}/cohorts/{cohort.id}/engagement",
        headers=await _headers(db_session, admin_id),
    )
    assert admin_response.status_code == 200, admin_response.text
    for denied_user in (
        member_ids[0],
        people["outsider_id"],
        people["platform_admin_id"],
    ):
        denied = await client.get(
            f"/tenants/{tenant.id}/cohorts/{cohort.id}/engagement",
            headers=await _headers(db_session, denied_user),
        )
        assert denied.status_code == 403
