"""Collaboration usage analytics (C10 / #2080).

Covers comment/mention/review counts, distinct participants, explicit
time-to-review denominators, tenant/cohort reconciliation, five-member
suppression, date filtering, privacy and admin-only access.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import models

START_DAY = "2024-03-01"
END_DAY = "2024-03-07"
BASE_TIME = datetime(2024, 3, 1, 9, 0, tzinfo=timezone.utc)
SECRET_COMMENT = "PRIVATE comment body must never leave the admin aggregate"
SECRET_EMAIL_PREFIX = "test_ca_"
SECRET_REVIEWER = "Reviewer DEADBEEF"


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def _create_user(db: AsyncSession, *, role: str = "user") -> str:
    user_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, 'Collaboration Analytics User', :role, true, "
            "'free', 'active', false)"
        ),
        {
            "id": user_id,
            "email": f"{SECRET_EMAIL_PREFIX}{user_id.replace('-', '')}@example.com",
            "role": role,
        },
    )
    await db.flush()
    return user_id


async def _session_headers(db: AsyncSession, user_id: str) -> dict[str, str]:
    token = f"test_sess_ca_{uuid.uuid4().hex}"
    await db.execute(
        text('INSERT INTO session (id, "userId", "expiresAt", token) VALUES (:id, :uid, :exp, :tok)'),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "exp": datetime.now(timezone.utc) + timedelta(days=1),
            "tok": token,
        },
    )
    await db.flush()
    return {"Authorization": f"Bearer {token}"}


async def _admin_headers(db: AsyncSession) -> dict[str, str]:
    return await _session_headers(db, await _create_user(db, role="admin"))


async def _seed_tenant(
    db: AsyncSession,
    *,
    name: str,
    member_count: int,
    cohort_sizes: tuple[int, ...] = (),
) -> tuple[models.Tenant, list[str], list[models.Workspace]]:
    owner_id = await _create_user(db)
    tenant = models.Tenant(
        slug=f"test-ca-{uuid.uuid4().hex[:12]}",
        name=name,
        owner_id=owner_id,
        plan_id="agency",
        max_members=200,
        active=True,
    )
    db.add(tenant)
    await db.flush()
    members = [owner_id]
    for _ in range(max(0, member_count - 1)):
        members.append(await _create_user(db))
    for user_id in members:
        db.add(
            models.TenantMember(
                tenant_id=tenant.id,
                user_id=user_id,
                role="member",
                joined_at=BASE_TIME,
            )
        )
    cohorts: list[models.Workspace] = []
    for index, size in enumerate(cohort_sizes):
        cohort = models.Workspace(
            name=f"{name} Cohort {index + 1}",
            owner_id=owner_id,
            tenant_id=tenant.id,
            plan_id="agency",
            max_members=200,
        )
        db.add(cohort)
        await db.flush()
        for user_id in members[: min(size, len(members))]:
            db.add(
                models.WorkspaceMember(
                    workspace_id=cohort.id,
                    user_id=user_id,
                    role="editor",
                    invited_by=owner_id,
                    joined_at=BASE_TIME,
                )
            )
        cohorts.append(cohort)
    await db.flush()
    return tenant, members, cohorts


async def _seed_resume(
    db: AsyncSession,
    *,
    owner_id: str,
    cohort: models.Workspace | None,
    review_enabled: bool = True,
    shared_at: datetime = BASE_TIME,
    token: str | None = None,
) -> models.Resume:
    share_token = token or f"ca-token-{uuid.uuid4().hex}"
    resume = models.Resume(
        user_id=owner_id,
        title="Private resume title",
        latex_content="PRIVATE LaTeX document body",
        share_token=share_token,
        resume_settings={"share_review_comments": review_enabled},
    )
    db.add(resume)
    await db.flush()
    if cohort is not None:
        db.add(
            models.WorkspaceResume(
                workspace_id=cohort.id,
                resume_id=resume.id,
                shared_by=owner_id,
                shared_at=shared_at,
            )
        )
        await db.flush()
    return resume


async def _add_comment(
    db: AsyncSession,
    *,
    resume: models.Resume,
    cohort: models.Workspace,
    author_id: str,
    resolved: bool = False,
    created_at: datetime = BASE_TIME,
) -> models.ResumeComment:
    comment = models.ResumeComment(
        resume_id=resume.id,
        workspace_id=cohort.id,
        author_id=author_id,
        content=SECRET_COMMENT,
        resolved=resolved,
        created_at=created_at,
    )
    db.add(comment)
    await db.flush()
    return comment


async def _add_mention(
    db: AsyncSession,
    *,
    comment: models.ResumeComment,
    resume: models.Resume,
    mentioned_user_id: str,
    delivered: bool = False,
    attempts: int = 0,
    created_at: datetime = BASE_TIME,
) -> models.ResumeCommentMention:
    mention = models.ResumeCommentMention(
        comment_id=comment.id,
        resume_id=resume.id,
        mentioned_user_id=mentioned_user_id,
        delivery_sent_at=created_at + timedelta(minutes=5) if delivered else None,
        delivery_attempts=attempts,
        created_at=created_at,
    )
    db.add(mention)
    await db.flush()
    return mention


async def _add_review_comment(
    db: AsyncSession,
    *,
    resume: models.Resume,
    reviewer_label: str = SECRET_REVIEWER,
    resolved: bool = False,
    created_at: datetime = BASE_TIME,
) -> models.ResumeReviewComment:
    comment = models.ResumeReviewComment(
        resume_id=resume.id,
        share_token_hash=_token_hash(resume.share_token or ""),
        reviewer_label=reviewer_label,
        content=SECRET_COMMENT,
        resolved=resolved,
        created_at=created_at,
        updated_at=created_at,
    )
    db.add(comment)
    await db.flush()
    return comment


async def _add_view(
    db: AsyncSession,
    *,
    resume: models.Resume,
    viewed_at: datetime = BASE_TIME,
) -> models.ResumeView:
    view = models.ResumeView(
        resume_id=resume.id,
        share_token=resume.share_token or f"ca-token-{uuid.uuid4().hex}",
        viewed_at=viewed_at,
        user_agent="PRIVATE user agent",
        referrer="https://private.example",
        session_id=uuid.uuid4().hex[:16],
    )
    db.add(view)
    await db.flush()
    return view


async def _get_collaboration(
    client: AsyncClient,
    headers: dict[str, str] | None,
    *,
    tenant_id: str | None = None,
) -> dict:
    params: dict[str, str] = {"start_date": START_DAY, "end_date": END_DAY}
    if tenant_id:
        params["tenant_id"] = tenant_id
    response = await client.get("/admin/analytics/collaboration", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _tenant_row(body: dict, tenant_id: str) -> dict:
    return next(row for row in body["tenants"] if row["tenant_id"] == tenant_id)


class TestCollaborationAnalyticsCounts:
    async def test_counts_distinct_participants_and_rates(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        headers = await _admin_headers(db_session)
        tenant, members, cohorts = await _seed_tenant(
            db_session, name="Counts University", member_count=6, cohort_sizes=(6,)
        )
        cohort = cohorts[0]
        resume = await _seed_resume(db_session, owner_id=members[0], cohort=cohort)
        second_resume = await _seed_resume(
            db_session, owner_id=members[0], cohort=cohort, token=f"ca-token-{uuid.uuid4().hex}"
        )
        third_resume = await _seed_resume(
            db_session,
            owner_id=members[0],
            cohort=cohort,
            review_enabled=False,
            token=f"ca-token-{uuid.uuid4().hex}",
        )

        comments: list[models.ResumeComment] = []
        for index in range(6):
            comments.append(
                await _add_comment(
                    db_session,
                    resume=resume,
                    cohort=cohort,
                    author_id=members[index % 2],
                    resolved=index < 3,
                    created_at=BASE_TIME + timedelta(minutes=index),
                )
            )
        for index in range(3):
            await _add_mention(
                db_session,
                comment=comments[index],
                resume=resume,
                mentioned_user_id=members[2 + (index % 2)],
                delivered=index < 2,
                attempts=2 if index < 2 else 1,
            )
        await _add_review_comment(
            db_session, resume=resume, reviewer_label="Reviewer AAAA", resolved=True
        )
        await _add_review_comment(
            db_session, resume=resume, reviewer_label="Reviewer AAAA", resolved=True
        )
        await _add_review_comment(
            db_session, resume=resume, reviewer_label="Reviewer BBBB", resolved=False
        )
        await _add_review_comment(
            db_session,
            resume=second_resume,
            reviewer_label="Reviewer AAAA",
            resolved=False,
        )
        await _add_view(db_session, resume=resume)
        await _add_view(db_session, resume=resume)
        await _add_view(db_session, resume=second_resume)
        # Review-disabled link opens are intentionally excluded.
        await _add_view(db_session, resume=third_resume)

        body = await _get_collaboration(client, headers, tenant_id=tenant.id)
        selected = body["selected_tenant"]
        activity = selected["activity"]

        assert activity["comments"] == {
            "total": 6,
            "resolved": 3,
            "resolution_rate": 50.0,
            "resolution_denominator": 6,
            "distinct_authors": 2,
        }
        assert activity["mentions"]["total"] == 3
        assert activity["mentions"]["delivered"] == 2
        assert activity["mentions"]["pending"] == 1
        assert activity["mentions"]["delivery_denominator"] == 3
        assert activity["mentions"]["delivery_rate"] == 66.67
        assert activity["mentions"]["delivery_attempts"] == 5
        assert activity["mentions"]["distinct_mentioned_users"] == 2
        assert activity["review_comments"] == {
            "total": 4,
            "resolved": 2,
            "resolution_rate": 50.0,
            "resolution_denominator": 4,
            "distinct_reviewers": 3,
            "distinct_review_links": 2,
        }
        assert activity["review_links"] == {"opens": 3, "distinct_links_opened": 2}

        # The platform summary covers the same rows and may include other
        # tenants from concurrent test data, so assert at least the seeded set.
        assert body["summary"]["comments"]["total"] >= 6
        assert body["summary"]["comments"]["distinct_authors"] >= 2
        assert body["summary"]["mentions"]["total"] >= 3
        assert body["summary"]["review_comments"]["total"] >= 4
        assert body["summary"]["review_comments"]["distinct_reviewers"] >= 3
        assert body["summary"]["review_links"]["opens"] >= 3

        row = _tenant_row(body, tenant.id)
        assert row["member_count"] == 6
        assert row["cohort_count"] == 1
        assert row["cohort_member_count"] == 6
        assert row["submitted_resume_count"] == 3
        assert row["suppressed"] is False
        assert row["activity"]["comments"]["total"] == 6

        raw = json.dumps(body)
        for secret in (
            SECRET_COMMENT,
            SECRET_REVIEWER,
            "PRIVATE LaTeX document body",
            "PRIVATE user agent",
            "https://private.example",
            "Private resume title",
        ):
            assert secret not in raw
        for user_id in members:
            assert user_id not in raw
        assert "@example.com" not in raw
        assert "reviewer_label" not in raw
        assert "author_id" not in raw
        assert "resume_id" not in raw
        assert "email" not in raw
        assert "content" not in raw


class TestCollaborationTimeToFirstReview:
    async def test_time_to_first_review_has_explicit_denominator(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        headers = await _admin_headers(db_session)
        tenant, members, cohorts = await _seed_tenant(
            db_session, name="Review Timing College", member_count=6, cohort_sizes=(6,)
        )
        cohort = cohorts[0]
        for hour in range(1, 6):
            resume = await _seed_resume(
                db_session,
                owner_id=members[0],
                cohort=cohort,
                token=f"ca-token-{uuid.uuid4().hex}",
                shared_at=BASE_TIME,
            )
            await _add_review_comment(
                db_session,
                resume=resume,
                created_at=BASE_TIME + timedelta(hours=hour),
            )
        # Sixth submission has no review and remains in the denominator.
        await _seed_resume(
            db_session,
            owner_id=members[0],
            cohort=cohort,
            token=f"ca-token-{uuid.uuid4().hex}",
            shared_at=BASE_TIME,
        )

        body = await _get_collaboration(client, headers, tenant_id=tenant.id)
        timing = body["selected_tenant"]["activity"]["time_to_first_review"]
        assert timing["eligible_submissions"] == 6
        assert timing["reviewed_submissions"] == 5
        assert timing["denominator"] == 6
        assert timing["median_hours"] == 3.0
        assert timing["p90_hours"] == 4.6
        assert timing["suppressed"] is False

        # Platform summary uses the same tenant-cohort denominator.
        assert body["summary"]["time_to_first_review"]["denominator"] == 6
        assert body["summary"]["time_to_first_review"]["reviewed_submissions"] == 5

    async def test_time_to_first_review_is_suppressed_below_five_reviews(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        headers = await _admin_headers(db_session)
        tenant, members, cohorts = await _seed_tenant(
            db_session, name="Small Review Sample", member_count=6, cohort_sizes=(6,)
        )
        cohort = cohorts[0]
        for hour in range(1, 5):
            resume = await _seed_resume(
                db_session,
                owner_id=members[0],
                cohort=cohort,
                token=f"ca-token-{uuid.uuid4().hex}",
            )
            await _add_review_comment(
                db_session,
                resume=resume,
                created_at=BASE_TIME + timedelta(hours=hour),
            )
        await _seed_resume(
            db_session,
            owner_id=members[0],
            cohort=cohort,
            token=f"ca-token-{uuid.uuid4().hex}",
        )

        body = await _get_collaboration(client, headers, tenant_id=tenant.id)
        timing = body["selected_tenant"]["activity"]["time_to_first_review"]
        assert timing["denominator"] == 5
        assert timing["reviewed_submissions"] == 4
        assert timing["median_hours"] is None
        assert timing["p90_hours"] is None
        assert timing["suppressed"] is True


class TestCollaborationTenantReconciliation:
    async def test_tenant_and_cohort_counts_reconcile(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        headers = await _admin_headers(db_session)
        tenant, members, cohorts = await _seed_tenant(
            db_session,
            name="Reconciliation Institute",
            member_count=6,
            cohort_sizes=(6, 2),
        )
        for index, cohort in enumerate(cohorts):
            resume = await _seed_resume(
                db_session,
                owner_id=members[0],
                cohort=cohort,
                token=f"ca-token-{uuid.uuid4().hex}",
            )
            if index == 0:
                await _add_comment(
                    db_session,
                    resume=resume,
                    cohort=cohort,
                    author_id=members[1],
                )
        # Third submission in the first cohort.
        await _seed_resume(
            db_session,
            owner_id=members[0],
            cohort=cohorts[0],
            token=f"ca-token-{uuid.uuid4().hex}",
        )

        member_count = int(
            (
                await db_session.execute(
                    select(func.count(models.TenantMember.user_id)).where(
                        models.TenantMember.tenant_id == tenant.id
                    )
                )
            ).scalar()
            or 0
        )
        cohort_member_count = int(
            (
                await db_session.execute(
                    select(func.count(models.WorkspaceMember.user_id))
                    .select_from(models.Workspace)
                    .join(
                        models.WorkspaceMember,
                        models.WorkspaceMember.workspace_id == models.Workspace.id,
                    )
                    .where(models.Workspace.tenant_id == tenant.id)
                )
            ).scalar()
            or 0
        )
        submission_count = int(
            (
                await db_session.execute(
                    select(func.count(models.WorkspaceResume.resume_id))
                    .select_from(models.Workspace)
                    .join(
                        models.WorkspaceResume,
                        models.WorkspaceResume.workspace_id == models.Workspace.id,
                    )
                    .where(models.Workspace.tenant_id == tenant.id)
                )
            ).scalar()
            or 0
        )

        body = await _get_collaboration(client, headers, tenant_id=tenant.id)
        row = _tenant_row(body, tenant.id)
        assert row["member_count"] == member_count == 6
        assert row["cohort_count"] == 2
        assert row["cohort_member_count"] == cohort_member_count == 8
        assert row["submitted_resume_count"] == submission_count == 3

        selected = body["selected_tenant"]
        assert selected["reconciliation"]["member_count"] == member_count
        assert selected["reconciliation"]["cohort_count"] == 2
        assert selected["reconciliation"]["cohort_member_count"] == cohort_member_count
        assert selected["reconciliation"]["submitted_resume_count"] == submission_count
        assert (
            selected["reconciliation"]["visible_cohort_member_count"]
            + selected["reconciliation"]["suppressed_cohort_member_count"]
            == cohort_member_count
        )
        assert (
            selected["reconciliation"]["visible_cohort_submission_count"]
            + selected["reconciliation"]["suppressed_cohort_submission_count"]
            == submission_count
        )

        reconciliation = body["reconciliation"]
        assert (
            reconciliation["visible_tenant_member_count"]
            + reconciliation["suppressed_tenant_member_count"]
            == reconciliation["tenant_member_count"]
        )
        assert (
            reconciliation["visible_cohort_member_count"]
            + reconciliation["suppressed_cohort_member_count"]
            == reconciliation["cohort_member_count"]
        )
        assert (
            reconciliation["visible_cohort_submission_count"]
            + reconciliation["suppressed_cohort_submission_count"]
            == reconciliation["cohort_submission_count"]
        )
        assert reconciliation["distinct_tenant_members"] <= reconciliation["tenant_member_count"]

        # Suppressed cohorts still reconcile to the source tables.
        cohort_rows = selected["cohorts"]
        suppressed = [row for row in cohort_rows if row["suppressed"]]
        assert len(suppressed) == 1
        assert suppressed[0]["member_count"] is None
        assert suppressed[0]["activity"] is None
        assert suppressed[0]["suppression_reason"] == "fewer_than_minimum_members"


class TestCollaborationSuppression:
    async def test_small_tenants_and_small_cohorts_are_hidden(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        headers = await _admin_headers(db_session)
        small_tenant, small_members, small_cohorts = await _seed_tenant(
            db_session, name="Tiny Tenant", member_count=3, cohort_sizes=(3,)
        )
        small_resume = await _seed_resume(
            db_session, owner_id=small_members[0], cohort=small_cohorts[0]
        )
        await _add_comment(
            db_session,
            resume=small_resume,
            cohort=small_cohorts[0],
            author_id=small_members[1],
        )

        big_tenant, big_members, big_cohorts = await _seed_tenant(
            db_session, name="Large Tenant", member_count=6, cohort_sizes=(6, 2)
        )
        big_resume = await _seed_resume(
            db_session, owner_id=big_members[0], cohort=big_cohorts[0]
        )
        await _add_comment(
            db_session,
            resume=big_resume,
            cohort=big_cohorts[0],
            author_id=big_members[1],
        )

        body = await _get_collaboration(client, headers)
        small_row = _tenant_row(body, small_tenant.id)
        assert small_row["suppressed"] is True
        assert small_row["suppression_reason"] == "fewer_than_minimum_members"
        assert small_row["member_count"] is None
        assert small_row["cohort_count"] is None
        assert small_row["activity"] is None
        assert body["suppressed_tenants"] >= 1

        big_row = _tenant_row(body, big_tenant.id)
        assert big_row["suppressed"] is False
        assert big_row["activity"] is not None

        suppressed_body = await _get_collaboration(client, headers, tenant_id=small_tenant.id)
        selected = suppressed_body["selected_tenant"]
        assert selected["suppressed"] is True
        assert selected["activity"] is None
        assert selected["cohorts"] == []

        # The two-member cohort inside a visible tenant is suppressed too.
        drilldown = await _get_collaboration(client, headers, tenant_id=big_tenant.id)
        cohort_rows = drilldown["selected_tenant"]["cohorts"]
        assert len(cohort_rows) == 2
        by_name = {row["name"]: row for row in cohort_rows}
        small_cohort_name = big_cohorts[1].name
        assert by_name[small_cohort_name]["suppressed"] is True
        assert by_name[small_cohort_name]["member_count"] is None
        assert by_name[small_cohort_name]["activity"] is None
        assert drilldown["selected_tenant"]["suppressed_cohort_count"] == 1


class TestCollaborationDateFiltersAndAccess:
    async def test_activity_outside_the_selected_range_is_excluded(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        headers = await _admin_headers(db_session)
        tenant, members, cohorts = await _seed_tenant(
            db_session, name="Date Filter University", member_count=6, cohort_sizes=(6,)
        )
        resume = await _seed_resume(db_session, owner_id=members[0], cohort=cohorts[0])
        await _add_comment(
            db_session,
            resume=resume,
            cohort=cohorts[0],
            author_id=members[1],
            created_at=BASE_TIME,
        )
        await _add_comment(
            db_session,
            resume=resume,
            cohort=cohorts[0],
            author_id=members[1],
            created_at=datetime(2023, 1, 1, tzinfo=timezone.utc),
        )
        await _add_review_comment(
            db_session,
            resume=resume,
            created_at=BASE_TIME,
        )
        await _add_review_comment(
            db_session,
            resume=resume,
            created_at=datetime(2023, 1, 1, tzinfo=timezone.utc),
        )

        body = await _get_collaboration(client, headers, tenant_id=tenant.id)
        activity = body["selected_tenant"]["activity"]
        assert activity["comments"]["total"] == 1
        assert activity["review_comments"]["total"] == 1
        assert body["filters"]["start_date"] == START_DAY
        assert body["filters"]["end_date"] == END_DAY

    async def test_requires_an_admin_session(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        non_admin = await _session_headers(db_session, await _create_user(db_session))
        response = await client.get("/admin/analytics/collaboration", headers=non_admin)
        assert response.status_code == 403

        anonymous = await client.get("/admin/analytics/collaboration")
        assert anonymous.status_code == 401

    async def test_unknown_and_malformed_tenant_filters_fail_cleanly(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        headers = await _admin_headers(db_session)
        missing = await client.get(
            "/admin/analytics/collaboration",
            params={"days": 7, "tenant_id": str(uuid.uuid4())},
            headers=headers,
        )
        assert missing.status_code == 404

        malformed = await client.get(
            "/admin/analytics/collaboration",
            params={"days": 7, "tenant_id": "not-a-uuid"},
            headers=headers,
        )
        assert malformed.status_code == 422

        inverted = await client.get(
            "/admin/analytics/collaboration",
            params={"start_date": END_DAY, "end_date": START_DAY},
            headers=headers,
        )
        assert inverted.status_code == 422
