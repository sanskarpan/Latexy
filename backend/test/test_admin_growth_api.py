"""Activation, retention, AI-cost, and dimension-filtered analytics tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def _create_user(
    db: AsyncSession,
    *,
    role: str = "user",
    plan: str = "pro",
    created_at: datetime | None = None,
) -> tuple[str, str]:
    user_id = str(uuid.uuid4())
    email = f"growth_{user_id.replace('-', '')}@example.com"
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used, created_at) "
            "VALUES (:id, :email, 'Growth User', :role, true, :plan, 'active', false, :created)"
        ),
        {
            "id": user_id,
            "email": email,
            "role": role,
            "plan": plan,
            "created": created_at or datetime.now(timezone.utc),
        },
    )
    await db.commit()
    return user_id, email


async def _session_headers(db: AsyncSession, user_id: str) -> dict[str, str]:
    token = f"growth_sess_{uuid.uuid4().hex}"
    await db.execute(
        text(
            'INSERT INTO session (id, "userId", "expiresAt", token) '
            "VALUES (:id, :uid, :exp, :tok)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "exp": datetime.now(timezone.utc) + timedelta(days=1),
            "tok": token,
        },
    )
    await db.commit()
    return {"Authorization": f"Bearer {token}"}


async def _admin_headers(db: AsyncSession) -> dict[str, str]:
    user_id, _ = await _create_user(db, role="admin")
    return await _session_headers(db, user_id)


async def _seed_milestones(db: AsyncSession, user_id: str, *, created_at: datetime) -> None:
    resume_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO resumes (id, user_id, title, latex_content, created_at) "
            "VALUES (:id, :uid, 'Growth Resume', 'latex', :created)"
        ),
        {"id": resume_id, "uid": user_id, "created": created_at + timedelta(hours=1)},
    )
    await db.execute(
        text(
            "INSERT INTO compilations (id, user_id, resume_id, job_id, status, created_at) "
            "VALUES (:id, :uid, :resume, :job, 'completed', :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "resume": resume_id,
            "job": f"growth_{uuid.uuid4().hex}",
            "created": created_at + timedelta(hours=2),
        },
    )
    await db.execute(
        text(
            "INSERT INTO optimizations (id, user_id, resume_id, job_description, "
            "original_latex, optimized_latex, provider, model, tokens_used, created_at) "
            "VALUES (:id, :uid, :resume, 'jd', 'a', 'b', 'openai', 'gpt-4o-mini', 1000000, :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "resume": resume_id,
            "created": created_at + timedelta(hours=3),
        },
    )
    await db.execute(
        text(
            "INSERT INTO usage_analytics (id, user_id, action, resource_type, created_at) "
            "VALUES (:id, :uid, 'export', 'resume', :created)"
        ),
        {"id": str(uuid.uuid4()), "uid": user_id, "created": created_at + timedelta(hours=4)},
    )
    await db.execute(
        text(
            "INSERT INTO payments (id, user_id, provider, provider_payment_id, amount, currency, status, created_at) "
            "VALUES (:id, :uid, 'dodo', :provider_id, 59900, 'INR', 'paid', :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "provider_id": f"pay_{uuid.uuid4().hex}",
            "created": created_at + timedelta(hours=5),
        },
    )
    await db.commit()


class TestActivation:
    async def test_funnel_and_segments(self, client: AsyncClient, db_session: AsyncSession):
        headers = await _admin_headers(db_session)
        created = datetime.now(timezone.utc) - timedelta(days=2)
        first_id, _ = await _create_user(db_session, plan="pro", created_at=created)
        second_id, _ = await _create_user(db_session, plan="free", created_at=created)
        await _seed_milestones(db_session, first_id, created_at=created)

        response = await client.get("/admin/analytics/activation?days=30", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["cohort_size"] >= 2
        steps = {step["key"]: step for step in body["steps"]}
        assert steps["signup"]["count"] >= 2
        assert steps["first_resume"]["count"] >= 1
        assert steps["first_compile"]["count"] >= 1
        assert steps["first_export"]["count"] >= 1
        assert steps["first_optimize"]["count"] >= 1
        assert steps["first_paid"]["count"] >= 1
        assert body["by_plan"]
        assert any(segment["label"] == "pro" for segment in body["by_plan"])

        filtered = await client.get("/admin/analytics/activation?days=30&plan=pro", headers=headers)
        assert filtered.status_code == 200
        assert filtered.json()["cohort_size"] >= 1
        assert all(segment["label"] == "pro" for segment in filtered.json()["by_plan"])

    async def test_non_admin_forbidden(self, client: AsyncClient, db_session: AsyncSession):
        user_id, _ = await _create_user(db_session)
        headers = await _session_headers(db_session, user_id)
        response = await client.get("/admin/analytics/activation", headers=headers)
        assert response.status_code == 403


class TestRetention:
    async def test_d1_and_d7_cohorts(self, client: AsyncClient, db_session: AsyncSession):
        headers = await _admin_headers(db_session)
        signup = datetime.now(timezone.utc) - timedelta(days=14)
        user_id, _ = await _create_user(db_session, created_at=signup)
        for offset in (1, 7):
            await db_session.execute(
                text(
                    "INSERT INTO usage_analytics (id, user_id, action, resource_type, created_at) "
                    "VALUES (:id, :uid, 'page_view', 'page', :created)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "uid": user_id,
                    "created": signup + timedelta(days=offset),
                },
            )
        await db_session.commit()

        response = await client.get("/admin/analytics/retention?weeks=8", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["overall"]["cohort_size"] >= 1
        matching = [row for row in body["cohorts"] if row["cohort_size"] >= 1]
        assert matching
        assert any(row["d1"]["count"] >= 1 for row in matching)
        assert any(row["d7"]["count"] >= 1 for row in matching)


class TestAiCost:
    async def test_cost_margin_and_alerts(self, client: AsyncClient, db_session: AsyncSession):
        headers = await _admin_headers(db_session)
        created = datetime.now(timezone.utc) - timedelta(days=1)
        user_id, _ = await _create_user(db_session, plan="pro", created_at=created)
        await _seed_milestones(db_session, user_id, created_at=created)

        response = await client.get("/admin/analytics/ai-cost?days=30", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["estimated"] is True
        assert body["total_tokens"] >= 1_000_000
        assert body["total_cost_usd"] > 0
        assert body["by_model"]
        assert body["top_users"]
        assert any(row["plan"] == "pro" for row in body["margin_by_plan"])
        assert any(row["user_id"] == user_id for row in body["top_users"])


class TestDimensionTimeseries:
    async def test_plan_and_feature_filters(self, client: AsyncClient, db_session: AsyncSession):
        headers = await _admin_headers(db_session)
        user_id, _ = await _create_user(db_session, plan="pro")
        await db_session.execute(
            text(
                "INSERT INTO usage_analytics (id, user_id, action, resource_type) "
                "VALUES (:id, :uid, 'export', 'resume')"
            ),
            {"id": str(uuid.uuid4()), "uid": user_id},
        )
        await db_session.commit()

        plan_filtered = await client.get(
            "/admin/analytics/timeseries?days=30&metric=events&dimension=plan&value=pro",
            headers=headers,
        )
        assert plan_filtered.status_code == 200
        assert plan_filtered.json()["total"] >= 1

        feature_filtered = await client.get(
            "/admin/analytics/timeseries?days=30&metric=events&dimension=feature&value=export",
            headers=headers,
        )
        assert feature_filtered.status_code == 200
        assert feature_filtered.json()["total"] >= 1
        assert any(row["label"] == "export" for row in feature_filtered.json()["breakdown"])

        revenue = await client.get(
            "/admin/analytics/timeseries?days=30&metric=revenue", headers=headers
        )
        assert revenue.status_code == 200
        assert revenue.json()["metric"] == "revenue"
