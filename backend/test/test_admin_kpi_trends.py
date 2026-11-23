"""Prior-period deltas and sparklines for the admin KPI header."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.analytics_routes import reset_admin_overview_cache
from app.services.analytics_service import analytics_service

KPI_KEYS = {
    "total_users",
    "active_subscriptions",
    "total_revenue_inr",
    "total_compilations",
    "total_optimizations",
    "trial_users",
}


async def _create_user(
    db: AsyncSession,
    *,
    role: str = "user",
    created_at: datetime | None = None,
) -> tuple[str, str]:
    user_id = str(uuid.uuid4())
    email = f"trend_{user_id.replace('-', '')}@example.com"
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used, created_at) "
            "VALUES (:id, :email, :name, :role, true, 'free', 'active', false, :created)"
        ),
        {
            "id": user_id,
            "email": email,
            "name": "Trend User",
            "role": role,
            "created": created_at or datetime.now(timezone.utc),
        },
    )
    await db.commit()
    return user_id, email


async def _session_headers(db: AsyncSession, user_id: str) -> dict[str, str]:
    token = f"trend_sess_{uuid.uuid4().hex}"
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


async def _headers(db: AsyncSession) -> dict[str, str]:
    user_id, _ = await _create_user(db, role="admin")
    return await _session_headers(db, user_id)


def _trend(body: dict[str, Any], key: str) -> dict[str, Any]:
    return next(item for item in body["kpi_trends"] if item["key"] == key)


async def test_kpi_trends_require_admin(client: AsyncClient):
    reset_admin_overview_cache()
    response = await client.get("/analytics/admin/overview?days=7")
    assert response.status_code == 401


async def test_kpi_trends_are_complete_finite_and_cached(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    headers = await _headers(db_session)
    now = datetime.now(timezone.utc)
    reset_admin_overview_cache()

    baseline_response = await client.get("/analytics/admin/overview?days=7", headers=headers)
    assert baseline_response.status_code == 200
    baseline = baseline_response.json()
    assert set(item["key"] for item in baseline["kpi_trends"]) == KPI_KEYS
    baseline_map = {item["key"]: item for item in baseline["kpi_trends"]}

    # Seed current and previous windows. The endpoint is intentionally compared
    # against the pre-seed baseline so the shared test database cannot make the
    # assertions order-dependent.
    previous_point = now - timedelta(days=9)
    for _ in range(3):
        await _create_user(db_session, created_at=now - timedelta(hours=1))
    await _create_user(db_session, created_at=previous_point)

    for created_at in (now - timedelta(hours=2), now - timedelta(hours=1)):
        await db_session.execute(
            text(
                "INSERT INTO compilations (id, job_id, status, created_at) "
                "VALUES (:id, :job_id, 'completed', :created)"
            ),
            {"id": str(uuid.uuid4()), "job_id": f"job_{uuid.uuid4().hex}", "created": created_at},
        )
    await db_session.execute(
        text(
            "INSERT INTO compilations (id, job_id, status, created_at) "
            "VALUES (:id, :job_id, 'failed', :created)"
        ),
        {"id": str(uuid.uuid4()), "job_id": f"job_{uuid.uuid4().hex}", "created": previous_point},
    )

    await db_session.execute(
        text(
            "INSERT INTO device_trials "
            "(id, device_fingerprint, usage_count, blocked, last_used, created_at) "
            "VALUES (:id, :fingerprint, 0, false, :created, :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "fingerprint": f"trend_{uuid.uuid4().hex}",
            "created": now - timedelta(hours=1),
        },
    )
    for offset in (0, 1):
        await db_session.execute(
            text(
                "INSERT INTO device_trials "
                "(id, device_fingerprint, usage_count, blocked, last_used, created_at) "
                "VALUES (:id, :fingerprint, 0, false, :created, :created)"
            ),
            {
                "id": str(uuid.uuid4()),
                "fingerprint": f"trend_{uuid.uuid4().hex}_{offset}",
                "created": previous_point,
            },
        )

    payer_id, _ = await _create_user(db_session, created_at=previous_point)
    for amount, created_at in ((10_000, now - timedelta(hours=1)), (5_000, previous_point)):
        await db_session.execute(
            text(
                "INSERT INTO payments (id, user_id, provider, provider_payment_id, "
                "amount, currency, status, created_at) "
                "VALUES (:id, :uid, 'dodo', :provider_payment, :amount, 'INR', 'paid', :created)"
            ),
            {
                "id": str(uuid.uuid4()),
                "uid": payer_id,
                "provider_payment": f"pay_{uuid.uuid4().hex[:12]}",
                "amount": amount,
                "created": created_at,
            },
        )

    await db_session.execute(
        text(
            "INSERT INTO subscriptions (id, user_id, provider, provider_subscription_id, "
            "plan_id, status, current_period_start, current_period_end, created_at) "
            "VALUES (:id, :uid, 'dodo', :provider_sub, 'pro', 'active', :start, :end, :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": payer_id,
            "provider_sub": f"sub_{uuid.uuid4().hex[:12]}",
            "start": previous_point,
            "end": now + timedelta(days=20),
            "created": previous_point,
        },
    )
    await db_session.commit()

    reset_admin_overview_cache()
    response = await client.get("/analytics/admin/overview?days=7", headers=headers)
    assert response.status_code == 200
    body = response.json()
    trends = {item["key"]: item for item in body["kpi_trends"]}

    assert set(trends) == KPI_KEYS
    for item in trends.values():
        assert item["current"] >= 0
        assert item["previous"] >= 0
        assert item["absolute_delta"] == pytest.approx(item["current"] - item["previous"], abs=0.01)
        assert item["baseline_zero"] is (item["previous"] == 0)
        if item["previous"] == 0:
            assert item["percent_delta"] is None
        else:
            assert item["percent_delta"] is not None
        assert item["sparkline"]
        assert all("date" in point and "value" in point for point in item["sparkline"])

    for key in ("total_compilations", "total_optimizations", "trial_users", "total_revenue_inr"):
        trend = trends[key]
        assert sum(point["value"] for point in trend["sparkline"]) == pytest.approx(
            trend["current"], abs=0.01
        )

    users = _trend(body, "total_users")
    # Total users is a snapshot: all five seeded users increase it, while only
    # the two users created before the period start increase the prior value.
    assert users["current"] == baseline_map["total_users"]["current"] + 5
    assert users["previous"] == baseline_map["total_users"]["previous"] + 2

    compilations = _trend(body, "total_compilations")
    assert compilations["current"] == baseline_map["total_compilations"]["current"] + 2
    assert compilations["previous"] == baseline_map["total_compilations"]["previous"] + 1

    trials = _trend(body, "trial_users")
    assert trials["current"] == baseline_map["trial_users"]["current"] + 1
    assert trials["previous"] == baseline_map["trial_users"]["previous"] + 2

    revenue = _trend(body, "total_revenue_inr")
    assert revenue["current"] == pytest.approx(baseline_map["total_revenue_inr"]["current"] + 100.0)
    assert revenue["previous"] == pytest.approx(baseline_map["total_revenue_inr"]["previous"] + 50.0)
    assert revenue["unit"] == "currency"

    text_body = json.dumps(body)
    assert "NaN" not in text_body and "Infinity" not in text_body

    # The second request must be served from the 60s cache.
    calls = 0
    original = analytics_service.get_system_analytics

    async def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return await original(*args, **kwargs)

    monkeypatch.setattr(analytics_service, "get_system_analytics", counted)
    cached_response = await client.get("/analytics/admin/overview?days=7", headers=headers)
    assert cached_response.status_code == 200
    assert cached_response.json()["generated_at"] == body["generated_at"]
    assert calls == 0
