"""Landing conversion by page, variant, and device (issue #2064).

Covers per-page/variant visits, same-device trial and registration attribution,
mobile vs desktop comparison, missing-variant labelling, small-cohort
suppression, the page-view ingestion contract, aggregate-only output, and
admin-only access.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

NOW = datetime.now(timezone.utc)


class LandingSeed:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.user_ids: list[str] = []
        self.fingerprints: set[str] = set()

    async def user(
        self,
        *,
        role: str = "user",
        plan: str = "free",
        created_at: datetime | None = None,
        email: str | None = None,
    ) -> str:
        user_id = str(uuid.uuid4())
        await self.db.execute(
            text(
                "INSERT INTO users (id, email, name, role, email_verified, "
                "subscription_plan, subscription_status, trial_used, created_at) "
                "VALUES (:id, :email, 'Landing User', :role, true, :plan, 'active', false, :created)"
            ),
            {
                "id": user_id,
                "email": email or f"test_landing_{user_id.replace('-', '')}@example.com",
                "role": role,
                "plan": plan,
                "created": created_at or NOW,
            },
        )
        self.user_ids.append(user_id)
        return user_id

    async def session_headers(self, user_id: str) -> dict[str, str]:
        token = f"test_sess_landing_{uuid.uuid4().hex}"
        await self.db.execute(
            text('INSERT INTO session (id, "userId", "expiresAt", token) VALUES (:id, :uid, :exp, :tok)'),
            {
                "id": str(uuid.uuid4()),
                "uid": user_id,
                "exp": NOW + timedelta(days=1),
                "tok": token,
            },
        )
        await self.db.commit()
        return {"Authorization": f"Bearer {token}"}

    async def admin_headers(self) -> dict[str, str]:
        admin_id = await self.user(role="admin", plan="pro")
        return await self.session_headers(admin_id)

    async def pageview(
        self,
        *,
        fingerprint: str | None,
        page: str = "landing",
        page_key: str | None = None,
        experiment: str | None = None,
        variant: str | None = None,
        device_class: str | None = "desktop",
        user_id: str | None = None,
        created_at: datetime | None = None,
    ) -> None:
        metadata: dict[str, object] = {"page": page}
        if page_key is not None:
            metadata["page_key"] = page_key
        if experiment is not None:
            metadata["experiment"] = experiment
        if variant is not None:
            metadata["variant"] = variant
        if device_class is not None:
            metadata["device_class"] = device_class
        if fingerprint:
            self.fingerprints.add(fingerprint)
        await self.db.execute(
            text(
                "INSERT INTO usage_analytics "
                "(id, user_id, device_fingerprint, action, resource_type, event_metadata, user_agent, created_at) "
                "VALUES (:id, :uid, :fp, 'page_view', 'page', CAST(:metadata AS JSONB), 'test-agent', :created)"
            ),
            {
                "id": str(uuid.uuid4()),
                "uid": user_id,
                "fp": fingerprint,
                "metadata": json.dumps(metadata),
                "created": created_at or NOW,
            },
        )
        await self.db.commit()

    async def trial(self, fingerprint: str, *, created_at: datetime | None = None) -> None:
        self.fingerprints.add(fingerprint)
        await self.db.execute(
            text(
                "INSERT INTO device_trials (id, device_fingerprint, usage_count, blocked, created_at) "
                "VALUES (:id, :fp, 1, false, :created)"
            ),
            {"id": str(uuid.uuid4()), "fp": fingerprint, "created": created_at or NOW},
        )
        await self.db.commit()

    async def subscription(self, user_id: str, *, created_at: datetime | None = None) -> None:
        await self.db.execute(
            text(
                "INSERT INTO subscriptions "
                "(id, user_id, provider, plan_id, status, created_at) "
                "VALUES (:id, :uid, 'dodo', 'pro', 'active', :created)"
            ),
            {"id": str(uuid.uuid4()), "uid": user_id, "created": created_at or NOW},
        )
        await self.db.commit()

    async def cleanup(self) -> None:
        if self.user_ids:
            await self.db.execute(
                text("DELETE FROM usage_analytics WHERE user_id = ANY(CAST(:ids AS uuid[]))"),
                {"ids": self.user_ids},
            )
            await self.db.execute(
                text("DELETE FROM subscriptions WHERE user_id = ANY(CAST(:ids AS uuid[]))"),
                {"ids": self.user_ids},
            )
            await self.db.execute(
                text('DELETE FROM session WHERE "userId" = ANY(:ids)'),
                {"ids": self.user_ids},
            )
            await self.db.execute(
                text("DELETE FROM users WHERE id = ANY(CAST(:ids AS uuid[]))"),
                {"ids": self.user_ids},
            )
        if self.fingerprints:
            fingerprints = list(self.fingerprints)
            await self.db.execute(
                text("DELETE FROM usage_analytics WHERE device_fingerprint = ANY(:fps)"),
                {"fps": fingerprints},
            )
            await self.db.execute(
                text("DELETE FROM device_trials WHERE device_fingerprint = ANY(:fps)"),
                {"fps": fingerprints},
            )
        await self.db.commit()


@pytest.fixture
async def landing_seed(db_session: AsyncSession):
    seed = LandingSeed(db_session)
    yield seed
    await seed.cleanup()


def _fingerprint() -> str:
    return f"lp_test_{uuid.uuid4().hex}"


def _variant() -> str:
    return f"v_{uuid.uuid4().hex[:10]}"


def _rows(body: dict, collection: str) -> list[dict]:
    return body.get(collection, [])


async def test_landing_conversion_by_page_variant_and_device(client: AsyncClient, landing_seed: LandingSeed):
    headers = await landing_seed.admin_headers()
    base = NOW - timedelta(hours=20)
    mobile_variant = _variant()
    desktop_variant = _variant()

    mobile_fingerprints = [_fingerprint() for _ in range(5)]
    for index, fingerprint in enumerate(mobile_fingerprints):
        await landing_seed.pageview(
            fingerprint=fingerprint,
            page_key="home",
            experiment="hero",
            variant=mobile_variant,
            device_class="mobile",
            created_at=base + timedelta(minutes=index),
        )

    converting_user = await landing_seed.user(created_at=base + timedelta(hours=1))
    await landing_seed.pageview(
        fingerprint=mobile_fingerprints[0],
        page="app",
        page_key=None,
        device_class="mobile",
        user_id=converting_user,
        created_at=base + timedelta(hours=2),
    )
    await landing_seed.trial(mobile_fingerprints[0], created_at=base + timedelta(minutes=30))
    await landing_seed.subscription(converting_user, created_at=base + timedelta(hours=3))

    desktop_fingerprints = [_fingerprint() for _ in range(5)]
    for index, fingerprint in enumerate(desktop_fingerprints):
        landing_seed.fingerprints.add(fingerprint)
        await landing_seed.pageview(
            fingerprint=fingerprint,
            page_key="home",
            experiment="hero",
            variant=desktop_variant,
            device_class="desktop",
            created_at=base + timedelta(minutes=index),
        )
    await landing_seed.trial(desktop_fingerprints[0], created_at=base + timedelta(minutes=45))

    response = await client.get("/admin/analytics/landing-conversion?days=30", headers=headers)
    assert response.status_code == 200
    body = response.json()

    mobile_row = next(
        row
        for row in _rows(body, "by_page_variant_device")
        if row["variant"] == mobile_variant and row["device_class"] == "mobile"
    )
    assert mobile_row["page_key"] == "home"
    assert mobile_row["visits"] == 5
    assert mobile_row["sample_size"] == 5
    assert mobile_row["trial_starts"] == 1
    assert mobile_row["registrations"] == 1
    assert mobile_row["subscriptions"] == 1
    assert mobile_row["conversion_rate"] == pytest.approx(20.0)
    assert mobile_row["missing_variant"] is False

    desktop_row = next(
        row
        for row in _rows(body, "by_page_variant_device")
        if row["variant"] == desktop_variant and row["device_class"] == "desktop"
    )
    assert desktop_row["visits"] == 5
    assert desktop_row["trial_starts"] == 1
    assert desktop_row["registrations"] == 0
    assert desktop_row["conversion_rate"] == 0.0

    device_rows = {row["device_class"]: row for row in _rows(body, "by_device")}
    assert device_rows["mobile"]["visits"] >= 5
    assert device_rows["desktop"]["visits"] >= 5

    summary = body["summary"]
    assert summary["sample_sizes"] == summary["funnel_steps"]
    assert summary["funnel_steps"]["landing_visits"] >= 10
    assert summary["attribution"]["attributed_registrations"] >= 1
    assert summary["attribution"]["model"] == "same_device_first_touch"

    # Aggregate-only: no account id, email, fingerprint, path, or token.
    assert converting_user not in response.text
    assert "@example.com" not in response.text
    assert mobile_fingerprints[0] not in response.text
    assert "/workspace" not in response.text


async def test_missing_variant_is_labelled_not_imputed(client: AsyncClient, landing_seed: LandingSeed):
    headers = await landing_seed.admin_headers()
    for index in range(5):
        await landing_seed.pageview(
            fingerprint=_fingerprint(),
            page_key="templates",
            experiment="template-order",
            variant=None,
            device_class="desktop",
            created_at=NOW - timedelta(hours=3, minutes=index),
        )

    response = await client.get("/admin/analytics/landing-conversion?days=7", headers=headers)
    assert response.status_code == 200
    body = response.json()
    row = next(
        item
        for item in _rows(body, "by_page_variant_device")
        if item["page_key"] == "templates" and item["experiment"] == "template-order"
    )
    assert row["variant"] is None
    assert row["variant_label"] == "Variant not recorded"
    assert row["missing_variant"] is True
    assert body["variant_labels"]["missing"] == "Variant not recorded"
    # A missing variant must not be replaced with a control/hero label.
    assert row["variant_label"] not in {"control", "a", "hero"}


async def test_cells_below_five_visits_are_suppressed(client: AsyncClient, landing_seed: LandingSeed):
    headers = await landing_seed.admin_headers()
    tiny_variant = _variant()
    for index in range(4):
        await landing_seed.pageview(
            fingerprint=_fingerprint(),
            page_key="pricing",
            variant=tiny_variant,
            device_class="desktop",
            created_at=NOW - timedelta(hours=2, minutes=index),
        )

    response = await client.get("/admin/analytics/landing-conversion?days=7", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["suppressed_cells"] >= 1
    assert not any(row["variant"] == tiny_variant for row in _rows(body, "by_page_variant_device"))
    assert not any(row["variant"] == tiny_variant for row in _rows(body, "by_page_variant"))


async def test_page_view_ingest_stores_bounded_landing_context(client: AsyncClient, landing_seed: LandingSeed):
    fingerprint = _fingerprint()
    experiment = "hero-order"
    variant = "variant_b"
    landing_seed.fingerprints.add(fingerprint)

    response = await client.post(
        "/analytics/track/page-view",
        params={
            "page": "landing",
            "page_key": "pricing",
            "experiment": experiment,
            "variant": variant,
            "device_class": "mobile",
            "device_fingerprint": fingerprint,
        },
        headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"},
    )
    assert response.status_code == 201

    row = (
        await landing_seed.db.execute(
            text(
                "SELECT event_metadata, device_fingerprint FROM usage_analytics "
                "WHERE device_fingerprint = :fp AND action = 'page_view'"
            ),
            {"fp": fingerprint},
        )
    ).one()
    metadata = row[0]
    assert metadata["page"] == "landing"
    assert metadata["page_key"] == "pricing"
    assert metadata["experiment"] == experiment
    assert metadata["variant"] == variant
    assert metadata["device_class"] == "mobile"
    assert row[1] == fingerprint
    # No document/path/query field is written by the endpoint.
    assert "path" not in metadata
    assert "url" not in metadata


async def test_page_view_ingest_rejects_free_form_and_derives_device(client: AsyncClient, landing_seed: LandingSeed):
    invalid_page_key = await client.post(
        "/analytics/track/page-view",
        params={"page": "landing", "page_key": "share-token-abc"},
    )
    assert invalid_page_key.status_code == 422

    invalid_variant = await client.post(
        "/analytics/track/page-view",
        params={"page": "landing", "page_key": "home", "variant": "bad value with spaces"},
    )
    assert invalid_variant.status_code == 422

    fingerprint = _fingerprint()
    landing_seed.fingerprints.add(fingerprint)
    response = await client.post(
        "/analytics/track/page-view",
        params={
            "page": "landing",
            "page_key": "home",
            "device_fingerprint": fingerprint,
        },
        headers={"User-Agent": "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X)"},
    )
    assert response.status_code == 201
    metadata = (
        await landing_seed.db.execute(
            text("SELECT event_metadata FROM usage_analytics WHERE device_fingerprint = :fp AND action = 'page_view'"),
            {"fp": fingerprint},
        )
    ).scalar_one()
    assert metadata["device_class"] == "tablet"


async def test_landing_conversion_is_admin_only(client: AsyncClient, landing_seed: LandingSeed):
    unauthenticated = await client.get("/admin/analytics/landing-conversion?days=30")
    assert unauthenticated.status_code == 401

    user_id = await landing_seed.user()
    user_headers = await landing_seed.session_headers(user_id)
    forbidden = await client.get("/admin/analytics/landing-conversion?days=30", headers=user_headers)
    assert forbidden.status_code == 403

    admin_headers = await landing_seed.admin_headers()
    allowed = await client.get("/admin/analytics/landing-conversion?days=30", headers=admin_headers)
    assert allowed.status_code == 200
