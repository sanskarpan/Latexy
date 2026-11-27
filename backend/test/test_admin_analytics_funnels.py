"""Admin activation, retention, and filtered-timeseries contract tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

NOW = datetime.now(timezone.utc)


async def _create_user(
    db: AsyncSession,
    *,
    role: str = "user",
    plan: str = "pro",
    created_at: datetime | None = None,
    provider: str | None = None,
) -> str:
    user_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used, created_at) "
            "VALUES (:id, :email, 'Analytics User', :role, true, :plan, 'active', false, :created)"
        ),
        {
            "id": user_id,
            "email": f"analytics_{user_id.replace('-', '')}@example.com",
            "role": role,
            "plan": plan,
            "created": created_at or NOW,
        },
    )
    if provider:
        await db.execute(
            text(
                'INSERT INTO account (id, "userId", "accountId", "providerId") '
                "VALUES (:id, :uid, :account, :provider)"
            ),
            {
                "id": str(uuid.uuid4()),
                "uid": user_id,
                "account": f"account_{uuid.uuid4().hex}",
                "provider": provider,
            },
        )
    return user_id


async def _admin_headers(db: AsyncSession) -> dict[str, str]:
    user_id = await _create_user(db, role="admin")
    token = f"analytics_sess_{uuid.uuid4().hex}"
    await db.execute(
        text(
            'INSERT INTO session (id, "userId", "expiresAt", token) '
            "VALUES (:id, :uid, :exp, :tok)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "exp": NOW + timedelta(days=1),
            "tok": token,
        },
    )
    await db.commit()
    return {"Authorization": f"Bearer {token}"}


async def _insert_resume(db: AsyncSession, user_id: str, created_at: datetime) -> str:
    resume_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO resumes (id, user_id, title, latex_content, created_at, updated_at) "
            "VALUES (:id, :uid, 'Analytics Resume', 'latex', :created, :created)"
        ),
        {"id": resume_id, "uid": user_id, "created": created_at},
    )
    return resume_id


async def _insert_compilation(
    db: AsyncSession,
    user_id: str,
    resume_id: str,
    created_at: datetime,
    *,
    status: str = "completed",
) -> None:
    await db.execute(
        text(
            "INSERT INTO compilations (id, user_id, resume_id, job_id, status, created_at) "
            "VALUES (:id, :uid, :resume, :job, :status, :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "resume": resume_id,
            "job": f"analytics_{uuid.uuid4().hex}",
            "status": status,
            "created": created_at,
        },
    )


async def _insert_optimization(
    db: AsyncSession,
    user_id: str,
    resume_id: str,
    created_at: datetime,
) -> None:
    await db.execute(
        text(
            "INSERT INTO optimizations (id, user_id, resume_id, job_description, "
            "original_latex, optimized_latex, provider, model, tokens_used, created_at) "
            "VALUES (:id, :uid, :resume, 'jd', 'a', 'b', 'openai', 'gpt-4o-mini', 10, :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "resume": resume_id,
            "created": created_at,
        },
    )


async def _insert_activity(
    db: AsyncSession,
    user_id: str,
    created_at: datetime,
    *,
    action: str = "page_view",
) -> None:
    await db.execute(
        text(
            "INSERT INTO usage_analytics (id, user_id, action, resource_type, created_at) "
            "VALUES (:id, :uid, :action, 'page', :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "action": action,
            "created": created_at,
        },
    )


async def _insert_payment(db: AsyncSession, user_id: str, created_at: datetime) -> None:
    await db.execute(
        text(
            "INSERT INTO payments (id, user_id, provider, provider_payment_id, amount, currency, status, created_at) "
            "VALUES (:id, :uid, 'dodo', :provider_id, 59900, 'INR', 'paid', :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "provider_id": f"pay_{uuid.uuid4().hex}",
            "created": created_at,
        },
    )


async def _seed_full_milestones(db: AsyncSession, user_id: str, signup: datetime) -> None:
    resume_id = await _insert_resume(db, user_id, signup + timedelta(hours=1))
    await _insert_compilation(db, user_id, resume_id, signup + timedelta(hours=2))
    await _insert_activity(db, user_id, signup + timedelta(hours=5), action="export")
    await _insert_optimization(db, user_id, resume_id, signup + timedelta(hours=9))
    await _insert_payment(db, user_id, signup + timedelta(hours=14))


class TestActivationFunnel:
    async def test_milestones_are_first_occurrence_and_reconcile(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        headers = await _admin_headers(db_session)
        plan = f"plan_{uuid.uuid4().hex[:10]}"
        signup = NOW - timedelta(days=2)
        user_id = await _create_user(db_session, plan=plan, created_at=signup)
        await _seed_full_milestones(db_session, user_id, signup)

        # Duplicate source rows must not inflate the funnel or move the first event.
        resume_id = await _insert_resume(db_session, user_id, signup + timedelta(hours=6))
        await _insert_resume(db_session, user_id, signup + timedelta(hours=7))
        await _insert_compilation(db_session, user_id, resume_id, signup + timedelta(hours=8))
        await _insert_compilation(
            db_session, user_id, resume_id, signup + timedelta(hours=8, minutes=30), status="failed"
        )
        await _insert_activity(db_session, user_id, signup + timedelta(hours=10), action="export")
        await _insert_optimization(db_session, user_id, resume_id, signup + timedelta(hours=11))
        await _insert_payment(db_session, user_id, signup + timedelta(hours=15))

        response = await client.get(
            f"/admin/analytics/activation?days=30&plan={plan}&activation_window_days=30",
            headers=headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["cohort_size"] == 1
        steps = {step["key"]: step for step in body["steps"]}
        for key in (
            "signup",
            "first_resume",
            "first_compile",
            "first_export",
            "first_optimize",
            "first_paid",
        ):
            assert steps[key]["count"] == 1
        assert steps["first_compile"]["median_seconds_from_previous"] == pytest.approx(3600, abs=1)
        reconciliation = body["reconciliation"]
        for key in ("first_resume", "first_compile", "first_export", "first_optimize", "first_paid"):
            assert reconciliation[key]["users"] == 1
        assert body["by_plan"] == []
        assert body["suppressed_segments"]["plan"] >= 1
        assert "@example.com" not in response.text
        assert "latex" not in response.text

    async def test_median_time_between_steps(self, client: AsyncClient, db_session: AsyncSession):
        headers = await _admin_headers(db_session)
        plan = f"plan_{uuid.uuid4().hex[:10]}"
        signup = NOW - timedelta(days=2)
        user_id = await _create_user(db_session, plan=plan, created_at=signup)
        await _seed_full_milestones(db_session, user_id, signup)

        response = await client.get(
            f"/admin/analytics/activation?days=30&plan={plan}&activation_window_days=30",
            headers=headers,
        )
        assert response.status_code == 200
        steps = {step["key"]: step for step in response.json()["steps"]}
        expected = {
            "first_resume": 3600,
            "first_compile": 3600,
            "first_export": 10800,
            "first_optimize": 14400,
            "first_paid": 18000,
        }
        for key, seconds in expected.items():
            assert steps[key]["median_seconds_from_previous"] == pytest.approx(seconds, abs=1)
            assert steps[key]["median_days_from_previous"] == pytest.approx(seconds / 86_400, abs=0.01)

    async def test_seven_thirty_ninety_day_windows(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        headers = await _admin_headers(db_session)
        plan = f"plan_{uuid.uuid4().hex[:10]}"
        signup = NOW - timedelta(days=20)
        user_id = await _create_user(db_session, plan=plan, created_at=signup)
        resume_id = await _insert_resume(db_session, user_id, signup + timedelta(hours=1))
        await _insert_compilation(db_session, user_id, resume_id, signup + timedelta(days=10))

        response = await client.get(
            f"/admin/analytics/activation?days=30&plan={plan}&activation_window_days=30",
            headers=headers,
        )
        assert response.status_code == 200
        windows = response.json()["windows"]
        assert set(windows) == {"7", "30", "90"}
        assert windows["7"]["steps"][2]["count"] == 0
        assert windows["30"]["steps"][2]["count"] == 1
        assert windows["90"]["steps"][2]["count"] == 1

    async def test_small_segments_are_suppressed(self, client: AsyncClient, db_session: AsyncSession):
        headers = await _admin_headers(db_session)
        small_plan = f"small_{uuid.uuid4().hex[:10]}"
        large_plan = f"large_{uuid.uuid4().hex[:10]}"
        month = (NOW - timedelta(days=2)).strftime("%Y-%m")
        for _ in range(4):
            user_id = await _create_user(db_session, plan=small_plan, created_at=NOW - timedelta(days=2))
            await _insert_resume(db_session, user_id, NOW - timedelta(days=2, hours=1))
        for _ in range(5):
            user_id = await _create_user(db_session, plan=large_plan, created_at=NOW - timedelta(days=2))
            await _insert_resume(db_session, user_id, NOW - timedelta(days=2, hours=1))

        response = await client.get("/admin/analytics/activation?days=30", headers=headers)
        assert response.status_code == 200
        body = response.json()
        labels = {segment["label"] for segment in body["by_plan"]}
        assert large_plan in labels
        assert small_plan not in labels
        assert body["suppressed_segments"]["plan"] >= 1
        assert all(segment["users"] >= 5 for segment in body["by_plan"])
        assert all(segment["users"] >= 5 for segment in body["by_signup_cohort"])

    async def test_empty_activation(self, client: AsyncClient, db_session: AsyncSession):
        headers = await _admin_headers(db_session)
        missing_plan = f"missing_{uuid.uuid4().hex[:10]}"
        response = await client.get(
            f"/admin/analytics/activation?days=30&plan={missing_plan}", headers=headers
        )
        assert response.status_code == 200
        body = response.json()
        assert body["cohort_size"] == 0
        assert all(step["count"] == 0 for step in body["steps"])
        assert all(
            step["count"] == 0
            for window in body["windows"].values()
            for step in window["steps"]
        )
        assert body["by_plan"] == []

    async def test_non_admin_forbidden(self, client: AsyncClient, db_session: AsyncSession):
        user_id = await _create_user(db_session)
        token = f"analytics_sess_{uuid.uuid4().hex}"
        await db_session.execute(
            text(
                'INSERT INTO session (id, "userId", "expiresAt", token) '
                "VALUES (:id, :uid, :exp, :tok)"
            ),
            {
                "id": str(uuid.uuid4()),
                "uid": user_id,
                "exp": NOW + timedelta(days=1),
                "tok": token,
            },
        )
        await db_session.commit()
        response = await client.get(
            "/admin/analytics/activation", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 403


class TestRetentionCohorts:
    async def test_month_selector_and_retention_curves(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        headers = await _admin_headers(db_session)
        anchor = NOW - timedelta(days=350)
        signup = datetime(anchor.year, anchor.month, 5, 12, tzinfo=timezone.utc)
        month = signup.strftime("%Y-%m")
        users = [await _create_user(db_session, created_at=signup) for _ in range(5)]
        await _insert_activity(db_session, users[0], signup + timedelta(days=1))
        await _insert_activity(db_session, users[1], signup + timedelta(days=7))
        await _insert_activity(db_session, users[2], signup + timedelta(days=15))
        await _insert_activity(db_session, users[3], signup + timedelta(days=30))

        response = await client.get(
            f"/admin/analytics/retention?weeks=8&signup_month={month}", headers=headers
        )
        assert response.status_code == 200
        body = response.json()
        assert body["signup_month"] == month
        assert any(item["month"] == month for item in body["available_signup_months"])
        month_row = next(row for row in body["monthly"] if row["signup_month"] == month)
        assert month_row["cohort_size"] == 5
        assert month_row["d1"]["numerator"] == 1
        assert month_row["d1"]["denominator"] == 5
        assert month_row["d1"]["cohort_size"] == 5
        assert month_row["d1"]["rate"] == 20.0
        assert month_row["d7"]["numerator"] == 1
        assert month_row["d30"]["numerator"] == 1
        assert month_row["w1"]["numerator"] == 1
        # W2+ is any activity from day 14 onwards, so it includes day 15 and day 30.
        assert month_row["w2_plus"]["numerator"] == 2
        assert len(month_row["weekly"]) == 8
        assert month_row["weekly"][0]["numerator"] == 1
        assert month_row["weekly"][1]["numerator"] == 1
        # Week 3 has no activity but stays a zero point, not a gap or null.
        assert month_row["weekly"][2]["denominator"] == 5
        assert month_row["weekly"][2]["numerator"] == 0
        assert month_row["weekly"][2]["rate"] == 0.0
        assert month_row["weekly"][3]["numerator"] == 1
        assert len(body["curves"]["weekly"]) == 8
        assert body["overall"]["cohort_size"] == 5
        assert body["overall"]["d1"]["numerator"] == 1

    async def test_cohorts_below_five_are_hidden(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        headers = await _admin_headers(db_session)
        anchor = NOW - timedelta(days=300)
        signup = datetime(anchor.year, anchor.month, 6, 12, tzinfo=timezone.utc)
        month = signup.strftime("%Y-%m")
        for _ in range(4):
            await _create_user(db_session, created_at=signup)

        response = await client.get(
            f"/admin/analytics/retention?weeks=8&signup_month={month}", headers=headers
        )
        assert response.status_code == 200
        body = response.json()
        assert body["monthly"] == []
        assert body["cohorts"] == []
        assert body["hidden_monthly_cohorts"] == 1
        assert body["overall"]["cohort_size"] == 0
        assert body["curves"]["weekly"] == []

    async def test_invalid_signup_month(self, client: AsyncClient, db_session: AsyncSession):
        headers = await _admin_headers(db_session)
        response = await client.get(
            "/admin/analytics/retention?weeks=8&signup_month=2026-13", headers=headers
        )
        assert response.status_code == 422


class TestFilteredTimeseries:
    async def test_plan_dimension_and_gap_fill(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        headers = await _admin_headers(db_session)
        plan = f"plan_{uuid.uuid4().hex[:10]}"
        for _ in range(5):
            user_id = await _create_user(db_session, plan=plan, created_at=NOW)
            await _insert_activity(db_session, user_id, NOW, action="page_view")

        response = await client.get(
            f"/admin/analytics/timeseries?days=5&metric=events&dimension=plan&value={plan}",
            headers=headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] >= 5
        assert len(body["points"]) == 5
        assert body["points"][-1]["value"] >= 5
        assert sum(point["value"] for point in body["points"]) == body["total"]
        assert body["breakdown"][0]["label"] == plan
        assert body["breakdown"][0]["users"] >= 5
        assert body["suppressed"] is False
        assert body["filters"] == {
            "days": 5,
            "metric": "events",
            "dimension": "plan",
            "value": plan,
            "start_date": body["start_date"],
            "end_date": body["end_date"],
            "timezone": "UTC",
        }

    async def test_provider_dimension(self, client: AsyncClient, db_session: AsyncSession):
        headers = await _admin_headers(db_session)
        provider = f"provider_{uuid.uuid4().hex[:8]}"
        for _ in range(5):
            user_id = await _create_user(db_session, provider=provider)
            await _insert_activity(db_session, user_id, NOW, action="page_view")

        response = await client.get(
            f"/admin/analytics/timeseries?days=7&metric=events&dimension=provider&value={provider}",
            headers=headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] >= 5
        assert body["breakdown"][0]["label"] == provider
        assert body["breakdown"][0]["users"] >= 5

    async def test_feature_dimension(self, client: AsyncClient, db_session: AsyncSession):
        headers = await _admin_headers(db_session)
        feature = f"feature_{uuid.uuid4().hex[:8]}"
        for _ in range(5):
            user_id = await _create_user(db_session)
            await _insert_activity(db_session, user_id, NOW, action=feature)

        response = await client.get(
            f"/admin/analytics/timeseries?days=7&metric=events&dimension=feature&value={feature}",
            headers=headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 5
        assert body["breakdown"] == [
            {"label": feature, "value": 5, "users": 5},
        ]

    async def test_signup_cohort_dimension(self, client: AsyncClient, db_session: AsyncSession):
        headers = await _admin_headers(db_session)
        anchor = NOW - timedelta(days=200)
        signup = datetime(anchor.year, anchor.month, 10, 12, tzinfo=timezone.utc)
        month = signup.strftime("%Y-%m")
        for _ in range(5):
            user_id = await _create_user(db_session, created_at=signup)
            await _insert_activity(db_session, user_id, NOW, action="page_view")

        response = await client.get(
            f"/admin/analytics/timeseries?days=365&metric=events&dimension=signup_cohort&value={month}",
            headers=headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] >= 5
        assert body["breakdown"][0]["label"] == month
        assert body["breakdown"][0]["users"] >= 5

    async def test_new_and_active_user_metrics(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        headers = await _admin_headers(db_session)
        plan = f"plan_{uuid.uuid4().hex[:10]}"
        for _ in range(5):
            user_id = await _create_user(db_session, plan=plan, created_at=NOW)
            await _insert_activity(db_session, user_id, NOW, action="page_view")

        new_users = await client.get(
            f"/admin/analytics/timeseries?days=5&metric=new_users&dimension=plan&value={plan}",
            headers=headers,
        )
        assert new_users.status_code == 200
        assert new_users.json()["total"] == 5
        assert new_users.json()["points"][-1]["value"] == 5
        assert new_users.json()["breakdown"][0]["users"] == 5

        active_users = await client.get(
            f"/admin/analytics/timeseries?days=5&metric=active_users&dimension=plan&value={plan}",
            headers=headers,
        )
        assert active_users.status_code == 200
        assert active_users.json()["total"] == 5
        assert active_users.json()["points"][-1]["value"] == 5

    async def test_small_cohorts_are_suppressed(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        headers = await _admin_headers(db_session)
        small_plan = f"small_{uuid.uuid4().hex[:10]}"
        large_plan = f"large_{uuid.uuid4().hex[:10]}"
        for _ in range(4):
            user_id = await _create_user(db_session, plan=small_plan)
            await _insert_activity(db_session, user_id, NOW, action="page_view")
        for _ in range(5):
            user_id = await _create_user(db_session, plan=large_plan)
            await _insert_activity(db_session, user_id, NOW, action="page_view")

        filtered = await client.get(
            f"/admin/analytics/timeseries?days=7&metric=events&dimension=plan&value={small_plan}",
            headers=headers,
        )
        assert filtered.status_code == 200
        assert filtered.json()["suppressed"] is True
        assert filtered.json()["total"] == 0
        assert len(filtered.json()["points"]) == 7

        grouped = await client.get(
            "/admin/analytics/timeseries?days=7&metric=events&dimension=plan", headers=headers
        )
        assert grouped.status_code == 200
        labels = {row["label"] for row in grouped.json()["breakdown"]}
        assert large_plan in labels
        assert small_plan not in labels
        assert grouped.json()["suppressed_groups"] >= 1

    async def test_empty_data(self, client: AsyncClient, db_session: AsyncSession):
        headers = await _admin_headers(db_session)
        missing_plan = f"missing_{uuid.uuid4().hex[:10]}"
        response = await client.get(
            f"/admin/analytics/timeseries?days=3&metric=events&dimension=plan&value={missing_plan}",
            headers=headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 0
        assert body["suppressed"] is False
        assert len(body["points"]) == 3
        assert all(point["value"] == 0 for point in body["points"])
        assert body["breakdown"] == []

    async def test_invalid_parameters(self, client: AsyncClient, db_session: AsyncSession):
        headers = await _admin_headers(db_session)
        cases = [
            "/admin/analytics/timeseries?days=0",
            "/admin/analytics/timeseries?days=366",
            "/admin/analytics/timeseries?metric=unknown",
            "/admin/analytics/timeseries?dimension=unknown",
            "/admin/analytics/timeseries?metric=compilations&dimension=feature",
            "/admin/analytics/timeseries?dimension=signup_cohort&value=2026-13",
        ]
        for path in cases:
            response = await client.get(path, headers=headers)
            assert response.status_code == 422, path

    async def test_non_admin_forbidden(self, client: AsyncClient, db_session: AsyncSession):
        user_id = await _create_user(db_session)
        token = f"analytics_sess_{uuid.uuid4().hex}"
        await db_session.execute(
            text(
                'INSERT INTO session (id, "userId", "expiresAt", token) '
                "VALUES (:id, :uid, :exp, :tok)"
            ),
            {
                "id": str(uuid.uuid4()),
                "uid": user_id,
                "exp": NOW + timedelta(days=1),
                "tok": token,
            },
        )
        await db_session.commit()
        response = await client.get(
            "/admin/analytics/timeseries", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 403
