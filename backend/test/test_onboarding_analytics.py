"""Onboarding step completion and drop-off analytics (issue #2074).

Covers allowlisted event capture, idempotent retries, consent gating, account
preference reconciliation, per-step reporting, plan/provider segmentation,
five-account suppression, aggregate-only privacy, empty ranges, and admin-only
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

NOW = datetime.now(timezone.utc)
EVENTS = "/analytics/onboarding/events"
REPORT = "/admin/analytics/onboarding"
RANGE = {"start_date": "2019-02-01", "end_date": "2019-02-07"}


def _id(prefix: str = "test-onboarding") -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


class OnboardingSeed:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.user_ids: list[str] = []
        self.anonymous_ids: set[str] = set()

    async def user(
        self,
        *,
        role: str = "user",
        plan: str = "free",
        provider: str = "email",
        has_onboarded: bool | None = None,
        created_at: datetime | None = None,
    ) -> str:
        user_id = str(uuid.uuid4())
        metadata = (
            {"preferences": {"has_onboarded": has_onboarded}}
            if has_onboarded is not None
            else None
        )
        await self.db.execute(
            text(
                "INSERT INTO users (id, email, name, role, email_verified, "
                "subscription_plan, subscription_status, auth_provider, trial_used, "
                "user_metadata, created_at) "
                "VALUES (:id, :email, 'Onboarding User', :role, true, :plan, 'active', "
                ":provider, false, CAST(:metadata AS JSONB), :created)"
            ),
            {
                "id": user_id,
                "email": f"test_onboarding_{user_id.replace('-', '')}@example.com",
                "role": role,
                "plan": plan,
                "provider": provider,
                "metadata": json.dumps(metadata) if metadata is not None else None,
                "created": created_at or NOW,
            },
        )
        self.user_ids.append(user_id)
        return user_id

    async def session_headers(self, user_id: str) -> dict[str, str]:
        token = f"test_sess_onboarding_{uuid.uuid4().hex}"
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
        return await self.session_headers(await self.user(role="admin", plan="pro"))

    async def consent(
        self,
        anonymous_id: str | None = None,
        *,
        decision: str = "granted",
        created_at: datetime | None = None,
    ) -> str:
        identifier = anonymous_id or _id("test-onboarding-anon")
        self.anonymous_ids.add(identifier)
        action = {
            "granted": "consent_granted",
            "denied": "consent_denied",
            "withdrawn": "consent_withdrawn",
        }[decision]
        await self.db.execute(
            text(
                "INSERT INTO usage_analytics "
                "(id, user_id, device_fingerprint, action, resource_type, event_metadata, created_at) "
                "VALUES (:id, NULL, NULL, :action, 'consent', CAST(:metadata AS JSONB), :created)"
            ),
            {
                "id": str(uuid.uuid4()),
                "action": action,
                "metadata": json.dumps(
                    {
                        "decision": decision,
                        "surface": "banner",
                        "source": "first_party_consent",
                        "anonymous_id": identifier,
                        "event_id": _id("test-onboarding-consent"),
                    }
                ),
                "created": created_at or NOW,
            },
        )
        await self.db.commit()
        return identifier

    async def event(
        self,
        user_id: str | None,
        action: str,
        step_key: str,
        *,
        duration_ms: int | None = None,
        completion_source: str | None = None,
        created_at: datetime | None = None,
        flow_version: str = "v1",
        event_id: str | None = None,
        extra_metadata: dict[str, object] | None = None,
    ) -> str:
        identifier = event_id or _id()
        metadata: dict[str, object] = {
            "event_id": identifier,
            "step_key": step_key,
            "flow_version": flow_version,
        }
        if duration_ms is not None:
            metadata["duration_ms"] = duration_ms
        if completion_source is not None:
            metadata["completion_source"] = completion_source
        if extra_metadata:
            metadata.update(extra_metadata)
        await self.db.execute(
            text(
                "INSERT INTO usage_analytics "
                "(id, user_id, device_fingerprint, action, resource_type, event_metadata, created_at) "
                "VALUES (:id, :uid, NULL, :action, 'onboarding', CAST(:metadata AS JSONB), :created)"
            ),
            {
                "id": str(uuid.uuid4()),
                "uid": user_id,
                "action": action,
                "metadata": json.dumps(metadata),
                "created": created_at or (NOW - timedelta(hours=1)),
            },
        )
        await self.db.commit()
        return identifier

    async def cleanup(self) -> None:
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
        if self.anonymous_ids:
            await self.db.execute(
                text(
                    "DELETE FROM usage_analytics "
                    "WHERE event_metadata->>'anonymous_id' = ANY(:ids)"
                ),
                {"ids": list(self.anonymous_ids)},
            )
        await self.db.commit()


@pytest.fixture
async def onboarding_seed(db_session: AsyncSession):
    seed = OnboardingSeed(db_session)
    yield seed
    await seed.cleanup()


async def _report(
    client: AsyncClient,
    headers: dict[str, str],
    params: dict[str, object] | None = None,
) -> dict:
    response = await client.get(REPORT, params=params or {"days": 30}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _payload(
    *,
    action: str = "onboarding_step_completed",
    step_key: str = "welcome",
    anonymous_id: str,
    event_id: str | None = None,
    duration_ms: int | None = 1200,
    completion_source: str | None = "next",
) -> dict[str, object]:
    return {
        "action": action,
        "step_key": step_key,
        "flow_version": "v1",
        "duration_ms": duration_ms,
        "completion_source": completion_source,
        "event_id": event_id or _id(),
        "anonymous_id": anonymous_id,
    }


class TestOnboardingCapture:
    async def test_records_allowlisted_event_and_reconciles_terminal_completion(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        onboarding_seed: OnboardingSeed,
    ) -> None:
        user_id = await onboarding_seed.user()
        anonymous_id = await onboarding_seed.consent()
        headers = await onboarding_seed.session_headers(user_id)
        payload = _payload(
            action="onboarding_step_completed",
            step_key="get-started",
            anonymous_id=anonymous_id,
            duration_ms=2500,
            completion_source="cta",
        )

        response = await client.post(EVENTS, json=payload, headers=headers)
        assert response.status_code == 202, response.text
        body = response.json()
        assert body["accepted"] is True
        assert body["recorded"] is True
        assert body["duplicate"] is False
        assert body["completion_reconciled"] is True

        row = (
            await db_session.execute(
                text(
                    "SELECT user_id, device_fingerprint, action, resource_type, "
                    "event_metadata, ip_address, user_agent FROM usage_analytics "
                    "WHERE event_metadata->>'event_id' = :event_id"
                ),
                {"event_id": payload["event_id"]},
            )
        ).one()
        assert str(row.user_id) == user_id
        assert row.device_fingerprint is None
        assert row.action == "onboarding_step_completed"
        assert row.resource_type == "onboarding"
        assert row.ip_address is None
        assert row.user_agent is None
        assert row.event_metadata == {
            "event_id": payload["event_id"],
            "step_key": "get-started",
            "flow_version": "v1",
            "duration_ms": 2500,
            "completion_source": "cta",
        }

        metadata = (
            await db_session.execute(
                text("SELECT user_metadata FROM users WHERE id = :id"),
                {"id": user_id},
            )
        ).scalar_one()
        assert metadata["preferences"]["has_onboarded"] is True

        serialized = json.dumps(row.event_metadata).lower()
        for forbidden in ("email", "name", "document", "latex", "@example.com"):
            assert forbidden not in serialized

    async def test_view_event_does_not_change_account_preference(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        onboarding_seed: OnboardingSeed,
    ) -> None:
        user_id = await onboarding_seed.user(has_onboarded=False)
        anonymous_id = await onboarding_seed.consent()
        headers = await onboarding_seed.session_headers(user_id)
        payload = _payload(
            action="onboarding_step_viewed",
            step_key="welcome",
            anonymous_id=anonymous_id,
            completion_source=None,
        )

        response = await client.post(EVENTS, json=payload, headers=headers)
        assert response.status_code == 202, response.text
        assert response.json()["completion_reconciled"] is False

        metadata = (
            await db_session.execute(
                text("SELECT user_metadata FROM users WHERE id = :id"),
                {"id": user_id},
            )
        ).scalar_one()
        assert metadata["preferences"]["has_onboarded"] is False

    async def test_duplicate_event_id_is_idempotent(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        onboarding_seed: OnboardingSeed,
    ) -> None:
        user_id = await onboarding_seed.user()
        anonymous_id = await onboarding_seed.consent()
        headers = await onboarding_seed.session_headers(user_id)
        payload = _payload(
            action="onboarding_step_skipped",
            step_key="features",
            anonymous_id=anonymous_id,
            completion_source="skip",
        )

        first = await client.post(EVENTS, json=payload, headers=headers)
        second = await client.post(EVENTS, json=payload, headers=headers)
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
                {"event_id": payload["event_id"]},
            )
        ).scalar_one()
        assert count == 1

        metadata = (
            await db_session.execute(
                text("SELECT user_metadata FROM users WHERE id = :id"),
                {"id": user_id},
            )
        ).scalar_one()
        assert metadata["preferences"]["has_onboarded"] is True

    async def test_consent_gating_and_withdrawal(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        onboarding_seed: OnboardingSeed,
    ) -> None:
        user_id = await onboarding_seed.user()
        headers = await onboarding_seed.session_headers(user_id)

        no_consent = _payload(anonymous_id=_id("test-onboarding-anon"))
        onboarding_seed.anonymous_ids.add(no_consent["anonymous_id"])
        response = await client.post(EVENTS, json=no_consent, headers=headers)
        assert response.status_code == 403, response.text

        anonymous_id = await onboarding_seed.consent(decision="denied")
        denied = _payload(anonymous_id=anonymous_id)
        response = await client.post(EVENTS, json=denied, headers=headers)
        assert response.status_code == 403, response.text

        await onboarding_seed.consent(anonymous_id, decision="granted", created_at=NOW + timedelta(minutes=1))
        await onboarding_seed.consent(
            anonymous_id,
            decision="withdrawn",
            created_at=NOW + timedelta(minutes=2),
        )
        withdrawn = _payload(anonymous_id=anonymous_id)
        response = await client.post(EVENTS, json=withdrawn, headers=headers)
        assert response.status_code == 403, response.text

        rejected_count = (
            await db_session.execute(
                text(
                    "SELECT count(*) FROM usage_analytics "
                    "WHERE event_metadata->>'event_id' = ANY(:ids)"
                ),
                {
                    "ids": [
                        no_consent["event_id"],
                        denied["event_id"],
                        withdrawn["event_id"],
                    ]
                },
            )
        ).scalar_one()
        assert rejected_count == 0

        await onboarding_seed.consent(
            anonymous_id,
            decision="granted",
            created_at=NOW + timedelta(minutes=3),
        )
        allowed = _payload(anonymous_id=anonymous_id)
        response = await client.post(EVENTS, json=allowed, headers=headers)
        assert response.status_code == 202, response.text
        assert response.json()["recorded"] is True

    async def test_rejects_unknown_fields_and_identifiers(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        onboarding_seed: OnboardingSeed,
    ) -> None:
        user_id = await onboarding_seed.user()
        anonymous_id = await onboarding_seed.consent()
        headers = await onboarding_seed.session_headers(user_id)

        with_email = _payload(anonymous_id=anonymous_id)
        with_email["email"] = "person@example.com"
        response = await client.post(EVENTS, json=with_email, headers=headers)
        assert response.status_code == 422, response.text

        with_unknown_step = _payload(anonymous_id=anonymous_id, step_key="salary")
        response = await client.post(EVENTS, json=with_unknown_step, headers=headers)
        assert response.status_code == 422, response.text

        with_bad_event_id = _payload(anonymous_id=anonymous_id, event_id="has spaces")
        response = await client.post(EVENTS, json=with_bad_event_id, headers=headers)
        assert response.status_code == 422, response.text

        count = (
            await db_session.execute(
                text("SELECT count(*) FROM usage_analytics WHERE user_id = :id"),
                {"id": user_id},
            )
        ).scalar_one()
        assert count == 0


class TestOnboardingReport:
    async def _seed_complete_and_skip(
        self, seed: OnboardingSeed
    ) -> tuple[list[str], list[str], list[str]]:
        completed = [
            await seed.user(plan="free", provider="email", has_onboarded=True)
            for _ in range(5)
        ]
        skipped = [
            await seed.user(plan="pro", provider="google", has_onboarded=True)
            for _ in range(5)
        ]
        abandoned = [
            await seed.user(plan="free", provider="email", has_onboarded=False)
            for _ in range(5)
        ]

        for user_id in completed:
            await seed.event(user_id, "onboarding_step_viewed", "welcome")
            await seed.event(
                user_id,
                "onboarding_step_completed",
                "welcome",
                duration_ms=1000,
                completion_source="next",
            )
            await seed.event(user_id, "onboarding_step_viewed", "how-it-works")
            await seed.event(
                user_id,
                "onboarding_step_completed",
                "how-it-works",
                duration_ms=2000,
                completion_source="next",
            )
            await seed.event(user_id, "onboarding_step_viewed", "features")
            await seed.event(
                user_id,
                "onboarding_step_completed",
                "features",
                duration_ms=3000,
                completion_source="next",
            )
            await seed.event(user_id, "onboarding_step_viewed", "get-started")
            await seed.event(
                user_id,
                "onboarding_step_completed",
                "get-started",
                duration_ms=4000,
                completion_source="cta",
            )

        for user_id in skipped:
            await seed.event(user_id, "onboarding_step_viewed", "welcome")
            await seed.event(
                user_id,
                "onboarding_step_completed",
                "welcome",
                duration_ms=1000,
                completion_source="next",
            )
            await seed.event(user_id, "onboarding_step_viewed", "how-it-works")
            await seed.event(
                user_id,
                "onboarding_step_skipped",
                "how-it-works",
                duration_ms=5000,
                completion_source="skip",
            )

        for user_id in abandoned:
            await seed.event(user_id, "onboarding_step_viewed", "welcome")

        return completed, skipped, abandoned

    async def test_per_step_metrics_segments_and_reconciliation(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        onboarding_seed: OnboardingSeed,
    ) -> None:
        completed, skipped, _ = await self._seed_complete_and_skip(onboarding_seed)

        body = await _report(client, await onboarding_seed.admin_headers())

        assert body["minimum_cohort_size"] == 5
        assert body["flow_version"] is None
        assert body["available_flow_versions"] == [{"flow_version": "v1", "events": 65}]

        summary = body["summary"]
        assert summary["accounts"] == 15
        assert summary["views"] == 20 + 10 + 5
        assert summary["step_completions"] == 25
        assert summary["completions"] == 5
        assert summary["skips"] == 5
        assert summary["terminal_accounts"] == 10
        assert summary["abandoned_accounts"] == 5
        assert summary["completion_rate"] == 33.33
        assert summary["skip_rate"] == 33.33
        assert summary["drop_off_rate"] == 33.33
        assert summary["median_duration_seconds"] == 2.0
        assert summary["suppressed"] is False

        steps = {row["step_key"]: row for row in body["steps"]}
        assert steps["welcome"]["views"] == 15
        assert steps["welcome"]["unique_viewers"] == 15
        assert steps["welcome"]["completions"] == 10
        assert steps["welcome"]["unique_completers"] == 10
        assert steps["welcome"]["skips"] == 0
        assert steps["welcome"]["abandoned_accounts"] == 5
        assert steps["welcome"]["drop_off_rate"] == 33.33
        assert steps["welcome"]["completion_rate"] == 66.67
        assert steps["welcome"]["median_duration_seconds"] == 1.0

        assert steps["how-it-works"]["views"] == 10
        assert steps["how-it-works"]["completions"] == 5
        assert steps["how-it-works"]["skips"] == 5
        assert steps["how-it-works"]["unique_skippers"] == 5
        assert steps["how-it-works"]["drop_off_rate"] == 0.0
        assert steps["how-it-works"]["completion_rate"] == 50.0
        assert steps["how-it-works"]["skip_rate"] == 50.0
        assert steps["how-it-works"]["median_duration_seconds"] == 2.0

        assert steps["features"]["views"] == 5
        assert steps["features"]["median_duration_seconds"] == 3.0
        assert steps["get-started"]["views"] == 5
        assert steps["get-started"]["median_duration_seconds"] == 4.0

        reconciliation = body["completion_reconciliation"]
        assert reconciliation["completed_accounts"] == 5
        assert reconciliation["skipped_accounts"] == 5
        assert reconciliation["terminal_accounts"] == 10
        assert reconciliation["preference_on_accounts"] == 10
        assert reconciliation["reconciled_accounts"] == 10
        assert reconciliation["missing_preference_accounts"] == 0
        assert reconciliation["preference_without_terminal_accounts"] == 0
        assert reconciliation["reconciled_rate"] == 100.0
        assert reconciliation["suppressed"] is False

        by_plan = {row["key"]: row for row in body["by_plan"]}
        assert set(by_plan) == {"free", "pro"}
        assert by_plan["free"]["accounts"] == 10
        assert by_plan["free"]["completions"] == 5
        assert by_plan["free"]["skips"] == 0
        assert by_plan["free"]["drop_off_rate"] == 50.0
        assert by_plan["pro"]["accounts"] == 5
        assert by_plan["pro"]["completions"] == 0
        assert by_plan["pro"]["skips"] == 5
        assert by_plan["pro"]["skip_rate"] == 100.0
        assert by_plan["pro"]["steps"][1]["step_key"] == "how-it-works"
        assert by_plan["pro"]["steps"][1]["skips"] == 5

        by_provider = {row["key"]: row for row in body["by_provider"]}
        assert set(by_provider) == {"email", "google"}
        assert by_provider["google"]["accounts"] == 5

        assert body["suppressed_segments"] == {"plan": 0, "provider": 0}
        assert body["truncated_events"] is False

        serialized = json.dumps(body).lower()
        for forbidden in (
            *completed[:1],
            *skipped[:1],
            "user_id",
            "event_id",
            "anonymous_id",
            "event_metadata",
            "@example.com",
            "onboarding user",
        ):
            assert forbidden.lower() not in serialized

    async def test_small_cohorts_are_suppressed(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        onboarding_seed: OnboardingSeed,
    ) -> None:
        for _ in range(4):
            user_id = await onboarding_seed.user(has_onboarded=True)
            await onboarding_seed.event(user_id, "onboarding_step_viewed", "welcome")
            await onboarding_seed.event(
                user_id,
                "onboarding_step_completed",
                "welcome",
                duration_ms=1000,
                completion_source="next",
            )
            await onboarding_seed.event(user_id, "onboarding_step_viewed", "get-started")
            await onboarding_seed.event(
                user_id,
                "onboarding_step_completed",
                "get-started",
                duration_ms=2000,
                completion_source="cta",
            )

        body = await _report(client, await onboarding_seed.admin_headers())

        assert body["summary"]["suppressed"] is True
        assert body["summary"]["accounts"] is None
        assert body["summary"]["views"] is None
        assert body["summary"]["drop_off_rate"] is None

        steps = {row["step_key"]: row for row in body["steps"]}
        assert steps["welcome"]["suppressed"] is True
        assert steps["welcome"]["views"] is None
        assert steps["welcome"]["median_duration_seconds"] is None
        assert steps["get-started"]["suppressed"] is True
        assert steps["how-it-works"]["suppressed"] is False
        assert steps["how-it-works"]["views"] == 0

        reconciliation = body["completion_reconciliation"]
        assert reconciliation["suppressed"] is True
        assert reconciliation["terminal_accounts"] is None
        assert reconciliation["reconciled_rate"] is None

        assert body["suppressed_segments"] == {"plan": 1, "provider": 1}
        assert body["by_plan"][0]["suppressed"] is True
        assert body["by_plan"][0]["accounts"] is None
        assert body["by_plan"][0]["steps"] == []
        assert body["by_provider"][0]["suppressed"] is True
        assert body["suppressed_rows"] >= 4
        assert body["suppressed_cells"] > 0

    async def test_reconciliation_reports_missing_and_stale_preference(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        onboarding_seed: OnboardingSeed,
    ) -> None:
        for _ in range(5):
            user_id = await onboarding_seed.user(has_onboarded=False)
            await onboarding_seed.event(
                user_id,
                "onboarding_step_completed",
                "get-started",
                duration_ms=2000,
                completion_source="cta",
            )
        for _ in range(5):
            user_id = await onboarding_seed.user(has_onboarded=True)
            await onboarding_seed.event(user_id, "onboarding_step_viewed", "welcome")

        body = await _report(client, await onboarding_seed.admin_headers())
        reconciliation = body["completion_reconciliation"]
        assert reconciliation["completed_accounts"] == 5
        assert reconciliation["terminal_accounts"] == 5
        assert reconciliation["preference_on_accounts"] == 0
        assert reconciliation["missing_preference_accounts"] == 5
        assert reconciliation["preference_without_terminal_accounts"] == 5
        assert reconciliation["reconciled_rate"] == 0.0
        assert reconciliation["suppressed"] is False

    async def test_empty_range_returns_zeroed_steps_without_suppression(
        self,
        client: AsyncClient,
        onboarding_seed: OnboardingSeed,
    ) -> None:
        body = await _report(
            client,
            await onboarding_seed.admin_headers(),
            {"start_date": "2016-01-01", "end_date": "2016-01-02"},
        )
        assert body["summary"]["accounts"] == 0
        assert body["summary"]["suppressed"] is False
        assert [row["step_key"] for row in body["steps"]] == [
            "welcome",
            "how-it-works",
            "features",
            "get-started",
        ]
        assert all(row["views"] == 0 for row in body["steps"])
        assert body["completion_reconciliation"]["terminal_accounts"] == 0
        assert body["completion_reconciliation"]["suppressed"] is False
        assert body["by_plan"] == []
        assert body["by_provider"] == []

    async def test_flow_version_filter(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        onboarding_seed: OnboardingSeed,
    ) -> None:
        for _ in range(5):
            user_id = await onboarding_seed.user()
            await onboarding_seed.event(
                user_id, "onboarding_step_viewed", "welcome", flow_version="v1"
            )
            await onboarding_seed.event(
                user_id, "onboarding_step_viewed", "welcome", flow_version="v2"
            )

        body = await _report(
            client,
            await onboarding_seed.admin_headers(),
            {"days": 30, "flow_version": "v2"},
        )
        assert body["flow_version"] == "v2"
        assert body["summary"]["views"] == 5
        assert body["available_flow_versions"] == [
            {"flow_version": "v1", "events": 5},
            {"flow_version": "v2", "events": 5},
        ]

    async def test_non_admin_and_anonymous_callers_are_forbidden(
        self,
        client: AsyncClient,
        onboarding_seed: OnboardingSeed,
    ) -> None:
        headers = await onboarding_seed.session_headers(await onboarding_seed.user())
        response = await client.get(REPORT, params={"days": 30}, headers=headers)
        assert response.status_code == 403, response.text

        response = await client.get(REPORT, params={"days": 30})
        assert response.status_code in (401, 403), response.text

        response = await client.post(EVENTS, json=_payload(anonymous_id=_id("test-onboarding-anon")))
        assert response.status_code in (401, 403), response.text

    async def test_invalid_date_range_is_rejected(
        self,
        client: AsyncClient,
        onboarding_seed: OnboardingSeed,
    ) -> None:
        response = await client.get(
            REPORT,
            params={"start_date": "2019-02-08", "end_date": "2019-02-01"},
            headers=await onboarding_seed.admin_headers(),
        )
        assert response.status_code == 422, response.text
