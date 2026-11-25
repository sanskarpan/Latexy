"""Traffic-source capture, attribution, and admin aggregation regressions."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import models
from app.services.traffic_source_service import (
    MIN_COHORT_SIZE,
    normalize_utm_values,
    sanitize_landing_path,
    sanitize_referrer_host,
)


@pytest.fixture(autouse=True)
async def _clean_traffic_rows(db_session: AsyncSession):
    """Keep these tests independent of reruns and other modules."""

    await db_session.execute(
        text(
            "DELETE FROM usage_analytics "
            "WHERE action IN ('traffic_landing', 'traffic_signup')"
        )
    )
    await db_session.commit()
    yield
    await db_session.execute(
        text(
            "DELETE FROM usage_analytics "
            "WHERE action IN ('traffic_landing', 'traffic_signup')"
        )
    )
    await db_session.commit()


async def _create_user(
    db: AsyncSession,
    *,
    role: str = "user",
    created_at: datetime | None = None,
) -> str:
    user_id = str(uuid.uuid4())
    db.add(
        models.User(
            id=user_id,
            email=f"test_traffic_{user_id.replace('-', '')}@example.com",
            name="Traffic Test User",
            role=role,
            email_verified=True,
            subscription_plan="pro" if role == "admin" else "free",
            subscription_status="active",
            trial_used=False,
            created_at=created_at or datetime.now(timezone.utc),
        )
    )
    await db.commit()
    return user_id


async def _session_headers(db: AsyncSession, user_id: str) -> dict[str, str]:
    token = f"test_sess_traffic_{uuid.uuid4().hex}"
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
    user_id = await _create_user(db, role="admin")
    return await _session_headers(db, user_id)


async def _seed_landing(
    db: AsyncSession,
    *,
    visitor: str,
    session: str,
    source: str | None,
    campaign: str | None = None,
    referrer: str | None = None,
    created_at: datetime | None = None,
    path: str = "/",
) -> None:
    metadata: dict[str, object] = {
        "visitor_id": visitor,
        "session_id": session,
        "landing_path": path,
    }
    if source:
        metadata["utm_source"] = source
    if campaign:
        metadata["utm_campaign"] = campaign
    if referrer:
        metadata["referrer_host"] = referrer
    db.add(
        models.UsageAnalytics(
            action="traffic_landing",
            resource_type="traffic_source",
            event_metadata=metadata,
            ip_address=None,
            user_agent=None,
            created_at=created_at or datetime.now(timezone.utc),
        )
    )


async def _seed_signup(
    db: AsyncSession,
    *,
    user_id: str,
    source: str | None,
    campaign: str | None = None,
    referrer: str | None = None,
    created_at: datetime | None = None,
) -> None:
    metadata: dict[str, object] = {"landing_path": "/"}
    if source:
        metadata["utm_source"] = source
    if campaign:
        metadata["utm_campaign"] = campaign
    if referrer:
        metadata["referrer_host"] = referrer
    db.add(
        models.UsageAnalytics(
            user_id=user_id,
            action="traffic_signup",
            resource_type="traffic_source",
            event_metadata=metadata,
            ip_address=None,
            user_agent=None,
            created_at=created_at or datetime.now(timezone.utc),
        )
    )


async def _seed_paid(db: AsyncSession, user_id: str) -> None:
    db.add(
        models.Payment(
            user_id=user_id,
            provider="dodo",
            provider_payment_id=f"test_pay_{uuid.uuid4().hex}",
            amount=59900,
            currency="INR",
            status="paid",
        )
    )


class TestSanitizers:
    def test_utm_allowlist_lowercases_and_rejects_free_form(self):
        assert normalize_utm_values({"utm_source": "Google", "utm_term": "resume-builder"}) == {
            "utm_source": "google",
            "utm_term": "resume-builder",
        }
        assert normalize_utm_values({"utm_medium": "", "utm_source": None}) == {}
        for invalid in (
            {"utm_source": "free form"},
            {"utm_source": "person@example.com"},
            {"utm_campaign": "https://evil.example"},
            {"utm_content": "a" * 65},
        ):
            with pytest.raises(ValueError):
                normalize_utm_values(invalid)

    def test_landing_path_drops_query_and_redacts_opaque_segments(self):
        assert sanitize_landing_path("/r/abc123?token=secret#frag") == "/r/:token"
        assert sanitize_landing_path("/pricing?utm_source=google") == "/pricing"
        assert sanitize_landing_path("/u/sanskar") == "/u/:username"
        with pytest.raises(ValueError):
            sanitize_landing_path("https://evil.example/r/secret?token=x")
        with pytest.raises(ValueError):
            sanitize_landing_path("not-a-path")

    def test_referrer_stores_only_external_host_and_drops_ip(self):
        assert (
            sanitize_referrer_host("https://news.ycombinator.com/item?id=1&token=secret")
            == "news.ycombinator.com"
        )
        assert sanitize_referrer_host("https://www.google.com/search?q=resume") == "www.google.com"
        assert sanitize_referrer_host("https://127.0.0.1/private") is None
        assert sanitize_referrer_host("https://[2001:db8::1]/private") is None
        with pytest.raises(ValueError):
            sanitize_referrer_host("javascript:alert(1)")


class TestCaptureValidation:
    async def test_allowlisted_utm_persists_without_ip_or_full_url(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        before = (
            await db_session.execute(
                select(func.count(models.UsageAnalytics.id)).where(
                    models.UsageAnalytics.action == "traffic_landing"
                )
            )
        ).scalar_one()

        response = await client.post(
            "/analytics/traffic/landing",
            json={
                "landing_path": "/r/abc123?token=secret#frag",
                "referrer": "https://news.ycombinator.com/item?id=123&token=secret",
                "session_id": str(uuid.uuid4()),
                "utm_source": "Google",
                "utm_medium": "CPC",
                "utm_campaign": "launch-2026",
                "utm_content": "hero",
                "utm_term": "resume-builder",
            },
        )

        assert response.status_code == 202, response.text
        assert response.json() == {"recorded": True}
        assert "latexy_traffic_visitor" in response.cookies

        after = (
            await db_session.execute(
                select(func.count(models.UsageAnalytics.id)).where(
                    models.UsageAnalytics.action == "traffic_landing"
                )
            )
        ).scalar_one()
        assert after == before + 1

        row = (
            await db_session.execute(
                select(models.UsageAnalytics)
                .where(models.UsageAnalytics.action == "traffic_landing")
                .order_by(models.UsageAnalytics.created_at.desc())
                .limit(1)
            )
        ).scalar_one()
        metadata = row.event_metadata or {}
        assert metadata["utm_source"] == "google"
        assert metadata["utm_medium"] == "cpc"
        assert metadata["utm_campaign"] == "launch-2026"
        assert metadata["utm_content"] == "hero"
        assert metadata["utm_term"] == "resume-builder"
        assert metadata["landing_path"] == "/r/:token"
        assert metadata["referrer_host"] == "news.ycombinator.com"
        assert set(metadata) == {
            "visitor_id",
            "session_id",
            "landing_path",
            "referrer_host",
            "utm_source",
            "utm_medium",
            "utm_campaign",
            "utm_content",
            "utm_term",
        }
        assert row.ip_address is None
        assert row.user_agent is None
        assert row.user_id is None
        serialized = json.dumps(metadata).lower()
        assert "secret" not in serialized
        assert "?" not in serialized
        assert "person@" not in serialized

    @pytest.mark.parametrize(
        "payload",
        [
            {"utm_source": "free form"},
            {"utm_source": "a" * 65},
            {"utm_campaign": "person@example.com"},
            {"utm_content": "https://evil.example"},
            {"email": "person@example.com"},
            {"landing_path": "https://evil.example/r/secret?token=x"},
            {"landing_path": "not-a-path"},
            {"session_id": "not-a-uuid"},
        ],
    )
    async def test_free_form_and_oversized_values_are_rejected(
        self, client: AsyncClient, db_session: AsyncSession, payload: dict
    ):
        before = (
            await db_session.execute(
                select(func.count(models.UsageAnalytics.id)).where(
                    models.UsageAnalytics.action == "traffic_landing"
                )
            )
        ).scalar_one()
        response = await client.post("/analytics/traffic/landing", json=payload)
        assert response.status_code == 422, response.text
        after = (
            await db_session.execute(
                select(func.count(models.UsageAnalytics.id)).where(
                    models.UsageAnalytics.action == "traffic_landing"
                )
            )
        ).scalar_one()
        assert after == before


class TestSignupAttribution:
    async def test_claim_copies_server_stored_landing_and_is_idempotent(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id = await _create_user(db_session)
        headers = await _session_headers(db_session, user_id)

        landing = await client.post(
            "/analytics/traffic/landing",
            json={
                "landing_path": "/pricing",
                "referrer": "https://www.google.com/search?q=latexy",
                "utm_source": "google",
                "utm_medium": "cpc",
                "utm_campaign": "brand",
            },
        )
        assert landing.status_code == 202

        first = await client.post("/analytics/traffic/claim", headers=headers)
        assert first.status_code == 202
        assert first.json()["recorded"] is True

        second = await client.post("/analytics/traffic/claim", headers=headers)
        assert second.status_code == 202
        assert second.json()["reason"] == "already_attributed"

        rows = (
            await db_session.execute(
                select(models.UsageAnalytics).where(
                    models.UsageAnalytics.action == "traffic_signup",
                    models.UsageAnalytics.user_id == user_id,
                )
            )
        ).scalars().all()
        assert len(rows) == 1
        metadata = rows[0].event_metadata or {}
        assert metadata["utm_source"] == "google"
        assert metadata["utm_medium"] == "cpc"
        assert metadata["utm_campaign"] == "brand"
        assert metadata["referrer_host"] == "www.google.com"
        assert rows[0].ip_address is None
        assert rows[0].user_agent is None

    async def test_claim_without_a_landing_records_nothing(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id = await _create_user(db_session)
        headers = await _session_headers(db_session, user_id)
        response = await client.post("/analytics/traffic/claim", headers=headers)
        assert response.status_code == 202
        assert response.json()["recorded"] is False
        count = (
            await db_session.execute(
                select(func.count(models.UsageAnalytics.id)).where(
                    models.UsageAnalytics.action == "traffic_signup",
                    models.UsageAnalytics.user_id == user_id,
                )
            )
        ).scalar_one()
        assert count == 0

    async def test_claim_requires_authentication(self, client: AsyncClient):
        response = await client.post("/analytics/traffic/claim")
        assert response.status_code == 401


class TestAggregation:
    async def test_sources_campaigns_referrers_and_paid_conversion(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        headers = await _admin_headers(db_session)
        now = datetime.now(timezone.utc)
        user_ids: list[str] = []
        for index in range(MIN_COHORT_SIZE):
            user_id = await _create_user(db_session, created_at=now - timedelta(days=1))
            user_ids.append(user_id)
            await _seed_landing(
                db_session,
                visitor=str(uuid.uuid4()),
                session=str(uuid.uuid4()),
                source="google",
                campaign="launch",
                referrer="www.google.com",
                created_at=now - timedelta(days=1),
            )
            await _seed_signup(
                db_session,
                user_id=user_id,
                source="google",
                campaign="launch",
                referrer="www.google.com",
                created_at=now - timedelta(days=1),
            )
            await _seed_paid(db_session, user_id)

        await db_session.commit()

        response = await client.get(
            "/admin/analytics/traffic-sources?days=30", headers=headers
        )
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["minimum_cohort_size"] == MIN_COHORT_SIZE
        assert body["period"]["days"] == 30
        assert body["totals"]["sessions"] >= MIN_COHORT_SIZE
        assert body["totals"]["visitors"] >= MIN_COHORT_SIZE
        assert body["totals"]["signups"] >= MIN_COHORT_SIZE
        assert body["totals"]["paid_users"] >= MIN_COHORT_SIZE

        source = next(row for row in body["by_source"] if row["label"] == "google")
        assert source["sessions"] >= MIN_COHORT_SIZE
        assert source["visitors"] >= MIN_COHORT_SIZE
        assert source["signups"] >= MIN_COHORT_SIZE
        assert source["paid_users"] >= MIN_COHORT_SIZE
        assert source["signup_conversion"] == 100.0
        assert source["paid_conversion"] == 100.0

        campaign = next(row for row in body["by_campaign"] if row["label"] == "launch")
        assert campaign["signups"] >= MIN_COHORT_SIZE
        referrer = next(row for row in body["by_referrer"] if row["label"] == "www.google.com")
        assert referrer["paid_users"] >= MIN_COHORT_SIZE
        medium = next(row for row in body["by_medium"] if row["label"] == "not set")
        assert medium["visitors"] >= MIN_COHORT_SIZE

        serialized = json.dumps(body).lower()
        assert "test_traffic_" not in serialized
        assert "@example.com" not in serialized
        assert "ip_address" not in serialized
        assert "user_agent" not in serialized

    async def test_small_rows_and_cells_are_suppressed(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        headers = await _admin_headers(db_session)
        now = datetime.now(timezone.utc)

        # A visible source cohort (>= 5 visitors) with only 2 signups: the row
        # stays visible but the signup cell is suppressed.
        for _ in range(MIN_COHORT_SIZE):
            await _seed_landing(
                db_session,
                visitor=str(uuid.uuid4()),
                session=str(uuid.uuid4()),
                source="visible",
                created_at=now - timedelta(days=1),
            )
        for _ in range(2):
            user_id = await _create_user(db_session, created_at=now - timedelta(days=1))
            await _seed_signup(
                db_session,
                user_id=user_id,
                source="visible",
                created_at=now - timedelta(days=1),
            )

        # A source with 4 visitors is below the cohort floor and must disappear
        # entirely rather than reveal a tiny audience.
        for _ in range(MIN_COHORT_SIZE - 1):
            await _seed_landing(
                db_session,
                visitor=str(uuid.uuid4()),
                session=str(uuid.uuid4()),
                source="tiny",
                created_at=now - timedelta(days=1),
            )
        await db_session.commit()

        response = await client.get(
            "/admin/analytics/traffic-sources?days=30", headers=headers
        )
        assert response.status_code == 200, response.text
        body = response.json()

        labels = {row["label"] for row in body["by_source"]}
        assert "visible" in labels
        assert "tiny" not in labels
        assert body["suppressed"]["source"] >= 1
        visible = next(row for row in body["by_source"] if row["label"] == "visible")
        assert visible["signups"] is None
        assert visible["signup_conversion"] is None
        assert "signups" in visible["suppressed_cells"]

    async def test_date_range_filters_landings(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        headers = await _admin_headers(db_session)
        now = datetime.now(timezone.utc)
        for _ in range(MIN_COHORT_SIZE):
            await _seed_landing(
                db_session,
                visitor=str(uuid.uuid4()),
                session=str(uuid.uuid4()),
                source="old",
                created_at=now - timedelta(days=60),
            )
            await _seed_landing(
                db_session,
                visitor=str(uuid.uuid4()),
                session=str(uuid.uuid4()),
                source="recent",
                created_at=now - timedelta(days=2),
            )
        await db_session.commit()

        response = await client.get(
            "/admin/analytics/traffic-sources?days=7", headers=headers
        )
        assert response.status_code == 200, response.text
        labels = {row["label"] for row in response.json()["by_source"]}
        assert "recent" in labels
        assert "old" not in labels

        explicit = await client.get(
            f"/admin/analytics/traffic-sources?start_date={(now - timedelta(days=90)).date().isoformat()}"
            f"&end_date={now.date().isoformat()}",
            headers=headers,
        )
        assert explicit.status_code == 200, explicit.text
        explicit_labels = {row["label"] for row in explicit.json()["by_source"]}
        assert {"recent", "old"}.issubset(explicit_labels)

        invalid = await client.get(
            f"/admin/analytics/traffic-sources?start_date={now.date().isoformat()}"
            f"&end_date={(now - timedelta(days=1)).date().isoformat()}",
            headers=headers,
        )
        assert invalid.status_code == 422

    async def test_non_admin_is_forbidden(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id = await _create_user(db_session)
        headers = await _session_headers(db_session, user_id)
        response = await client.get("/admin/analytics/traffic-sources", headers=headers)
        assert response.status_code == 403

    async def test_unauthenticated_admin_route_is_unauthorized(self, client: AsyncClient):
        response = await client.get("/admin/analytics/traffic-sources")
        assert response.status_code == 401
