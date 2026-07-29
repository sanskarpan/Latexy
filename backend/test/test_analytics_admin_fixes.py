"""
Regression tests for the analytics-admin audit fixes.

Covers:
- EventTrackingRequest metadata size/depth validation (storage DoS guard)
- track_* service wrappers propagating the success boolean
- system analytics conversion_rate clamping and period-scoped revenue
- /analytics/track deriving the user from the session (no client-supplied user_id)
- frontend telemetry label bucketing (cardinality guard)
- public feature-flags endpoint allowlist
"""

import uuid
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.analytics_routes import EventTrackingRequest
from app.services.analytics_service import analytics_service


class TestMetadataValidation:
    """EventTrackingRequest.metadata must reject oversized / deeply-nested blobs."""

    def test_small_metadata_ok(self):
        req = EventTrackingRequest(event_type="page_view", metadata={"page": "landing"})
        assert req.metadata == {"page": "landing"}

    def test_none_metadata_ok(self):
        req = EventTrackingRequest(event_type="page_view")
        assert req.metadata is None

    def test_oversized_metadata_rejected(self):
        with pytest.raises(ValueError):
            EventTrackingRequest(event_type="x", metadata={"blob": "a" * 5000})

    def test_deeply_nested_metadata_rejected(self):
        nested = current = {}
        for _ in range(8):
            child = {}
            current["child"] = child
            current = child
        with pytest.raises(ValueError):
            EventTrackingRequest(event_type="x", metadata=nested)


