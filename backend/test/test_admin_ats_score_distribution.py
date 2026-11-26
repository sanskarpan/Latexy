"""Admin ATS score distribution: buckets, baselines, math, filters, privacy."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.admin_ats_score_service import bucket_for_score

SECRET_RESUME = "SECRET_RESUME_CONTENT_2091_MUST_NOT_LEAK"
SECRET_JD = "SECRET_JOB_DESCRIPTION_2091_MUST_NOT_LEAK"
SECRET_CHANGES = "SECRET_CHANGES_PAYLOAD_2091_MUST_NOT_LEAK"


@pytest.fixture(autouse=True)
async def _isolate_optimizations(db_session: AsyncSession):
    await db_session.execute(text("DELETE FROM optimizations"))
    await db_session.commit()
    yield
    await db_session.execute(text("DELETE FROM optimizations"))
    await db_session.commit()


async def _create_user(
    db: AsyncSession,
    *,
    role: str = "user",
    plan: str = "pro",
    email: str | None = None,
) -> tuple[str, dict[str, str]]:
    user_id = str(uuid.uuid4())
    token = f"test_sess_ats_2091_{uuid.uuid4().hex}"
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, 'ATS Score User', :role, true, :plan, 'active', false)"
        ),
        {
            "id": user_id,
            "email": email or f"ats2091_{uuid.uuid4().hex[:8]}@example.com",
            "role": role,
            "plan": plan,
        },
    )
    await db.execute(
        text('INSERT INTO session (id, "userId", "expiresAt", token) VALUES (:id, :uid, :exp, :tok)'),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "exp": datetime.now(timezone.utc) + timedelta(days=1),
            "tok": token,
        },
    )
    await db.commit()
    return user_id, {"Authorization": f"Bearer {token}"}


async def _admin_headers(db: AsyncSession) -> dict[str, str]:
    _user_id, headers = await _create_user(db, role="admin")
    return headers


async def _create_resume(db: AsyncSession, *, user_id: str) -> str:
    resume_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO resumes (id, user_id, title, latex_content, metadata, created_at) "
            "VALUES (:id, :uid, 'ATS Score Resume', :latex, CAST(:metadata AS jsonb), :created)"
        ),
        {
            "id": resume_id,
            "uid": user_id,
            "latex": SECRET_RESUME,
            "metadata": json.dumps({"last_persona": "startup"}),
            "created": datetime.now(timezone.utc) - timedelta(days=1),
        },
    )
    await db.commit()
    return resume_id


async def _seed_optimization(
    db: AsyncSession,
    *,
    user_id: str,
    resume_id: str,
    before: float | None,
    after: float | None,
    industry: str | None = "tech_saas",
    profile: str | None = "startup",
    created_at: datetime | None = None,
    is_auto_save: bool = False,
    is_checkpoint: bool = False,
) -> str:
    optimization_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO optimizations "
            "(id, user_id, resume_id, job_description, original_latex, optimized_latex, "
            "provider, model, ats_score, ats_score_before, ats_score_after, industry, profile, "
            "changes_made, is_auto_save, is_checkpoint, created_at) "
            "VALUES (:id, :uid, :resume, :jd, :original, :optimized, 'openai', 'gpt-4o', "
            ":after, :before, :after, :industry, :profile, CAST(:changes AS jsonb), "
            ":auto_save, :checkpoint, :created)"
        ),
        {
            "id": optimization_id,
            "uid": user_id,
            "resume": resume_id,
            "jd": SECRET_JD,
            "original": SECRET_RESUME,
            "optimized": SECRET_RESUME,
            "before": before,
            "after": after,
            "industry": industry,
            "profile": profile,
            "changes": json.dumps([{"section": "summary", "reason": SECRET_CHANGES}]),
            "auto_save": is_auto_save,
            "checkpoint": is_checkpoint,
            "created": created_at or (datetime.now(timezone.utc) - timedelta(hours=2)),
        },
    )
    await db.commit()
    return optimization_id


async def _seed_cohort(
    db: AsyncSession,
    *,
    count: int,
    plan: str,
    industry: str,
    profile: str = "startup",
    before: float = 50.0,
    after: float = 70.0,
) -> list[str]:
    user_ids: list[str] = []
    for _ in range(count):
        user_id, _headers = await _create_user(db, plan=plan)
        resume_id = await _create_resume(db, user_id=user_id)
        await _seed_optimization(
            db,
            user_id=user_id,
            resume_id=resume_id,
            before=before,
            after=after,
            industry=industry,
            profile=profile,
        )
        user_ids.append(user_id)
    return user_ids


class TestAtsScoreDistributionEndpoint:
    async def test_admin_only_access(self, client: AsyncClient, db_session: AsyncSession):
        _uid, user_headers = await _create_user(db_session)
        assert (
            await client.get("/admin/analytics/ats-score-distribution", headers=user_headers)
        ).status_code == 403

        _sid, support_headers = await _create_user(db_session, role="support")
        assert (
            await client.get("/admin/analytics/ats-score-distribution", headers=support_headers)
        ).status_code == 403
        assert (await client.get("/admin/analytics/ats-score-distribution")).status_code == 401

        admin = await _admin_headers(db_session)
        allowed = await client.get("/admin/analytics/ats-score-distribution", headers=admin)
        assert allowed.status_code == 200, allowed.text
        assert allowed.json()["privacy"]["aggregate_only"] is True

    async def test_bucket_boundaries(self, client: AsyncClient, db_session: AsyncSession):
        scores = [0.0, 9.99, 10.0, 19.99, 20.0, 89.99, 90.0, 100.0]
        users = [await _create_user(db_session, plan="pro") for _ in range(5)]
        for index, score in enumerate(scores):
            user_id, _headers = users[index % len(users)]
            resume_id = await _create_resume(db_session, user_id=user_id)
            await _seed_optimization(
                db_session,
                user_id=user_id,
                resume_id=resume_id,
                before=score,
                after=score,
                industry="tech_saas",
            )

        # Direct boundary checks keep the bucket contract explicit.
        assert bucket_for_score(0.0) == "0-9"
        assert bucket_for_score(9.99) == "0-9"
        assert bucket_for_score(10.0) == "10-19"
        assert bucket_for_score(89.99) == "80-89"
        assert bucket_for_score(90.0) == "90-100"
        assert bucket_for_score(100.0) == "90-100"

        headers = await _admin_headers(db_session)
        response = await client.get(
            "/admin/analytics/ats-score-distribution?days=30&industry=tech_saas",
            headers=headers,
        )
        assert response.status_code == 200, response.text
        buckets = {row["bucket"]: row for row in response.json()["distribution"]}
        assert buckets["0-9"]["before_count"] == 2
        assert buckets["0-9"]["after_count"] == 2
        assert buckets["10-19"]["before_count"] == 2
        assert buckets["20-29"]["before_count"] == 1
        assert buckets["80-89"]["before_count"] == 1
        assert buckets["90-100"]["before_count"] == 2
        assert buckets["90-100"]["after_count"] == 2
        assert sum(row["before_count"] for row in buckets.values()) == len(scores)
        assert sum(row["after_count"] for row in buckets.values()) == len(scores)

    async def test_missing_baseline_is_excluded_and_counted(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        users = await _seed_cohort(
            db_session,
            count=5,
            plan="pro",
            industry="consulting",
            before=40.0,
            after=60.0,
        )
        for user_id in users[:2]:
            resume_id = await _create_resume(db_session, user_id=user_id)
            await _seed_optimization(
                db_session,
                user_id=user_id,
                resume_id=resume_id,
                before=None,
                after=80.0,
                industry="consulting",
            )

        headers = await _admin_headers(db_session)
        payload = (
            await client.get(
                "/admin/analytics/ats-score-distribution?days=30&industry=consulting",
                headers=headers,
            )
        ).json()
        assert payload["totals"]["runs"] == 5
        assert payload["totals"]["users"] == 5
        assert payload["excluded"]["missing_baseline"] == 2
        assert payload["reconciliation"]["missing_baseline"] == 2
        assert sum(row["before_count"] for row in payload["distribution"]) == 5
        assert payload["reconciliation"]["reconciled"] is True

    async def test_improvement_math(self, client: AsyncClient, db_session: AsyncSession):
        pairs = [(50.0, 60.0), (50.0, 70.0), (60.0, 55.0), (70.0, 70.0), (40.0, 70.0)]
        users = [await _create_user(db_session, plan="pro") for _ in range(5)]
        for index, (before, after) in enumerate(pairs):
            user_id, _headers = users[index]
            resume_id = await _create_resume(db_session, user_id=user_id)
            await _seed_optimization(
                db_session,
                user_id=user_id,
                resume_id=resume_id,
                before=before,
                after=after,
                industry="finance_banking",
            )

        headers = await _admin_headers(db_session)
        payload = (
            await client.get(
                "/admin/analytics/ats-score-distribution?days=30&industry=finance_banking",
                headers=headers,
            )
        ).json()
        totals = payload["totals"]
        # Deltas: 10, 20, -5, 0, 30.
        assert totals["runs"] == 5
        assert totals["mean_delta"] == 11.0
        assert totals["median_delta"] == 10.0
        assert totals["median_improvement"] == 10.0
        assert totals["median_positive_delta"] == 20.0
        assert totals["improved"] == 3
        assert totals["unchanged"] == 1
        assert totals["declined"] == 1
        assert totals["improvement_rate_pct"] == 60.0
        assert totals["mean_before"] == 54.0
        assert totals["mean_after"] == 65.0

    async def test_industry_and_plan_filters(self, client: AsyncClient, db_session: AsyncSession):
        await _seed_cohort(
            db_session, count=5, plan="pro", industry="tech_saas", before=50.0, after=75.0
        )
        await _seed_cohort(
            db_session, count=5, plan="free", industry="healthcare", before=60.0, after=55.0
        )
        headers = await _admin_headers(db_session)

        tech = (
            await client.get(
                "/admin/analytics/ats-score-distribution?days=30&industry=tech_saas",
                headers=headers,
            )
        ).json()
        assert tech["totals"]["runs"] == 5
        assert tech["filters"]["industry"] == ["tech_saas"]
        assert [row["industry"] for row in tech["by_industry"]] == ["tech_saas"]
        assert tech["totals"]["improvement_rate_pct"] == 100.0

        free = (
            await client.get(
                "/admin/analytics/ats-score-distribution?days=30&plan=free",
                headers=headers,
            )
        ).json()
        assert free["totals"]["runs"] == 5
        assert free["totals"]["improvement_rate_pct"] == 0.0
        assert [row["plan"] for row in free["by_plan"]] == ["free"]

        both = (
            await client.get(
                "/admin/analytics/ats-score-distribution?days=30&industry=tech_saas&plan=free",
                headers=headers,
            )
        ).json()
        assert both["totals"]["runs"] == 0
        assert both["suppressed"] is False

        unknown_filter = (
            await client.get(
                "/admin/analytics/ats-score-distribution?days=30&industry=not_a_profile",
                headers=headers,
            )
        ).json()
        assert unknown_filter["totals"]["runs"] == 0
        assert unknown_filter["filters"]["industry"] == ["not_a_profile"]

    async def test_five_user_suppression(self, client: AsyncClient, db_session: AsyncSession):
        # Seven distinct users overall, but healthcare only has two.
        await _seed_cohort(
            db_session, count=5, plan="pro", industry="tech_saas", before=50.0, after=70.0
        )
        await _seed_cohort(
            db_session, count=2, plan="free", industry="healthcare", before=60.0, after=50.0
        )
        headers = await _admin_headers(db_session)

        payload = (
            await client.get(
                "/admin/analytics/ats-score-distribution?days=30",
                headers=headers,
            )
        ).json()
        assert payload["totals"]["runs"] == 7
        assert payload["suppression"]["by_dimension"]["industry"] == 1
        visible = {row["industry"] for row in payload["by_industry"]}
        assert visible == {"tech_saas"}

        only_small = (
            await client.get(
                "/admin/analytics/ats-score-distribution?days=30&industry=healthcare",
                headers=headers,
            )
        ).json()
        assert only_small["suppressed"] is True
        assert only_small["totals"]["runs"] == 0
        assert only_small["distribution"] == []
        assert only_small["by_industry"] == []

    async def test_privacy_no_content_or_identities(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        users = await _seed_cohort(
            db_session, count=5, plan="pro", industry="tech_saas", before=50.0, after=70.0
        )
        secret_email = f"secret_identity_2091_{uuid.uuid4().hex}@example.com"
        admin_id, admin_headers = await _create_user(
            db_session, role="admin", email=secret_email
        )
        response = await client.get(
            "/admin/analytics/ats-score-distribution?days=30",
            headers=admin_headers,
        )
        assert response.status_code == 200, response.text
        body = response.text
        assert SECRET_RESUME not in body
        assert SECRET_JD not in body
        assert SECRET_CHANGES not in body
        assert secret_email not in body
        for user_id in users:
            assert user_id not in body
        assert admin_id not in body
        assert "user_id" not in body
        assert "resume_id" not in body
        assert response.json()["privacy"]["per_user_rows"] is False

    async def test_record_optimization_persists_baseline_and_dimensions(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id, headers = await _create_user(db_session, plan="pro")
        resume_id = await _create_resume(db_session, user_id=user_id)

        response = await client.post(
            f"/resumes/{resume_id}/record-optimization",
            headers=headers,
            json={
                "original_latex": SECRET_RESUME,
                "optimized_latex": SECRET_RESUME + " optimized",
                "job_description": SECRET_JD,
                "ats_score": 82.0,
                "ats_score_before": 41.5,
                "industry": "tech_saas",
                "profile": "startup",
                "changes_made": [{"section": "summary", "reason": SECRET_CHANGES}],
            },
        )
        assert response.status_code == 201, response.text

        row = (
            await db_session.execute(
                text(
                    "SELECT ats_score, ats_score_before, ats_score_after, industry, profile "
                    "FROM optimizations WHERE id = :id"
                ),
                {"id": response.json()["id"]},
            )
        ).mappings().one()
        assert row["ats_score"] == 82.0
        assert row["ats_score_before"] == 41.5
        assert row["ats_score_after"] == 82.0
        assert row["industry"] == "tech_saas"
        assert row["profile"] == "startup"

    async def test_record_optimization_derives_missing_baseline(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ):
        from app.api import resume_routes

        async def _fake_score(**_kwargs):
            return SimpleNamespace(overall_score=33.0, industry_key="finance_banking")

        monkeypatch.setattr(resume_routes.ats_scoring_service, "score_resume", _fake_score)
        user_id, headers = await _create_user(db_session, plan="pro")
        resume_id = await _create_resume(db_session, user_id=user_id)

        response = await client.post(
            f"/resumes/{resume_id}/record-optimization",
            headers=headers,
            json={
                "original_latex": SECRET_RESUME,
                "optimized_latex": SECRET_RESUME + " optimized",
                "job_description": SECRET_JD,
                "ats_score_after": 73.0,
            },
        )
        assert response.status_code == 201, response.text
        row = (
            await db_session.execute(
                text(
                    "SELECT ats_score_before, ats_score_after, industry "
                    "FROM optimizations WHERE id = :id"
                ),
                {"id": response.json()["id"]},
            )
        ).mappings().one()
        assert row["ats_score_before"] == 33.0
        assert row["ats_score_after"] == 73.0
        assert row["industry"] == "finance_banking"
