"""Privacy-safe device/browser/OS/country breakdowns (issue #2069).

Covers the bounded parser, country-header validation, aggregate and conversion
reporting, five-user suppression, unknown bucketing, admin-only access, empty
data, date ranges, and the no-raw-IP/no-user-agent output boundary.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.database.models import UsageAnalytics
from app.services.client_environment import (
    BROWSER_FAMILIES,
    DEVICE_CLASSES,
    OS_FAMILIES,
    classify_browser_family,
    classify_device_class,
    classify_os_family,
    country_from_metadata,
    country_from_request,
    normalize_country_code,
    parse_user_agent,
    with_server_country,
)

ENDPOINT = "/admin/analytics/privacy-breakdowns"
RANGE = {"start_date": "2019-02-01", "end_date": "2019-02-07"}

IPHONE_SAFARI = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
IPAD_SAFARI = (
    "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
ANDROID_CHROME_MOBILE = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
)
ANDROID_CHROME_TABLET = (
    "Mozilla/5.0 (Linux; Android 14; SM-X710) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
WINDOWS_CHROME = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
WINDOWS_EDGE = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0"
)
MAC_SAFARI = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)
LINUX_FIREFOX = "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0"
CHROMEOS = (
    "Mozilla/5.0 (X11; CrOS x86_64 14541.0.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
IE11 = "Mozilla/5.0 (Windows NT 6.1; Trident/7.0; rv:11.0) like Gecko"
SAMSUNG = (
    "Mozilla/5.0 (Linux; Android 13; SAMSUNG SM-G991B) AppleWebKit/537.36 "
    "(KHTML, like Gecko) SamsungBrowser/23.0 Chrome/115.0.0.0 Mobile Safari/537.36"
)
OPERA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 OPR/109.0.0.0"
)


class TestParserBuckets:
    @pytest.mark.parametrize(
        ("user_agent", "device", "browser", "os_family"),
        [
            (IPHONE_SAFARI, "mobile", "safari", "ios"),
            (IPAD_SAFARI, "tablet", "safari", "ios"),
            (ANDROID_CHROME_MOBILE, "mobile", "chrome", "android"),
            (ANDROID_CHROME_TABLET, "tablet", "chrome", "android"),
            (WINDOWS_CHROME, "desktop", "chrome", "windows"),
            (WINDOWS_EDGE, "desktop", "edge", "windows"),
            (MAC_SAFARI, "desktop", "safari", "macos"),
            (LINUX_FIREFOX, "desktop", "firefox", "linux"),
            (CHROMEOS, "desktop", "chrome", "chromeos"),
            (IE11, "desktop", "internet_explorer", "windows"),
            (SAMSUNG, "mobile", "samsung_internet", "android"),
            (OPERA, "desktop", "opera", "windows"),
        ],
    )
    def test_known_user_agents_map_to_bounded_labels(
        self, user_agent: str, device: str, browser: str, os_family: str
    ) -> None:
        assert classify_device_class(user_agent) == device
        assert classify_browser_family(user_agent) == browser
        assert classify_os_family(user_agent) == os_family
        assert device in DEVICE_CLASSES
        assert browser in BROWSER_FAMILIES
        assert os_family in OS_FAMILIES

    @pytest.mark.parametrize("user_agent", [None, "", "   "])
    def test_missing_user_agent_is_unknown(self, user_agent: str | None) -> None:
        assert parse_user_agent(user_agent) == {
            "device_class": "unknown",
            "browser_family": "unknown",
            "os_family": "unknown",
        }

    def test_unrecognized_user_agent_is_bounded_other(self) -> None:
        parsed = parse_user_agent("TotallyCustomClient/9.9 on SomeCustomOS")

        assert parsed == {
            "device_class": "desktop",
            "browser_family": "other",
            "os_family": "other",
        }
        assert "TotallyCustomClient" not in json.dumps(parsed)


class TestCountryValidation:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("in", "IN"),
            (" US ", "US"),
            ("gb", "GB"),
            ("De", "DE"),
        ],
    )
    def test_valid_iso_codes_are_normalized(self, raw: str, expected: str) -> None:
        assert normalize_country_code(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [None, "", "   ", "USA", "1A", "XX", "T1", "ZZ", "I N", "<script>", 123, ["IN"]],
    )
    def test_invalid_country_values_are_rejected(self, raw: object) -> None:
        assert normalize_country_code(raw) is None

    def test_untrusted_header_is_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        request = SimpleNamespace(headers={"CF-IPCountry": "IN"})
        monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", False)

        assert country_from_request(request) is None
        assert with_server_country({"screen": "desktop"}, request) == {"screen": "desktop"}

    def test_trusted_header_is_validated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        request = SimpleNamespace(headers={"CF-IPCountry": "in"})
        monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)

        assert country_from_request(request) == "IN"
        assert with_server_country({"screen": "desktop"}, request) == {
            "screen": "desktop",
            "country": "IN",
        }

    def test_client_supplied_country_is_replaced_or_removed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
        spoofed = {"country": "ZZ", "country_code": "ZZ", "screen": "desktop"}

        assert with_server_country(spoofed, SimpleNamespace(headers={"CF-IPCountry": "gb"})) == {
            "screen": "desktop",
            "country": "GB",
        }
        assert with_server_country(spoofed, SimpleNamespace(headers={"CF-IPCountry": "XX"})) == {"screen": "desktop"}

    def test_metadata_reader_accepts_only_captured_country(self) -> None:
        assert country_from_metadata({"country": "in"}) == "IN"
        assert country_from_metadata({"country": "XX"}) is None
        assert country_from_metadata({"city": "Mumbai"}) is None
        assert country_from_metadata(None) is None


class PrivacySeed:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.user_ids: list[str] = []
        self.tokens: list[str] = []
        self.fingerprints: set[str] = set()

    async def user(
        self,
        *,
        role: str = "user",
        created_at: datetime | None = None,
    ) -> str:
        user_id = str(uuid.uuid4())
        await self.db.execute(
            text(
                "INSERT INTO users (id, email, name, role, email_verified, "
                "subscription_plan, subscription_status, trial_used, created_at) "
                "VALUES (:id, :email, 'Privacy Test User', :role, true, "
                "'free', 'active', false, :created)"
            ),
            {
                "id": user_id,
                "email": f"test_privacy_{user_id.replace('-', '')}@example.com",
                "role": role,
                "created": created_at or datetime.now(timezone.utc),
            },
        )
        self.user_ids.append(user_id)
        await self.db.commit()
        return user_id

    async def session_headers(self, user_id: str) -> dict[str, str]:
        token = f"test_privacy_sess_{uuid.uuid4().hex}"
        self.tokens.append(token)
        await self.db.execute(
            text('INSERT INTO session (id, "userId", "expiresAt", token) VALUES (:id, :uid, :exp, :tok)'),
            {
                "id": str(uuid.uuid4()),
                "uid": user_id,
                "exp": datetime.now(timezone.utc) + timedelta(days=1),
                "tok": token,
            },
        )
        await self.db.commit()
        return {"Authorization": f"Bearer {token}"}

    async def admin_headers(self) -> dict[str, str]:
        admin_id = await self.user(role="admin")
        return await self.session_headers(admin_id)

    async def pageview(
        self,
        fingerprint: str,
        *,
        user_id: str | None = None,
        user_agent: str = WINDOWS_CHROME,
        country: str | None = "US",
        city: str | None = None,
        ip_address: str = "203.0.113.77",
        created_at: datetime | None = None,
    ) -> None:
        self.fingerprints.add(fingerprint)
        metadata: dict[str, object] = {"page": "landing"}
        if country is not None:
            metadata["country"] = country
        if city is not None:
            metadata["city"] = city
        await self.db.execute(
            text(
                "INSERT INTO usage_analytics "
                "(id, user_id, device_fingerprint, action, resource_type, event_metadata, "
                "ip_address, user_agent, created_at) "
                "VALUES (:id, :uid, :fp, 'page_view', 'page', CAST(:metadata AS JSONB), "
                "CAST(:ip AS inet), :ua, :created)"
            ),
            {
                "id": str(uuid.uuid4()),
                "uid": user_id,
                "fp": fingerprint,
                "metadata": json.dumps(metadata),
                "ip": ip_address,
                "ua": user_agent,
                "created": created_at or datetime(2019, 2, 3, 12, tzinfo=timezone.utc),
            },
        )
        await self.db.commit()

    async def cleanup(self) -> None:
        await self.db.execute(text("DELETE FROM usage_analytics WHERE action LIKE 'privacy_test_%'"))
        await self.db.execute(text("DELETE FROM usage_analytics WHERE device_fingerprint LIKE 'test_privacy_%'"))
        if self.user_ids:
            await self.db.execute(
                text("DELETE FROM usage_analytics WHERE user_id = ANY(CAST(:ids AS uuid[]))"),
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
        await self.db.commit()


@pytest.fixture
async def privacy_seed(db_session: AsyncSession):
    seed = PrivacySeed(db_session)
    yield seed
    await seed.cleanup()


async def _seed_cohorts(seed: PrivacySeed, db: AsyncSession) -> None:
    """Five mobile/IN signups plus two desktop signups and five unknown signups."""

    created = datetime(2019, 2, 3, 12, tzinfo=timezone.utc)
    for index in range(5):
        user_id = await seed.user(created_at=created)
        await seed.pageview(
            f"test_privacy_mobile_{index}",
            user_id=user_id,
            user_agent=IPHONE_SAFARI,
            country="IN",
            city="Mumbai",
            ip_address="203.0.113.77",
            created_at=created,
        )

    for index in range(2):
        user_id = await seed.user(created_at=created)
        await seed.pageview(
            f"test_privacy_desktop_{index}",
            user_id=user_id,
            user_agent=WINDOWS_CHROME,
            country="US",
            created_at=created,
        )

    # Five page views from one session: the visible page-view count is high but
    # the session cohort is one, so the row must stay suppressed.
    for index in range(5):
        await seed.pageview(
            "test_privacy_single_session",
            user_agent=LINUX_FIREFOX,
            country="GB",
            created_at=created + timedelta(minutes=index),
        )

    # Signups without any stored event still count, in the unknown bucket.
    for _ in range(5):
        await seed.user(created_at=created)

    await db.commit()


async def _report(client: AsyncClient, headers: dict[str, str], params: dict[str, object] | None = None) -> dict:
    response = await client.get(ENDPOINT, params=params or RANGE, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


class TestAdminBreakdownReport:
    async def test_breakdowns_suppress_small_cohorts_and_bucket_unknown(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        privacy_seed: PrivacySeed,
    ) -> None:
        await _seed_cohorts(privacy_seed, db_session)
        body = await _report(client, await privacy_seed.admin_headers())

        device_rows = {row["value"]: row for row in body["dimensions"]["device"]["rows"]}
        assert set(device_rows) == {"mobile", "unknown"}
        assert device_rows["mobile"]["page_views"] == 5
        assert device_rows["mobile"]["sessions"] == 5
        assert device_rows["mobile"]["signups"] == 5
        assert device_rows["mobile"]["signup_conversion"] == 100.0
        assert device_rows["unknown"]["page_views"] == 0
        assert device_rows["unknown"]["signups"] == 5
        assert body["dimensions"]["device"]["suppressed_rows"] >= 1

        country_rows = {row["value"]: row for row in body["dimensions"]["country"]["rows"]}
        assert country_rows["IN"]["sessions"] == 5
        assert country_rows["IN"]["signups"] == 5
        assert "GB" not in country_rows  # 5 page views from one session
        assert country_rows["unknown"]["signups"] == 5

        # No visible cell may contain a 1-4 cohort count.
        for dimension in body["dimensions"].values():
            for row in dimension["rows"]:
                for key in ("signups", "sessions"):
                    value = row[key]
                    assert value is None or value == 0 or value >= 5

        assert body["summary"]["page_views"] == 12
        assert body["summary"]["sessions"] == 8
        assert body["summary"]["signups"] == 12
        assert body["summary"]["signup_conversion"] == 100.0
        assert body["minimum_cohort_size"] == 5
        assert body["suppressed_rows"] >= 2

    async def test_small_signup_cell_is_hidden_even_when_sessions_are_large(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        privacy_seed: PrivacySeed,
    ) -> None:
        created = datetime(2019, 2, 3, 12, tzinfo=timezone.utc)
        for index in range(5):
            user_id = await privacy_seed.user(created_at=created)
            await privacy_seed.pageview(
                f"test_privacy_mobile_{index}",
                user_id=user_id if index < 2 else None,
                user_agent=IPHONE_SAFARI,
                country="IN",
                created_at=created,
            )

        body = await _report(client, await privacy_seed.admin_headers())
        mobile = next(row for row in body["dimensions"]["device"]["rows"] if row["value"] == "mobile")

        assert mobile["sessions"] == 5
        assert mobile["signups"] is None
        assert "signups" in mobile["suppressed_cells"]
        assert mobile["signup_conversion"] is None

    async def test_no_raw_ip_user_agent_or_city_is_returned(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        privacy_seed: PrivacySeed,
    ) -> None:
        created = datetime(2019, 2, 3, 12, tzinfo=timezone.utc)
        for index in range(5):
            await privacy_seed.pageview(
                f"test_privacy_leak_{index}",
                user_agent=f"{IPHONE_SAFARI} PrivacyLeakMarker/1.0",
                country="IN",
                city="Mumbai",
                ip_address="198.51.100.42",
                created_at=created,
            )

        response = await client.get(ENDPOINT, params=RANGE, headers=await privacy_seed.admin_headers())
        assert response.status_code == 200, response.text
        serialized = response.text

        assert "198.51.100.42" not in serialized
        assert "PrivacyLeakMarker" not in serialized
        assert "Mozilla/5.0" not in serialized
        assert "Mumbai" not in serialized
        assert "ip_address" not in serialized
        assert "user_agent" not in serialized
        assert "city" not in serialized

    async def test_empty_range_returns_empty_breakdowns(
        self,
        client: AsyncClient,
        privacy_seed: PrivacySeed,
    ) -> None:
        body = await _report(
            client,
            await privacy_seed.admin_headers(),
            {"start_date": "2016-01-01", "end_date": "2016-01-02"},
        )

        assert body["summary"]["page_views"] == 0
        assert body["summary"]["sessions"] == 0
        assert body["summary"]["signups"] == 0
        assert body["summary"]["signup_conversion"] is None
        assert body["suppressed_rows"] == 0
        for dimension in body["dimensions"].values():
            assert dimension["rows"] == []
            assert dimension["suppressed_rows"] == 0

    async def test_non_admin_is_forbidden(self, client: AsyncClient, privacy_seed: PrivacySeed) -> None:
        user_id = await privacy_seed.user()
        headers = await privacy_seed.session_headers(user_id)

        response = await client.get(ENDPOINT, params=RANGE, headers=headers)

        assert response.status_code == 403, response.text

    async def test_invalid_date_range_is_rejected(self, client: AsyncClient, privacy_seed: PrivacySeed) -> None:
        response = await client.get(
            ENDPOINT,
            params={"start_date": "2019-02-08", "end_date": "2019-02-01"},
            headers=await privacy_seed.admin_headers(),
        )

        assert response.status_code == 422, response.text


class TestCountryCapture:
    async def test_track_event_persists_validated_edge_country(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        privacy_seed: PrivacySeed,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
        response = await client.post(
            "/analytics/track",
            json={
                "event_type": "privacy_test_country_capture",
                "metadata": {"country": "ZZ", "screen": "desktop"},
            },
            headers={"CF-IPCountry": "in", "User-Agent": IPHONE_SAFARI},
        )

        assert response.status_code == 201, response.text
        row = (
            (
                await db_session.execute(
                    select(UsageAnalytics).where(UsageAnalytics.action == "privacy_test_country_capture")
                )
            )
            .scalars()
            .one()
        )
        assert row.event_metadata == {"screen": "desktop", "country": "IN"}

    async def test_page_view_captures_country_and_bounded_device(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        privacy_seed: PrivacySeed,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
        fingerprint = f"test_privacy_capture_{uuid.uuid4().hex}"
        privacy_seed.fingerprints.add(fingerprint)

        response = await client.post(
            "/analytics/track/page-view",
            params={"page": "landing", "device_fingerprint": fingerprint},
            headers={"CF-IPCountry": "de", "User-Agent": IPHONE_SAFARI},
        )

        assert response.status_code == 201, response.text
        row = (
            (await db_session.execute(select(UsageAnalytics).where(UsageAnalytics.device_fingerprint == fingerprint)))
            .scalars()
            .one()
        )
        assert row.event_metadata["country"] == "DE"
        assert row.event_metadata["device_class"] == "mobile"

    async def test_invalid_edge_country_is_not_stored(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        privacy_seed: PrivacySeed,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
        response = await client.post(
            "/analytics/track",
            json={"event_type": "privacy_test_invalid_country"},
            headers={"CF-IPCountry": "XX"},
        )

        assert response.status_code == 201, response.text
        row = (
            (
                await db_session.execute(
                    select(UsageAnalytics).where(UsageAnalytics.action == "privacy_test_invalid_country")
                )
            )
            .scalars()
            .one()
        )
        assert "country" not in (row.event_metadata or {})
