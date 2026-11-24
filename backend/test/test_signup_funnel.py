"""Signup funnel and email-verification metrics by auth provider (issue #2065).

Covers server-derived provider assignment, start -> complete -> verified
conversion, median time-to-verify, OAuth failure counters, small-cohort
suppression, PII/token exclusion and admin-only access.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.signup_funnel_service import (
    normalize_provider_claim,
    provider_from_auth_id,
    signup_funnel_service,
)

NOW = datetime.now(timezone.utc)


async def _create_user(
    db: AsyncSession,
    *,
    plan: str = "free",
    role: str = "user",
    email_verified: bool = False,
    created_at: datetime | None = None,
    auth_provider: str | None = None,
    account_provider: str | None = None,
    email: str | None = None,
    name: str = "Funnel User",
) -> str:
    user_id = str(uuid.uuid4())
    columns = [
        "id",
        "email",
        "name",
        "role",
        "email_verified",
        "subscription_plan",
        "subscription_status",
        "trial_used",
        "created_at",
    ]
    values = [
        ":id",
        ":email",
        ":name",
        ":role",
        ":verified",
        ":plan",
        "'active'",
        "false",
        ":created",
    ]
    params = {
        "id": user_id,
        "email": email or f"test_{user_id.replace('-', '')}@example.com",
        "name": name,
        "role": role,
        "verified": email_verified,
        "plan": plan,
        "created": created_at or NOW,
    }
    if auth_provider is not None:
        columns.append("auth_provider")
        values.append(":auth_provider")
        params["auth_provider"] = auth_provider
    await db.execute(
        text(
            f"INSERT INTO users ({', '.join(columns)}) VALUES ({', '.join(values)})"
        ),
        params,
    )
    if account_provider is not None:
        await db.execute(
            text(
                'INSERT INTO account (id, "userId", "accountId", "providerId", "accessToken") '
                "VALUES (:id, :uid, :account, :provider, :token)"
            ),
            {
                "id": str(uuid.uuid4()),
                "uid": user_id,
                "account": f"account_{uuid.uuid4().hex}",
                "provider": account_provider,
                "token": f"secret-token-{uuid.uuid4().hex}",
            },
        )
    return user_id


async def _session_headers(
    db: AsyncSession, user_id: str, *, role: str = "user"
) -> dict[str, str]:
    token = f"funnel_sess_{uuid.uuid4().hex}"
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


async def _admin_headers(db: AsyncSession) -> dict[str, str]:
    admin_id = await _create_user(db, role="admin")
    return await _session_headers(db, admin_id, role="admin")


async def _insert_event(
    db: AsyncSession,
    *,
    event: str,
    provider: str,
    user_id: str | None = None,
    created_at: datetime | None = None,
    failure_code: str | None = None,
) -> None:
    await db.execute(
        text(
            "INSERT INTO signup_funnel_events "
            "(id, user_id, event, provider, failure_code, created_at) "
            "VALUES (:id, :uid, :event, :provider, :code, :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "event": event,
            "provider": provider,
            "code": failure_code,
            "created": created_at or NOW,
        },
    )


class TestProviderAssignment:
    def test_allowlist_normalizes_claims_and_server_ids(self):
        assert normalize_provider_claim("email") == "email"
        assert normalize_provider_claim("credential") == "email"
        assert normalize_provider_claim(" Google ") == "google"
        assert normalize_provider_claim("salesforce") == "unknown"
        assert normalize_provider_claim(None) == "unknown"

        assert provider_from_auth_id("credential") == "email"
        assert provider_from_auth_id("github") == "github"
        assert provider_from_auth_id("acme-university-sso") == "oidc"
        assert provider_from_auth_id(None) == "unknown"

    async def test_new_account_defaults_to_unknown_and_sync_derives_server_value(
        self, db_session: AsyncSession
    ):
        plan = f"provider_{uuid.uuid4().hex[:10]}"
        email_user = await _create_user(
            db_session, plan=plan, account_provider="credential"
        )
        google_user = await _create_user(
            db_session, plan=plan, account_provider="google"
        )
        oidc_user = await _create_user(
            db_session, plan=plan, account_provider="acme-university-sso"
        )
        unknown_user = await _create_user(db_session, plan=plan)

        for user_id in (email_user, google_user, oidc_user, unknown_user):
            await signup_funnel_service.record_signup_milestones(
                db_session, user_id=user_id
            )

        rows = (
            await db_session.execute(
                text(
                    "SELECT id, auth_provider FROM users "
                    "WHERE id = ANY(:ids)"
                ),
                {"ids": [email_user, google_user, oidc_user, unknown_user]},
            )
        ).all()
        providers = {str(row[0]): row[1] for row in rows}
        assert providers[email_user] == "email"
        assert providers[google_user] == "google"
        assert providers[oidc_user] == "oidc"
        assert providers[unknown_user] == "unknown"

        # An authenticated client label must never override server state.
        recorded = await signup_funnel_service.record_signup_started(
            db_session, user_id=unknown_user, provider="google"
        )
        assert recorded == "unknown"
        event_provider = (
            await db_session.execute(
                text(
                    "SELECT provider FROM signup_funnel_events "
                    "WHERE user_id = :uid AND event = 'signup_started'"
                ),
                {"uid": unknown_user},
            )
        ).scalar_one()
        assert event_provider == "unknown"

    async def test_anonymous_attempt_labels_are_allowlisted(self, db_session: AsyncSession):
        assert (
            await signup_funnel_service.record_signup_started(
                db_session, provider="github"
            )
            == "github"
        )
        assert (
            await signup_funnel_service.record_signup_started(
                db_session, provider="not-a-provider"
            )
            == "unknown"
        )
        assert (
            await signup_funnel_service.record_oauth_failure(
                db_session, provider="acme-sso", failure_code="access_denied"
            )
            == "unknown"
        )


class TestSignupFunnelReport:
    async def test_start_complete_verified_conversion_and_median(
        self, db_session: AsyncSession
    ):
        plan = f"funnel_{uuid.uuid4().hex[:10]}"
        signup = NOW - timedelta(days=10)
        user_ids: list[str] = []
        for index in range(5):
            user_id = await _create_user(
                db_session,
                plan=plan,
                email_verified=False,
                created_at=signup,
                account_provider="credential",
            )
            user_ids.append(user_id)
            await signup_funnel_service.record_signup_started(
                db_session, user_id=user_id
            )
            await signup_funnel_service.record_signup_milestones(
                db_session, user_id=user_id
            )

        offsets = [1, 2, 3]
        for user_id, hours in zip(user_ids[:3], offsets):
            await _insert_event(
                db_session,
                event="email_verified",
                provider="email",
                user_id=user_id,
                created_at=signup + timedelta(hours=hours),
            )
        await db_session.execute(
            text(
                "UPDATE users SET email_verified = true WHERE id = ANY(:ids)"
            ),
            {"ids": user_ids[:3]},
        )
        await db_session.commit()

        result = await signup_funnel_service.signup_funnel(
            db_session, days=30, plan=plan
        )
        assert result["started"] == 5
        assert result["completed"] == 5
        assert result["verified"] == 3
        assert result["verification_rate"] == 60.0
        assert result["conversion_start_to_complete"] == 100.0
        assert result["conversion_complete_to_verified"] == 60.0
        # Median of 1h, 2h and 3h.
        assert result["median_seconds_to_verify"] == pytest.approx(7200, abs=1)
        assert result["median_days_to_verify"] == pytest.approx(2 / 24, abs=0.01)

        steps = {step["key"]: step for step in result["steps"]}
        assert steps["signup_started"]["count"] == 5
        assert steps["signup_completed"]["count"] == 5
        assert steps["email_verified"]["count"] == 3
        assert steps["signup_completed"]["from_previous"] == 100.0
        assert steps["email_verified"]["from_previous"] == 60.0

        email_segment = next(
            row for row in result["by_provider"] if row["provider"] == "email"
        )
        assert email_segment["users"] == 5
        assert email_segment["started"] == 5
        assert email_segment["completed"] == 5
        assert email_segment["verified"] == 3
        assert email_segment["verification_rate"] == 60.0
        assert email_segment["median_seconds_to_verify"] == pytest.approx(7200, abs=1)

    async def test_small_provider_cohorts_are_suppressed(
        self, db_session: AsyncSession
    ):
        plan = f"suppress_{uuid.uuid4().hex[:10]}"
        signup = NOW - timedelta(days=3)
        for _ in range(4):
            await _create_user(
                db_session,
                plan=plan,
                created_at=signup,
                auth_provider="google",
            )
        for _ in range(5):
            await _create_user(
                db_session,
                plan=plan,
                created_at=signup,
                auth_provider="email",
            )
        await db_session.commit()

        result = await signup_funnel_service.signup_funnel(
            db_session, days=30, plan=plan
        )
        labels = {row["provider"] for row in result["by_provider"]}
        assert "email" in labels
        assert "google" not in labels
        assert result["suppressed_segments"]["provider"] >= 1
        assert result["minimum_segment_size"] == 5
        assert all(row["users"] >= 5 for row in result["by_provider"])

    async def test_oauth_failures_are_counted_by_provider_without_pii(
        self, db_session: AsyncSession
    ):
        before = await signup_funnel_service.signup_funnel(db_session, days=30)
        baseline = {
            row["provider"]: row["count"]
            for row in before["oauth_failures"]["by_provider"]
        }

        for provider, count in (("google", 3), ("github", 2), ("oidc", 1)):
            for index in range(count):
                await signup_funnel_service.record_oauth_failure(
                    db_session,
                    provider=provider,
                    failure_code="access_denied" if index == 0 else "provider_error",
                )
        # Raw provider ids and free-form error text are never persisted raw.
        await signup_funnel_service.record_oauth_failure(
            db_session,
            provider="acme-university-sso",
            failure_code="provider said no: token=leak",
        )

        after = await signup_funnel_service.signup_funnel(db_session, days=30)
        counts = {
            row["provider"]: row["count"]
            for row in after["oauth_failures"]["by_provider"]
        }
        assert counts.get("google", 0) - baseline.get("google", 0) == 3
        assert counts.get("github", 0) - baseline.get("github", 0) == 2
        assert counts.get("oidc", 0) - baseline.get("oidc", 0) == 1
        assert counts.get("unknown", 0) - baseline.get("unknown", 0) == 1
        assert after["oauth_failures"]["total"] - before["oauth_failures"]["total"] == 7
        codes = {row["code"] for row in after["oauth_failures"]["by_code"]}
        assert codes <= {
            "access_denied",
            "account_not_linked",
            "callback_failed",
            "provider_error",
            "state_mismatch",
            "unknown",
        }

    async def test_empty_period_is_stable(self, db_session: AsyncSession):
        plan = f"empty_{uuid.uuid4().hex[:10]}"
        result = await signup_funnel_service.signup_funnel(
            db_session, days=30, plan=plan
        )
        assert result["cohort_size"] == 0
        assert result["started"] == 0
        assert result["completed"] == 0
        assert result["verified"] == 0
        assert result["median_seconds_to_verify"] is None
        assert result["by_provider"] == []
        assert [step["count"] for step in result["steps"]] == [0, 0, 0]


class TestSignupFunnelRoutes:
    async def test_started_endpoint_rejects_unknown_provider(
        self, client: AsyncClient
    ):
        accepted = await client.post(
            "/analytics/signup/started", json={"provider": "google"}
        )
        assert accepted.status_code == 202
        assert accepted.json() == {"recorded": "signup_started", "provider": "google"}

        rejected = await client.post(
            "/analytics/signup/started", json={"provider": "salesforce"}
        )
        assert rejected.status_code == 422

    async def test_oauth_failure_endpoint_rejects_free_form_values(
        self, client: AsyncClient
    ):
        accepted = await client.post(
            "/analytics/signup/oauth-failure",
            json={"provider": "github", "failure_code": "callback_failed"},
        )
        assert accepted.status_code == 202
        assert accepted.json()["provider"] == "github"

        rejected = await client.post(
            "/analytics/signup/oauth-failure",
            json={"provider": "github", "failure_code": "token=secret"},
        )
        assert rejected.status_code == 422

    async def test_milestones_require_a_session_and_are_idempotent(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        unauthenticated = await client.post("/analytics/signup/milestones")
        assert unauthenticated.status_code == 401

        plan = f"milestones_{uuid.uuid4().hex[:10]}"
        user_id = await _create_user(
            db_session,
            plan=plan,
            email_verified=True,
            account_provider="google",
        )
        headers = await _session_headers(db_session, user_id)

        first = await client.post("/analytics/signup/milestones", headers=headers)
        assert first.status_code == 200
        body = first.json()
        assert body["provider"] == "google"
        assert body["email_verified"] is True
        assert set(body["recorded"]) == {"signup_completed", "email_verified"}

        second = await client.post("/analytics/signup/milestones", headers=headers)
        assert second.status_code == 200
        assert second.json()["recorded"] == []

        stored = (
            await db_session.execute(
                text("SELECT auth_provider FROM users WHERE id = :uid"),
                {"uid": user_id},
            )
        ).scalar_one()
        assert stored == "google"

    async def test_admin_activation_includes_provider_funnel_without_pii(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_headers = await _admin_headers(db_session)
        plan = f"admin_{uuid.uuid4().hex[:10]}"
        signup = NOW - timedelta(days=2)
        secret_email = f"test_{uuid.uuid4().hex}@example.com"
        secret_name = "Sensitive Funnel Name"
        user_ids = []
        for _ in range(5):
            user_id = await _create_user(
                db_session,
                plan=plan,
                email_verified=False,
                created_at=signup,
                account_provider="github",
                email=secret_email if not user_ids else None,
                name=secret_name if not user_ids else "Funnel User",
            )
            user_ids.append(user_id)
            await signup_funnel_service.record_signup_started(
                db_session, user_id=user_id
            )
            await signup_funnel_service.record_signup_milestones(
                db_session, user_id=user_id
            )
        await db_session.execute(
            text("UPDATE users SET email_verified = true WHERE id = ANY(:ids)"),
            {"ids": user_ids},
        )
        await _insert_event(
            db_session,
            event="email_verified",
            provider="github",
            user_id=user_ids[0],
            created_at=signup + timedelta(hours=4),
        )
        await db_session.commit()

        response = await client.get(
            f"/admin/analytics/activation?days=30&plan={plan}",
            headers=admin_headers,
        )
        assert response.status_code == 200
        payload = response.json()
        funnel = payload["signup_funnel"]
        assert funnel["completed"] == 5
        assert funnel["verified"] == 5
        github = next(
            row for row in funnel["by_provider"] if row["provider"] == "github"
        )
        assert github["users"] == 5
        assert github["verified"] == 5
        assert github["median_seconds_to_verify"] == pytest.approx(14400, abs=1)

        # Accounts remain server-attributed even though no client provider was
        # sent; the account's OAuth token and the user's email/name never appear.
        assert "secret-token-" not in response.text
        assert secret_email not in response.text
        assert secret_name not in response.text
        assert "@example.com" not in response.text
        assert "accessToken" not in response.text

    async def test_conversion_funnel_has_provider_segmentation(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        headers = await _admin_headers(db_session)
        response = await client.get("/analytics/conversion-funnel?days=30", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert "signup" in body
        assert "by_provider" in body
        assert body["signup"]["minimum_segment_size"] == 5

    async def test_non_admin_is_forbidden(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id = await _create_user(db_session)
        headers = await _session_headers(db_session, user_id)

        activation = await client.get(
            "/admin/analytics/activation", headers=headers
        )
        assert activation.status_code == 403

        funnel = await client.get("/analytics/conversion-funnel", headers=headers)
        assert funnel.status_code == 403