class TestTrackReturnValues:
    """The track_* wrappers must return the underlying success boolean."""

    @pytest.mark.asyncio
    async def test_track_compilation_event_returns_true(self, db_session: AsyncSession):
        result = await analytics_service.track_compilation_event(
            db=db_session,
            user_id=None,
            device_fingerprint=f"fp_{uuid4().hex[:8]}",
            compilation_id=f"comp_{uuid4().hex[:8]}",
            status="completed",
            compilation_time=1.5,
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_track_optimization_event_returns_true(self, db_session: AsyncSession):
        result = await analytics_service.track_optimization_event(
            db=db_session,
            user_id=None,
            optimization_id=f"opt_{uuid4().hex[:8]}",
            provider="openai",
            model="gpt-4",
            tokens_used=100,
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_track_user_journey_event_returns_true(self, db_session: AsyncSession):
        result = await analytics_service.track_user_journey_event(
            db=db_session,
            event_type="page_view",
            device_fingerprint=f"fp_{uuid4().hex[:8]}",
            page="landing",
        )
        assert result is True


class TestSystemAnalyticsMetrics:
    """conversion_rate must be clamped to 100 and revenue scoped to the period."""

    @pytest.mark.asyncio
    async def test_conversion_rate_clamped(self, db_session: AsyncSession):
        analytics = await analytics_service.get_system_analytics(db=db_session, days=7)
        assert 0 <= analytics["conversion_rate"] <= 100
        assert analytics["period_days"] == 7


class TestTrackEndpointAuth:
    """POST /analytics/track must attribute events to the session user, not the body."""

    @pytest.mark.asyncio
    async def test_track_ignores_client_user_id_and_uses_session(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        # Client tries to forge a different user_id — it must be ignored.
        forged = str(uuid4())
        resp = await client.post(
            "/analytics/track",
            headers=auth_headers,
            json={
                "event_type": f"test_evt_{uuid4().hex[:8]}",
                "user_id": forged,
                "metadata": {"page": "landing"},
            },
        )
        assert resp.status_code == 201

        # The forged user_id must not appear as the attributed user.
        row = await db_session.execute(
            text("SELECT COUNT(*) FROM usage_analytics WHERE user_id = :uid"),
            {"uid": forged},
        )
        assert row.scalar() == 0

    @pytest.mark.asyncio
    async def test_track_anonymous_allowed(self, client: AsyncClient):
        resp = await client.post(
            "/analytics/track",
            json={"event_type": f"anon_{uuid4().hex[:8]}", "device_fingerprint": "fp-anon"},
        )
        assert resp.status_code == 201


class TestTelemetryLabelBucketing:
    """Unknown telemetry names/routes must be bucketed to 'other' as metric labels."""

    @pytest.mark.asyncio
    async def test_unknown_name_and_route_bucketed(self, client: AsyncClient):
        evil_name = "EVIL_NAME_XYZ"
        evil_route = "/attacker/unique/path"
        resp = await client.post(
            "/telemetry/frontend",
            json={
                "kind": "business_event",
                "name": evil_name,
                "route": evil_route,
                "metadata": {"k": "v"},
            },
        )
        assert resp.status_code == 202

        body = (await client.get("/metrics")).text
        assert evil_name not in body
        assert evil_route not in body
        assert 'name="other"' in body

    @pytest.mark.asyncio
    async def test_known_web_vital_preserved(self, client: AsyncClient):
        resp = await client.post(
            "/telemetry/frontend",
            json={"kind": "web_vital", "name": "CLS", "route": "/dashboard", "value": 0.05},
        )
        assert resp.status_code == 202
        body = (await client.get("/metrics")).text
        assert 'name="CLS"' in body
        assert 'route="/dashboard"' in body


class TestPublicFeatureFlagsAllowlist:
    """GET /config/feature-flags must only expose allowlisted client-facing flags."""

    @pytest.mark.asyncio
    async def test_internal_flag_not_leaked(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        internal_key = f"internal_{uuid.uuid4().hex[:8]}"
        await db_session.execute(
            text(
                "INSERT INTO feature_flags (key, enabled, label) "
                "VALUES (:k, true, 'Internal Test Flag') ON CONFLICT (key) DO NOTHING"
            ),
            {"k": internal_key},
        )
        await db_session.execute(
            text(
                "INSERT INTO feature_flags (key, enabled, label) "
                "VALUES ('billing', true, 'Billing') ON CONFLICT (key) DO NOTHING"
            ),
        )
        await db_session.commit()

        resp = await client.get("/config/feature-flags")
        assert resp.status_code == 200
        data = resp.json()
        assert internal_key not in data
        # An allowlisted flag is still exposed.
        assert "billing" in data


class TestUserAnalyticsDailyActivity:
    """get_user_analytics must not emit an ungrouped date_trunc expression."""

    async def test_get_user_analytics_returns_daily_activity(self, db_session: AsyncSession):
        # Seed real rows so the GROUP BY date_trunc path actually executes — with
        # zero rows Postgres never evaluates the grouping and the test would pass
        # even if the ungrouped-expression regression came back.
        user_id = uuid4()
        await db_session.execute(
            text(
                "INSERT INTO users (id, email, name, email_verified, subscription_plan, "
                "subscription_status, trial_used) VALUES (:id, :email, 'Analytics User', "
                "true, 'free', 'active', false)"
            ),
            {"id": str(user_id), "email": f"analytics_{user_id.hex}@example.com"},
        )
        for action, day_offset in (("compile", 1), ("compile", 1), ("optimize", 2)):
            await db_session.execute(
                text(
                    "INSERT INTO usage_analytics (id, user_id, action, created_at) "
                    "VALUES (:id, :uid, :action, NOW() - (:offset || ' days')::interval)"
                ),
                {
                    "id": str(uuid4()),
                    "uid": str(user_id),
                    "action": action,
                    "offset": str(day_offset),
                },
            )
        await db_session.commit()

        analytics = await analytics_service.get_user_analytics(
            db=db_session,
            user_id=user_id,
            days=7,
        )
        daily = analytics["daily_activity"]
        assert isinstance(daily, dict)
        # Two distinct days, three events total.
        assert len(daily) == 2
        assert sum(daily.values()) == 3
        assert analytics["most_active_day"] in daily
        assert daily[analytics["most_active_day"]] == 2
        assert analytics["feature_usage"] == {"compile": 2, "optimize": 1}
