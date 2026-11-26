"""Tenant overview analytics: aggregate seats, activation and submissions.

These tests run against the real disposable PostgreSQL fixture at migration head
0091. They intentionally use only existing tables and ``usage_analytics`` JSONB
rows, proving the overview requires no schema change.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis_cache_client
from app.database.models import (
    Resume,
    Tenant,
    TenantMember,
    UsageAnalytics,
    Workspace,
    WorkspaceMember,
    WorkspaceResume,
)
from test.test_admin_control_plane_api import _create_session, _create_user


def _slug(prefix: str = "test-overview") -> str:
    return f"{prefix}-{uuid4().hex[:16]}"


async def _seed_tenant(
    db: AsyncSession,
    *,
    owner_id: str,
    slug: str | None = None,
    max_members: int = 10,
) -> Tenant:
    tenant = Tenant(
        id=str(uuid4()),
        slug=slug or _slug(),
        name="Overview Test Tenant",
        owner_id=owner_id,
        plan_id="university",
        max_members=max_members,
        active=True,
    )
    db.add(tenant)
    db.add(TenantMember(tenant_id=tenant.id, user_id=owner_id, role="admin"))
    await db.commit()
    return tenant


async def _add_member(
    db: AsyncSession, tenant_id: str, user_id: str, role: str = "member"
) -> None:
    db.add(TenantMember(tenant_id=tenant_id, user_id=user_id, role=role))
    await db.commit()


async def _seed_cohort(
    db: AsyncSession,
    *,
    tenant: Tenant,
    owner_id: str,
    member_ids: list[str],
    name: str = "Overview Cohort",
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
    for user_id in member_ids:
        if user_id == owner_id:
            continue
        db.add(
            WorkspaceMember(
                workspace_id=cohort.id,
                user_id=user_id,
                role="viewer",
                invited_by=owner_id,
                joined_at=datetime.now(timezone.utc),
            )
        )
    await db.commit()
    return cohort


async def _seed_submission(
    db: AsyncSession,
    *,
    cohort: Workspace,
    user_id: str,
    shared_at: datetime,
    title: str = "Private submission",
    opened: bool = False,
    downloaded: bool = False,
) -> Resume:
    resume = Resume(
        id=str(uuid4()),
        user_id=user_id,
        title=title,
        latex_content="\\documentclass{article}\\begin{document}secret\\end{document}",
        content_source="manual_latex",
    )
    db.add(resume)
    db.add(
        WorkspaceResume(
            workspace_id=cohort.id,
            resume_id=resume.id,
            shared_by=user_id,
            shared_at=shared_at,
            opened_at=shared_at if opened else None,
            downloaded_at=shared_at if downloaded else None,
        )
    )
    await db.commit()
    return resume


async def _seed_activity(
    db: AsyncSession, user_id: str, at: datetime
) -> None:
    db.add(
        UsageAnalytics(
            id=str(uuid4()),
            user_id=user_id,
            action="page_view",
            created_at=at,
        )
    )
    await db.commit()


async def _headers(db: AsyncSession, user_id: str) -> dict[str, str]:
    token = await _create_session(db, user_id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def overview_people(db_session: AsyncSession):
    owner_id, owner_email = await _create_user(
        db_session, role="admin", plan="team", name="Overview Owner"
    )
    admin_id, admin_email = await _create_user(
        db_session, role="user", plan="team", name="Overview Admin"
    )
    member_ids = []
    member_emails = []
    for index in range(3):
        user_id, email = await _create_user(
            db_session, role="user", plan="team", name=f"Overview Member {index}"
        )
        member_ids.append(user_id)
        member_emails.append(email)
    outsider_id, outsider_email = await _create_user(
        db_session, role="user", plan="team", name="Overview Outsider"
    )
    return {
        "owner_id": owner_id,
        "owner_email": owner_email,
        "admin_id": admin_id,
        "admin_email": admin_email,
        "member_ids": member_ids,
        "member_emails": member_emails,
        "outsider_id": outsider_id,
        "outsider_email": outsider_email,
    }


@pytest.mark.asyncio
async def test_overview_reconciles_with_cohorts_and_is_tenant_scoped(
    client, db_session: AsyncSession, overview_people
):
    people = overview_people
    owner_id = people["owner_id"]
    tenant = await _seed_tenant(db_session, owner_id=owner_id, max_members=10)
    await _add_member(db_session, tenant.id, people["admin_id"], role="admin")
    for member_id in people["member_ids"]:
        await _add_member(db_session, tenant.id, member_id)

    # Four roster members -> below the five-member suppression threshold.
    small_cohort = await _seed_cohort(
        db_session,
        tenant=tenant,
        owner_id=owner_id,
        member_ids=[people["admin_id"], *people["member_ids"][:2]],
        name="Secret Small Cohort",
    )
    # Five roster members -> eligible for itemisation (not returned here).
    large_cohort = await _seed_cohort(
        db_session,
        tenant=tenant,
        owner_id=owner_id,
        member_ids=[people["admin_id"], *people["member_ids"]],
        name="Secret Large Cohort",
    )
    now = datetime.now(timezone.utc)
    await _seed_submission(
        db_session,
        cohort=small_cohort,
        user_id=people["member_ids"][0],
        shared_at=now,
        title="Confidential small cohort resume",
        opened=True,
    )
    await _seed_submission(
        db_session,
        cohort=small_cohort,
        user_id=people["member_ids"][1],
        shared_at=now - timedelta(days=2),
        title="Confidential small cohort resume two",
        downloaded=True,
    )
    await _seed_submission(
        db_session,
        cohort=large_cohort,
        user_id=people["member_ids"][2],
        shared_at=now - timedelta(days=5),
        title="Confidential large cohort resume",
    )

    other_owner_id, _ = await _create_user(
        db_session, role="user", plan="team", name="Other Tenant Owner"
    )
    other_tenant = await _seed_tenant(
        db_session, owner_id=other_owner_id, max_members=10
    )
    other_cohort = await _seed_cohort(
        db_session,
        tenant=other_tenant,
        owner_id=other_owner_id,
        member_ids=[],
        name="Other Tenant Cohort",
    )
    await _seed_submission(
        db_session,
        cohort=other_cohort,
        user_id=other_owner_id,
        shared_at=now,
        title="Other tenant private resume",
    )

    headers = await _headers(db_session, owner_id)
    response = await client.get(f"/tenants/{tenant.id}/stats", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()

    # The accepted roster includes owner, admin and three members.
    assert body["accepted_members"] == 5
    assert body["member_count"] == 5
    assert body["seats_used"] == 5
    assert body["seat_limit"] == 10
    assert body["seats_available"] == 5
    assert body["seat_utilization"] == 0.5
    assert body["cohort_count"] == 2
    assert body["submission_count"] == 3
    assert body["cohort_member_count"] == 9
    assert body["cohorts_with_submissions"] == 2
    assert body["suppression"]["minimum_cohort_size"] == 5
    assert body["suppression"]["suppressed_cohorts"] == 1
    assert body["suppression"]["cohort_breakdown_visible"] is False
    assert body["activation"]["submitted"] == 3
    assert body["activation"]["opened"] == 1
    assert body["activation"]["downloaded"] == 1
    assert body["activation"]["submitting_members"] == 3
    assert body["activation"]["activation_rate"] == 0.6

    # Reconcile with the existing cohort and submission endpoints.
    cohort_response = await client.get(
        f"/tenants/{tenant.id}/cohorts", headers=headers
    )
    assert cohort_response.status_code == 200, cohort_response.text
    cohorts = cohort_response.json()
    assert len(cohorts) == body["cohort_count"]
    assert sum(row["member_count"] for row in cohorts) == body["cohort_member_count"]
    assert sum(row["resume_count"] for row in cohorts) == body["submission_count"]

    # Tenant scoping: the other tenant's cohort/submission is absent.
    assert body["submission_count"] == 3
    assert body["cohort_count"] == 2

    # No PII, document metadata or cohort names leave the aggregate payload.
    serialized = json.dumps(body)
    for secret in (
        people["owner_email"],
        people["admin_email"],
        *people["member_emails"],
        "Confidential small cohort resume",
        "Confidential large cohort resume",
        "Other tenant private resume",
        "Secret Small Cohort",
        "Secret Large Cohort",
        "secret\\end{document}",
    ):
        assert secret not in serialized

    # Owner/admin only: a non-admin member and an outsider are both denied.
    for denied_user in (people["member_ids"][0], people["outsider_id"]):
        denied = await client.get(
            f"/tenants/{tenant.id}/stats",
            headers=await _headers(db_session, denied_user),
        )
        assert denied.status_code == 403

    # A tenant admin (not just the owner) may read the overview.
    admin_response = await client.get(
        f"/tenants/{tenant.id}/stats",
        headers=await _headers(db_session, people["admin_id"]),
    )
    assert admin_response.status_code == 200, admin_response.text


@pytest.mark.asyncio
async def test_overview_activation_milestones_and_period_trends(
    client, db_session: AsyncSession, overview_people
):
    people = overview_people
    tenant = await _seed_tenant(db_session, owner_id=people["owner_id"], max_members=10)
    for member_id in people["member_ids"][:2]:
        await _add_member(db_session, tenant.id, member_id)
    cohort = await _seed_cohort(
        db_session,
        tenant=tenant,
        owner_id=people["owner_id"],
        member_ids=[*people["member_ids"][:2]],
    )
    now = datetime.now(timezone.utc)
    # 4 explicit submissions: today, 10d, 40d and 100d old.
    await _seed_submission(
        db_session,
        cohort=cohort,
        user_id=people["member_ids"][0],
        shared_at=now,
        opened=True,
        downloaded=True,
    )
    await _seed_submission(
        db_session,
        cohort=cohort,
        user_id=people["member_ids"][1],
        shared_at=now - timedelta(days=10),
        opened=True,
    )
    await _seed_submission(
        db_session,
        cohort=cohort,
        user_id=people["member_ids"][0],
        shared_at=now - timedelta(days=40),
    )
    await _seed_submission(
        db_session,
        cohort=cohort,
        user_id=people["member_ids"][1],
        shared_at=now - timedelta(days=100),
    )
    await _seed_activity(db_session, people["member_ids"][0], now)
    await _seed_activity(db_session, people["member_ids"][1], now - timedelta(days=10))
    await _seed_activity(db_session, people["member_ids"][0], now - timedelta(days=40))
    await _seed_activity(
        db_session, people["outsider_id"], now
    )  # not a tenant member

    response = await client.get(
        f"/tenants/{tenant.id}/stats",
        headers=await _headers(db_session, people["owner_id"]),
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["activation"]["submitted"] == 4
    assert body["activation"]["opened"] == 2
    assert body["activation"]["downloaded"] == 1
    assert body["activation"]["submitting_members"] == 2
    # Owner + two members accepted; two distinct submitters.
    assert body["accepted_members"] == 3
    assert body["activation"]["activation_rate"] == 0.6667

    trends = body["trends"]
    assert set(trends) == {"7", "30", "90"}
    for days in (7, 30, 90):
        points = trends[str(days)]
        assert len(points) == days
        assert points[-1]["date"] == now.date().isoformat()
        assert points[0]["date"] == (
            now.date() - timedelta(days=days - 1)
        ).isoformat()

    assert sum(p["submissions"] for p in trends["7"]) == 1
    assert sum(p["submissions"] for p in trends["30"]) == 2
    assert sum(p["submissions"] for p in trends["90"]) == 3
    # 100-day-old submission is outside even the 90-day window.
    assert body["submission_count"] == 4

    assert sum(p["active_members"] for p in trends["7"]) == 1
    assert sum(p["active_members"] for p in trends["30"]) == 2
    assert sum(p["active_members"] for p in trends["90"]) == 3
    assert body["active_members"] == 2
    assert body["active_members_window_days"] == 30
    # Roster joins are included, but no non-member activity is counted.
    assert sum(p["members_joined"] for p in trends["7"]) == 3


@pytest.mark.asyncio
async def test_overview_pending_invites_are_counted_without_email_leak(
    client, db_session: AsyncSession, overview_people
):
    tenant = await _seed_tenant(db_session, owner_id=overview_people["owner_id"])
    other_tenant = await _seed_tenant(
        db_session, owner_id=overview_people["outsider_id"]
    )
    redis = await get_redis_cache_client()
    own_key = f"tenant_invite:test_{uuid4().hex}"
    other_key = f"tenant_invite:test_{uuid4().hex}"
    invitee_email = f"test_{uuid4().hex}@example.com"
    try:
        await redis.set(
            own_key,
            json.dumps(
                {
                    "tenant_id": tenant.id,
                    "role": "member",
                    "email": invitee_email,
                    "cohort_id": None,
                }
            ),
            ex=60,
        )
        await redis.set(
            other_key,
            json.dumps(
                {
                    "tenant_id": other_tenant.id,
                    "role": "member",
                    "email": f"test_{uuid4().hex}@example.com",
                    "cohort_id": None,
                }
            ),
            ex=60,
        )
        response = await client.get(
            f"/tenants/{tenant.id}/stats",
            headers=await _headers(db_session, overview_people["owner_id"]),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["invited_members"] == 1
        assert body["pending_invites_available"] is True
        assert invitee_email not in json.dumps(body)
    finally:
        await redis.delete(own_key, other_key)


@pytest.mark.asyncio
async def test_overview_empty_tenant_returns_zeroed_aggregates(
    client, db_session: AsyncSession, overview_people
):
    tenant = await _seed_tenant(
        db_session, owner_id=overview_people["owner_id"], max_members=5
    )
    response = await client.get(
        f"/tenants/{tenant.id}/stats",
        headers=await _headers(db_session, overview_people["owner_id"]),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["accepted_members"] == 1
    assert body["seats_available"] == 4
    assert body["invited_members"] == 0
    assert body["cohort_count"] == 0
    assert body["cohort_member_count"] == 0
    assert body["submission_count"] == 0
    assert body["activation"] == {
        "submitted": 0,
        "opened": 0,
        "downloaded": 0,
        "submitting_members": 0,
        "activation_rate": 0.0,
    }
    for days in (7, 30, 90):
        assert len(body["trends"][str(days)]) == days
        assert all(point["submissions"] == 0 for point in body["trends"][str(days)])
        assert all(
            point["active_members"] == 0 for point in body["trends"][str(days)]
        )


@pytest.mark.asyncio
async def test_overview_reads_existing_schema_only(
    client, db_session: AsyncSession, overview_people
):
    """The overview works against the deployed head without adding a migration."""
    revision = (
        await db_session.execute(text("SELECT version_num FROM alembic_version"))
    ).scalar_one()
    assert revision
    tenant = await _seed_tenant(db_session, owner_id=overview_people["owner_id"])
    response = await client.get(
        f"/tenants/{tenant.id}/stats",
        headers=await _headers(db_session, overview_people["owner_id"]),
    )
    assert response.status_code == 200, response.text
