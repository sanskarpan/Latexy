"""Consent grant, deny and withdrawal analytics (issue #2138).

Covers first-party capture for all three decisions, idempotent retries, the
no-PII request/storage boundary, aggregate-only admin reporting, five-session
suppression, withdrawal trends, replay coverage, empty data, and admin-only
access.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

ENDPOINT = "/admin/analytics/consent"
CAPTURE = "/analytics/consent"
RANGE = {"start_date": "2019-02-01", "end_date": "2019-02-07"}
NOW = datetime.now(timezone.utc)


def _id(prefix: str = "test-consent") -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


class ConsentSeed:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.user_ids: list[str] = []
        self.markers: set[str] = set()

    async def user(self, *, role: str = "user") -> str:
        user_id = str(uuid.uuid4())
        await self.db.execute(
            text(
                "INSERT INTO users (id, email, name, role, email_verified, "
                "subscription_plan, subscription_status, trial_used, created_at) "
                "VALUES (:id, :email, 'Consent User', :role, true, 'free', 'active', false, :created)"
            ),
            {
                "id": user_id,
                "email": f"test_consent_{user_id.replace('-', '')}@example.com",
                "role": role,
                "created": NOW,
            },
        )
        self.user_ids.append(user_id)
        return user_id

    async def session_headers(self, user_id: str) -> dict[str, str]:
        token = f"test_sess_consent_{uuid.uuid4().hex}"
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
        return await self.session_headers(await self.user(role="admin"))

    async def event(
        self,
        decision: str,
        *,
        surface: str | None = "banner",
        created_at: datetime,
        session_id: str | None = None,
        anonymous_id: str | None = None,
        metadata_extra: dict[str, object] | None = None,
    ) -> str:
        action = {
            "granted": "consent_granted",
            "denied": "consent_denied",
            "withdrawn": "consent_withdrawn",
        }[decision]
        event_id = _id()
        metadata: dict[str, object] = {
            "decision": decision,
            "source": "first_party_consent",
            "event_id": event_id,
        }
        if surface is not None:
            metadata["surface"] = surface
        if session_id:
            metadata["session_id"] = session_id
            self.markers.add(session_id)
        if anonymous_id:
            metadata["anonymous_id"] = anonymous_id
            self.markers.add(anonymous_id)
        if metadata_extra:
            metadata.update(metadata_extra)
        await self.db.execute(
            text(
                "INSERT INTO usage_analytics "
                "(id, user_id, device_fingerprint, action, resource_type, event_metadata, created_at) "
                "VALUES (:id, NULL, NULL, :action, 'consent', CAST(:metadata AS JSONB), :created)"
            ),
            {
                "id": str(uuid.uuid4()),
                "action": action,
                "metadata": json.dumps(metadata),
                "created": created_at,
            },
        )
        await self.db.commit()
        return event_id

    async def cleanup(self) -> None:
        await self.db.execute(
            text(
                "DELETE FROM usage_analytics "
                "WHERE action IN ('consent_granted', 'consent_denied', 'consent_withdrawn') "
                "AND (event_metadata->>'event_id' LIKE 'test-consent-%' "
                "OR event_metadata->>'anonymous_id' LIKE 'test-consent-%' "
                "OR event_metadata->>'session_id' LIKE 'test-consent-%')"
            )
        )
        if self.user_ids:
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
async def consent_seed(db_session: AsyncSession):
    seed = ConsentSeed(db_session)
    yield seed
    await seed.cleanup()


async def _report(
    client: AsyncClient,
    headers: dict[str, str],
    params: dict[str, object] | None = None,
) -> dict:
    response = await client.get(ENDPOINT, params=params or RANGE, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


class TestConsentCapture:
    async def test_records_grant_deny_and_withdraw_without_pii(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        consent_seed: ConsentSeed,
    ) -> None:
        payloads = []
        for decision in ("granted", "denied", "withdrawn"):
            event_id = _id()
            session_id = _id("test-consent-session")
            payloads.append(
                {
                    "decision": decision,
                    "surface": "banner" if decision == "granted" else "privacy_choices",
                    "anonymous_id": _id("test-consent-anon"),
                    "session_id": session_id,
                    "event_id": event_id,
                }
            )
            consent_seed.markers.add(session_id)

        for payload in payloads:
            response = await client.post(CAPTURE, json=payload)
            assert response.status_code == 202, response.text
            body = response.json()
            assert body["accepted"] is True
            assert body["recorded"] is True
            assert body["decision"] == payload["decision"]

        rows = (
            await db_session.execute(
                text(
                    "SELECT action, resource_type, user_id, device_fingerprint, "
                    "ip_address, user_agent, event_metadata "
                    "FROM usage_analytics "
                    "WHERE event_metadata->>'event_id' = ANY(:ids)"
                ),
                {"ids": [payload["event_id"] for payload in payloads]},
            )
        ).all()
        assert len(rows) == 3
        actions = {row.action for row in rows}
        assert actions == {"consent_granted", "consent_denied", "consent_withdrawn"}
        for row in rows:
            assert row.resource_type == "consent"
            assert row.user_id is None
            assert row.device_fingerprint is None
            assert row.ip_address is None
            assert row.user_agent is None
            metadata = row.event_metadata
            assert set(metadata) == {
                "decision",
                "surface",
                "source",
                "anonymous_id",
                "session_id",
                "event_id",
            }
            serialized = json.dumps(metadata).lower()
            assert "@" not in serialized
            assert "email" not in serialized
            assert "document" not in serialized
            assert "latex" not in serialized

    async def test_rejects_unknown_fields_and_invalid_decisions(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            CAPTURE,
            json={
                "decision": "granted",
                "surface": "banner",
                "email": "person@example.com",
            },
        )
        assert response.status_code == 422, response.text

        response = await client.post(
            CAPTURE,
            json={"decision": "maybe", "surface": "banner"},
        )
        assert response.status_code == 422, response.text

    async def test_duplicate_event_id_is_idempotent(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        consent_seed: ConsentSeed,
    ) -> None:
        event_id = _id()
        payload = {
            "decision": "granted",
            "surface": "banner",
            "event_id": event_id,
            "session_id": _id("test-consent-session"),
        }
        consent_seed.markers.add(payload["session_id"])

        first = await client.post(CAPTURE, json=payload)
        second = await client.post(CAPTURE, json=payload)
        assert first.status_code == 202, first.text
        assert second.status_code == 202, second.text
        assert first.json()["recorded"] is True
        assert second.json()["recorded"] is False
        assert second.json()["duplicate"] is True

        count = (
            await db_session.execute(
                text(
                    "SELECT count(*) FROM usage_analytics "
                    "WHERE event_metadata->>'event_id' = :event_id"
                ),
                {"event_id": event_id},
            )
        ).scalar_one()
        assert count == 1


class TestConsentReport:
    async def test_counts_by_day_and_surface_with_withdrawal_and_replay_coverage(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        consent_seed: ConsentSeed,
    ) -> None:
        day_one = datetime(2019, 2, 3, 12, tzinfo=timezone.utc)
        day_two = day_one + timedelta(days=1)
        prior = datetime(2019, 1, 25, 12, tzinfo=timezone.utc)

        for index in range(5):
            await consent_seed.event(
                "granted",
                surface="banner",
                session_id=_id("test-consent-session"),
                created_at=day_one,
            )
            await consent_seed.event(
                "denied",
                surface="privacy_choices",
                session_id=_id("test-consent-session"),
                created_at=day_one,
            )
            # The same session grants and later withdraws: the latest state is
            # withdrawn, so it must not count as replay-eligible.
            session_id = _id("test-consent-session")
            await consent_seed.event(
                "granted",
                surface="settings",
                session_id=session_id,
                created_at=day_two,
            )
            await consent_seed.event(
                "withdrawn",
                surface="settings",
                session_id=session_id,
                created_at=day_two + timedelta(minutes=1),
            )
            await consent_seed.event(
                "withdrawn",
                surface="settings",
                session_id=_id("test-consent-session"),
                created_at=prior,
            )

        body = await _report(client, await consent_seed.admin_headers())

        assert body["summary"]["granted"] == 10
        assert body["summary"]["denied"] == 5
        assert body["summary"]["withdrawn"] == 5
        assert body["summary"]["total"] == 20
        assert body["summary"]["unique_sessions"] == 15

        by_day = {row["date"]: row for row in body["by_day"]}
        assert by_day["2019-02-03"]["granted"] == 5
        assert by_day["2019-02-03"]["denied"] == 5
        assert by_day["2019-02-03"]["total"] == 10
        assert by_day["2019-02-04"]["granted"] == 5
        assert by_day["2019-02-04"]["withdrawn"] == 5
        assert by_day["2019-02-04"]["total"] == 10

        by_surface = {row["surface"]: row for row in body["by_surface"]}
        assert set(by_surface) == {"banner", "privacy_choices", "settings"}
        assert by_surface["banner"]["granted"] == 5
        assert by_surface["privacy_choices"]["denied"] == 5
        assert by_surface["settings"]["granted"] == 5
        assert by_surface["settings"]["withdrawn"] == 5

        assert body["withdrawal_trend"]["current"] == 5
        assert body["withdrawal_trend"]["previous"] == 5
        assert body["withdrawal_trend"]["percent_delta"] == 0.0
        assert body["withdrawal_trend"]["suppressed"] is False

        # Five banner sessions remain granted; the five grant-then-withdraw
        # sessions are no longer replay-eligible.
        assert body["replay_coverage"]["eligible_sessions"] == 5
        assert body["replay_coverage"]["sessions_with_consent"] == 15
        assert body["replay_coverage"]["coverage_pct"] == 33.33
        assert body["minimum_cohort_size"] == 5
        assert body["counts_by_day"] == body["by_day"]
        assert body["counts_by_surface"] == body["by_surface"]

        serialized = json.dumps(body).lower()
        for forbidden in (
            "test-consent-session",
            "test-consent-anon",
            "session_id",
            "anonymous_id",
            "@example.com",
            "user_id",
            "ip_address",
            "user_agent",
        ):
            assert forbidden not in serialized

    async def test_small_cohorts_are_suppressed(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        consent_seed: ConsentSeed,
    ) -> None:
        created = datetime(2019, 2, 3, 12, tzinfo=timezone.utc)
        for _ in range(4):
            await consent_seed.event(
                "granted",
                surface="footer",
                session_id=_id("test-consent-session"),
                created_at=created,
            )

        body = await _report(client, await consent_seed.admin_headers())

        assert body["summary"]["granted"] is None
        assert body["summary"]["total"] is None
        assert "granted" in body["summary"]["suppressed_cells"]
        assert body["summary"]["consent_coverage_pct"] is None

        footer = next(row for row in body["by_surface"] if row["surface"] == "footer")
        assert footer["granted"] is None
        assert footer["total"] is None
        assert "granted" in footer["suppressed_cells"]
        assert "total" in footer["suppressed_cells"]

        day = next(row for row in body["by_day"] if row["date"] == "2019-02-03")
        assert day["granted"] is None
        assert day["total"] is None

        # Zero withdrawals are safe to publish; only 1-4 is a small cohort.
        assert body["withdrawal_trend"]["suppressed"] is False
        assert body["withdrawal_trend"]["current"] == 0
        assert body["replay_coverage"]["suppressed"] is True
        assert body["replay_coverage"]["eligible_sessions"] is None
        assert body["replay_coverage"]["coverage_pct"] is None

    async def test_five_sessions_are_visible_and_totals_are_shown(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        consent_seed: ConsentSeed,
    ) -> None:
        created = datetime(2019, 2, 3, 12, tzinfo=timezone.utc)
        for _ in range(5):
            await consent_seed.event(
                "granted",
                surface="banner",
                session_id=_id("test-consent-session"),
                created_at=created,
            )

        body = await _report(client, await consent_seed.admin_headers())

        assert body["summary"]["granted"] == 5
        assert body["summary"]["total"] == 5
        assert body["summary"]["unique_sessions"] == 5
        assert body["summary"]["suppressed_cells"] == []
        assert body["replay_coverage"]["eligible_sessions"] == 5
        assert body["replay_coverage"]["coverage_pct"] == 100.0

    async def test_withdrawal_trend_hides_small_periods(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        consent_seed: ConsentSeed,
    ) -> None:
        created = datetime(2019, 2, 3, 12, tzinfo=timezone.utc)
        await consent_seed.event(
            "withdrawn",
            surface="privacy_choices",
            session_id=_id("test-consent-session"),
            created_at=created,
        )

        body = await _report(client, await consent_seed.admin_headers())
        trend = body["withdrawal_trend"]
        assert trend["suppressed"] is True
        assert trend["current"] is None
        assert trend["previous"] is None

    async def test_empty_range_returns_zeroes(self, client: AsyncClient, consent_seed: ConsentSeed) -> None:
        body = await _report(
            client,
            await consent_seed.admin_headers(),
            {"start_date": "2016-01-01", "end_date": "2016-01-02"},
        )
        assert body["summary"]["granted"] == 0
        assert body["summary"]["denied"] == 0
        assert body["summary"]["withdrawn"] == 0
        assert body["summary"]["total"] == 0
        assert body["summary"]["consent_coverage_pct"] is None
        assert body["by_surface"] == []
        assert body["withdrawal_trend"]["current"] == 0
        assert body["withdrawal_trend"]["previous"] == 0
        assert body["replay_coverage"]["eligible_sessions"] == 0
        assert body["replay_coverage"]["coverage_pct"] is None

    async def test_non_admin_and_anonymous_callers_are_forbidden(
        self,
        client: AsyncClient,
        consent_seed: ConsentSeed,
    ) -> None:
        headers = await consent_seed.session_headers(await consent_seed.user())

        response = await client.get(ENDPOINT, params=RANGE, headers=headers)
        assert response.status_code == 403, response.text

        response = await client.get(ENDPOINT, params=RANGE)
        assert response.status_code in (401, 403), response.text

    async def test_invalid_date_range_is_rejected(
        self, client: AsyncClient, consent_seed: ConsentSeed
    ) -> None:
        response = await client.get(
            ENDPOINT,
            params={"start_date": "2019-02-08", "end_date": "2019-02-01"},
            headers=await consent_seed.admin_headers(),
        )
        assert response.status_code == 422, response.text
