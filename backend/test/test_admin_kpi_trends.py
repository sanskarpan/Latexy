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

from app.api import analytics_routes
from app.api.analytics_routes import reset_admin_overview_cache
from app.services.analytics_service import analytics_service

KPI_KEYS = {
    "total_users",
    "active_subscriptions",
    "total_revenue_inr",
    "total_compilations",
    "total_optimizations",
    "trial_users",
    "conversion_rate",
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


async def _create_trial(db: AsyncSession, *, created_at: datetime) -> None:
    await db.execute(
        text(
            "INSERT INTO device_trials "
            "(id, device_fingerprint, usage_count, blocked, last_used, created_at) "
            "VALUES (:id, :fingerprint, 0, false, :created, :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "fingerprint": f"trend_{uuid.uuid4().hex}",
            "created": created_at,
        },
    )
    await db.commit()


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
        sparkline_sum = sum(point["value"] for point in trend["sparkline"])
        assert sparkline_sum == pytest.approx(trend["current"], abs=0.01), (
            f"{key}: sparkline sum {sparkline_sum} != current {trend['current']}"
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


async def test_conversion_rate_kpi_is_percent_and_consistent(
    client: AsyncClient, db_session: AsyncSession
):
    """The new conversion KPI is a percent and its deltas are internally consistent."""
    headers = await _headers(db_session)
    reset_admin_overview_cache()
    response = await client.get("/analytics/admin/overview?days=7", headers=headers)
    assert response.status_code == 200
    body = response.json()

    trend = _trend(body, "conversion_rate")
    assert trend["unit"] == "percent"
    # The KPI value mirrors system.conversion_rate exactly.
    assert trend["current"] == pytest.approx(body["system"]["conversion_rate"], abs=0.01)
    assert 0 <= trend["current"] <= 100
    assert trend["previous"] >= 0
    assert trend["absolute_delta"] == pytest.approx(
        trend["current"] - trend["previous"], abs=0.01
    )
    assert trend["baseline_zero"] is (trend["previous"] == 0)
    # An empty prior window never divides by zero.
    assert (trend["percent_delta"] is None) is (trend["previous"] == 0)
    assert all("date" in point and "value" in point for point in trend["sparkline"])
    assert all(0 <= point["value"] <= 100 for point in trend["sparkline"])
    serialized = json.dumps(trend)
    assert "NaN" not in serialized and "Infinity" not in serialized


async def test_conversion_rate_prior_window_matches_utc_counts(
    client: AsyncClient, db_session: AsyncSession
):
    """The prior conversion rate is new users / trials over the prior UTC window."""
    headers = await _headers(db_session)
    now = datetime.now(timezone.utc)
    previous_point = now - timedelta(days=9)
    current_point = now - timedelta(hours=1)

    # Prior window: two users over four trials. Current window: three users
    # over two trials, which clamps to 100%.
    for _ in range(2):
        await _create_user(db_session, created_at=previous_point)
    for _ in range(4):
        await _create_trial(db_session, created_at=previous_point)
    for _ in range(3):
        await _create_user(db_session, created_at=current_point)
    for _ in range(2):
        await _create_trial(db_session, created_at=current_point)

    reset_admin_overview_cache()
    response = await client.get("/analytics/admin/overview?days=7", headers=headers)
    assert response.status_code == 200
    body = response.json()
    trend = _trend(body, "conversion_rate")

    start = datetime.now(timezone.utc) - timedelta(days=7)
    previous_start = start - timedelta(days=7)
    previous_users = (
        await db_session.execute(
            text("SELECT count(*) FROM users WHERE created_at >= :start AND created_at < :end"),
            {"start": previous_start, "end": start},
        )
    ).scalar_one()
    previous_trials = (
        await db_session.execute(
            text(
                "SELECT count(*) FROM device_trials "
                "WHERE created_at >= :start AND created_at < :end"
            ),
            {"start": previous_start, "end": start},
        )
    ).scalar_one()
    expected_previous = (
        min(previous_users / previous_trials * 100, 100.0) if previous_trials else 0.0
    )

    assert expected_previous > 0
    assert trend["previous"] == pytest.approx(expected_previous, abs=0.01)
    assert trend["current"] == pytest.approx(body["system"]["conversion_rate"], abs=0.01)
    assert trend["absolute_delta"] == pytest.approx(
        trend["current"] - trend["previous"], abs=0.01
    )
    assert all(0 <= point["value"] <= 100 for point in trend["sparkline"])


async def test_prior_window_boundary_is_utc_exclusive(
    client: AsyncClient, db_session: AsyncSession
):
    """Records on either side of the UTC window boundary land in the right window."""
    headers = await _headers(db_session)
    now = datetime.now(timezone.utc)
    days = 7
    start = now - timedelta(days=days)

    reset_admin_overview_cache()
    baseline = await client.get("/analytics/admin/overview?days=7", headers=headers)
    base_trend = _trend(baseline.json(), "total_compilations")

    # One compile an hour before the window start (prior window) and one an hour
    # after it (current window). Prior is [start-days, start), current is
    # [start, now).
    for created_at in (start - timedelta(hours=1), start + timedelta(hours=1)):
        await db_session.execute(
            text(
                "INSERT INTO compilations (id, job_id, status, created_at) "
                "VALUES (:id, :job_id, 'completed', :created)"
            ),
            {"id": str(uuid.uuid4()), "job_id": f"job_{uuid.uuid4().hex}", "created": created_at},
        )
    await db_session.commit()

    reset_admin_overview_cache()
    response = await client.get("/analytics/admin/overview?days=7", headers=headers)
    assert response.status_code == 200
    trend = _trend(response.json(), "total_compilations")
    assert trend["previous"] == base_trend["previous"] + 1
    assert trend["current"] == base_trend["current"] + 1


async def test_overview_served_from_redis_cache(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """A warm Redis entry short-circuits the database on the second request."""
    headers = await _headers(db_session)
    reset_admin_overview_cache()

    first = await client.get("/analytics/admin/overview?days=7", headers=headers)
    assert first.status_code == 200
    payload = first.json()

    async def fake_get(key: str):
        if key == "analytics:admin_overview:7":
            return payload
        return None

    monkeypatch.setattr(analytics_routes.cache_manager, "get", fake_get)

    async def _boom(*args, **kwargs):
        raise AssertionError("service must not run on a Redis cache hit")

    monkeypatch.setattr(analytics_service, "get_system_analytics", _boom)

    reset_admin_overview_cache()
    second = await client.get("/analytics/admin/overview?days=7", headers=headers)
    assert second.status_code == 200
    assert second.json()["generated_at"] == payload["generated_at"]


async def test_overview_redis_miss_stores_payload(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """A Redis miss computes from the DB and stores the composed response for 60s."""
    headers = await _headers(db_session)
    reset_admin_overview_cache()
    stored: list[tuple[str, int | None]] = []

    async def fake_get(key: str):
        return None

    async def fake_set(key: str, value: Any, ttl: int | None = None):
        stored.append((key, ttl))

    monkeypatch.setattr(analytics_routes.cache_manager, "get", fake_get)
    monkeypatch.setattr(analytics_routes.cache_manager, "set", fake_set)

    response = await client.get("/analytics/admin/overview?days=7", headers=headers)
    assert response.status_code == 200
    assert ("analytics:admin_overview:7", 60) in stored


async def test_overview_redis_outage_falls_through(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """A Redis outage must not fail the overview — it falls through to the DB."""
    headers = await _headers(db_session)
    reset_admin_overview_cache()

    async def failing_get(key: str):
        raise RuntimeError("redis unavailable")

    async def failing_set(key: str, value: Any, ttl: int | None = None):
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(analytics_routes.cache_manager, "get", failing_get)
    monkeypatch.setattr(analytics_routes.cache_manager, "set", failing_set)

    response = await client.get("/analytics/admin/overview?days=7", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert set(item["key"] for item in body["kpi_trends"]) == KPI_KEYS
