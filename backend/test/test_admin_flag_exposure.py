"""Feature-flag exposure capture and outcome joins (issue #2157).

Covers consent-safe capture, one row per subject/flag/variant/evaluation window,
no-PII storage, admin-only access, five-user suppression, the activation/compile/
checkout/retention join, metric definitions, the no-causality policy, and the
unchanged audited kill-switch path.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AdminAuditLog

CAPTURE = "/analytics/flag-exposure"
REPORT = "/admin/analytics/flag-exposure"
NOW = datetime.now(timezone.utc)
EXPOSURE_AT = NOW - timedelta(days=2)


def _id(prefix: str = "test-flag-exposure") -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


class FlagSeed:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.user_ids: list[str] = []
        self.anonymous_ids: set[str] = set()

    async def user(self, *, role: str = "user") -> str:
        user_id = str(uuid.uuid4())
        await self.db.execute(
            text(
                "INSERT INTO users (id, email, name, role, email_verified, "
                "subscription_plan, subscription_status, trial_used, created_at) "
                "VALUES (:id, :email, 'Flag Exposure User', :role, true, 'free', "
                "'active', false, :created)"
            ),
            {
                "id": user_id,
                "email": f"test_flag_exposure_{user_id.replace('-', '')}@example.com",
                "role": role,
                "created": NOW,
            },
        )
        self.user_ids.append(user_id)
        await self.db.commit()
        return user_id

    async def headers(self, user_id: str) -> dict[str, str]:
        token = f"test_sess_flag_exposure_{uuid.uuid4().hex}"
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

    async def user_headers(self, *, role: str = "user") -> tuple[str, dict[str, str]]:
        user_id = await self.user(role=role)
        return user_id, await self.headers(user_id)

    async def consent(
        self,
        anonymous_id: str,
        *,
        decision: str = "granted",
        created_at: datetime | None = None,
    ) -> None:
        action = {
            "granted": "consent_granted",
            "denied": "consent_denied",
            "withdrawn": "consent_withdrawn",
        }[decision]
        self.anonymous_ids.add(anonymous_id)
        await self.db.execute(
            text(
                "INSERT INTO usage_analytics (id, user_id, action, resource_type, "
                "event_metadata, created_at) "
                "VALUES (:id, NULL, :action, 'consent', CAST(:metadata AS JSONB), :created)"
            ),
            {
                "id": str(uuid.uuid4()),
                "action": action,
                "metadata": json.dumps(
                    {
                        "decision": decision,
                        "surface": "banner",
                        "source": "first_party_consent",
                        "anonymous_id": anonymous_id,
                        "event_id": _id("test-flag-exposure-consent"),
                    }
                ),
                "created": created_at or NOW - timedelta(minutes=5),
            },
        )
        await self.db.commit()

    async def exposure(
        self,
        user_id: str,
        *,
        enabled: bool,
        created_at: datetime = EXPOSURE_AT,
        key: str = "upgrade_ctas",
    ) -> None:
        variant = "treatment" if enabled else "control"
        await self.db.execute(
            text(
                "INSERT INTO usage_analytics (id, user_id, action, resource_type, "
                "event_metadata, created_at) "
                "VALUES (:id, :uid, 'flag_exposed', 'feature_flag', "
                "CAST(:metadata AS JSONB), :created)"
            ),
            {
                "id": str(uuid.uuid4()),
                "uid": user_id,
                "metadata": json.dumps(
                    {
                        "flag_key": key,
                        "variant": variant,
                        "enabled": enabled,
                        "window": created_at.date().isoformat(),
                        "source": "first_party_flag_evaluation",
                    }
                ),
                "created": created_at,
            },
        )
        await self.db.commit()

    async def resume(self, user_id: str, created_at: datetime) -> None:
        await self.db.execute(
            text(
                "INSERT INTO resumes (id, user_id, title, latex_content, created_at, updated_at) "
                "VALUES (:id, :uid, 'test flag exposure', 'test', :created, :created)"
            ),
            {"id": str(uuid.uuid4()), "uid": user_id, "created": created_at},
        )
        await self.db.commit()

    async def compilation(self, user_id: str, *, status: str, created_at: datetime) -> None:
        await self.db.execute(
            text(
                "INSERT INTO compilations (id, user_id, resume_id, job_id, status, "
                "error_class, created_at) "
                "VALUES (:id, :uid, NULL, :job, :status, :error_class, :created)"
            ),
            {
                "id": str(uuid.uuid4()),
                "uid": user_id,
                "job": f"test_flag_job_{uuid.uuid4().hex}",
                "status": status,
                "error_class": "timeout" if status == "failed" else "unknown",
                "created": created_at,
            },
        )
        await self.db.commit()

    async def checkout(self, user_id: str, *, paid: bool, created_at: datetime) -> None:
        subscription_id = str(uuid.uuid4())
        await self.db.execute(
            text(
                "INSERT INTO subscriptions (id, user_id, provider, provider_subscription_id, "
                "plan_id, status, created_at, updated_at) "
                "VALUES (:id, :uid, 'test', :provider_sub, 'pro', :status, :created, :created)"
            ),
            {
                "id": subscription_id,
                "uid": user_id,
                "provider_sub": f"test_sub_{uuid.uuid4().hex}",
                "status": "active" if paid else "pending",
                "created": created_at,
            },
        )
        await self.db.commit()

    async def activity(self, user_id: str, created_at: datetime) -> None:
        await self.db.execute(
            text(
                "INSERT INTO usage_analytics (id, user_id, action, resource_type, "
                "event_metadata, created_at) "
                "VALUES (:id, :uid, 'workspace_opened', 'test', NULL, :created)"
            ),
            {"id": str(uuid.uuid4()), "uid": user_id, "created": created_at},
        )
        await self.db.commit()

    async def cleanup(self) -> None:
        if self.user_ids:
            params = {"ids": self.user_ids}
            await self.db.execute(
                text("DELETE FROM payments WHERE user_id = ANY(CAST(:ids AS uuid[]))"),
                params,
            )
            await self.db.execute(
                text("DELETE FROM subscriptions WHERE user_id = ANY(CAST(:ids AS uuid[]))"),
                params,
            )
            await self.db.execute(
                text("DELETE FROM compilations WHERE user_id = ANY(CAST(:ids AS uuid[]))"),
                params,
            )
            await self.db.execute(
                text("DELETE FROM optimizations WHERE user_id = ANY(CAST(:ids AS uuid[]))"),
                params,
            )
            await self.db.execute(
                text("DELETE FROM resumes WHERE user_id = ANY(CAST(:ids AS uuid[]))"),
                params,
            )
            await self.db.execute(
                text("DELETE FROM usage_analytics WHERE user_id = ANY(CAST(:ids AS uuid[]))"),
                params,
            )
            await self.db.execute(
                text('DELETE FROM session WHERE "userId" = ANY(:ids)'),
                params,
            )
            await self.db.execute(
                text("DELETE FROM users WHERE id = ANY(CAST(:ids AS uuid[]))"),
                params,
            )
        if self.anonymous_ids:
            await self.db.execute(
                text(
                    "DELETE FROM usage_analytics "
                    "WHERE event_metadata->>'anonymous_id' = ANY(:ids)"
                ),
                {"ids": sorted(self.anonymous_ids)},
            )
        await self.db.commit()


@pytest.fixture
async def flag_seed(db_session: AsyncSession):
    seed = FlagSeed(db_session)
    yield seed
    await seed.cleanup()


async def _report(client: AsyncClient, headers: dict[str, str]) -> dict:
    response = await client.get(REPORT, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _flag(body: dict, key: str = "upgrade_ctas") -> dict:
    return next(flag for flag in body["flags"] if flag["key"] == key)


def _metric(window: dict, key: str) -> dict:
    return next(metric for metric in window["metrics"] if metric["key"] == key)


class TestExposureCapture:
    async def test_requires_consent_and_records_allowlisted_metadata(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        flag_seed: FlagSeed,
    ) -> None:
        user_id, headers = await flag_seed.user_headers()
        anonymous_id = _id()

        response = await client.post(
            CAPTURE,
            headers=headers,
            json={
                "anonymous_id": anonymous_id,
                "flags": [{"key": "upgrade_ctas", "enabled": True}],
            },
        )
        assert response.status_code == 403, response.text

        await flag_seed.consent(anonymous_id)
        response = await client.post(
            CAPTURE,
            headers=headers,
            json={
                "anonymous_id": anonymous_id,
                "flags": [
                    {"key": "upgrade_ctas", "enabled": True},
                    {"key": "billing", "enabled": False},
                ],
            },
        )
        assert response.status_code == 202, response.text
        body = response.json()
        assert body["accepted"] == 2
        assert body["duplicate"] == 0
        assert body["rejected"] == 0
        assert body["window"] == datetime.now(timezone.utc).date().isoformat()

        rows = (
            await db_session.execute(
                text(
                    "SELECT action, resource_type, user_id, device_fingerprint, "
                    "ip_address, user_agent, event_metadata "
                    "FROM usage_analytics WHERE user_id = :uid AND action = 'flag_exposed'"
                ),
                {"uid": user_id},
            )
        ).all()
        assert len(rows) == 2
        variants = set()
        for row in rows:
            assert row.action == "flag_exposed"
            assert row.resource_type == "feature_flag"
            assert str(row.user_id) == user_id
            assert row.device_fingerprint is None
            assert row.ip_address is None
            assert row.user_agent is None
            assert set(row.event_metadata) == {
                "flag_key",
                "variant",
                "enabled",
                "window",
                "source",
            }
            variants.add((row.event_metadata["flag_key"], row.event_metadata["variant"]))
            serialized = json.dumps(row.event_metadata).lower()
            assert anonymous_id.lower() not in serialized
            assert "@" not in serialized
            assert "email" not in serialized
            assert "document" not in serialized
        assert variants == {("upgrade_ctas", "treatment"), ("billing", "control")}

    async def test_dedupes_per_subject_flag_variant_and_evaluation_window(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        flag_seed: FlagSeed,
    ) -> None:
        user_id, headers = await flag_seed.user_headers()
        anonymous_id = _id()
        await flag_seed.consent(anonymous_id)
        payload = {
            "anonymous_id": anonymous_id,
            "flags": [{"key": "upgrade_ctas", "enabled": True}],
        }

        first = await client.post(CAPTURE, headers=headers, json=payload)
        second = await client.post(CAPTURE, headers=headers, json=payload)
        assert first.status_code == 202, first.text
        assert first.json()["accepted"] == 1
        assert second.json()["accepted"] == 0
        assert second.json()["duplicate"] == 1

        # A prior UTC window is a different dedupe key, so today's evaluation is
        # still accepted even though the flag value is unchanged.
        second_user_id, second_headers = await flag_seed.user_headers()
        yesterday = NOW - timedelta(days=1)
        await flag_seed.exposure(
            second_user_id,
            enabled=True,
            created_at=yesterday,
            key="upgrade_ctas",
        )
        third = await client.post(CAPTURE, headers=second_headers, json=payload)
        assert third.status_code == 202, third.text
        assert third.json()["accepted"] == 1

        count = (
            await db_session.execute(
                text(
                    "SELECT count(*) FROM usage_analytics "
                    "WHERE user_id = :uid AND action = 'flag_exposed' "
                    "AND event_metadata->>'flag_key' = 'upgrade_ctas' "
                    "AND event_metadata->>'variant' = 'treatment'"
                ),
                {"uid": second_user_id},
            )
        ).scalar_one()
        assert count == 2

        # A withdrawal recorded after the grant supersedes it.
        await flag_seed.consent(
            anonymous_id,
            decision="withdrawn",
            created_at=NOW + timedelta(minutes=1),
        )
        denied = await client.post(CAPTURE, headers=headers, json=payload)
        assert denied.status_code == 403, denied.text

    async def test_rejects_unknown_fields_keys_and_unauthenticated_callers(
        self,
        client: AsyncClient,
        flag_seed: FlagSeed,
    ) -> None:
        _user_id, headers = await flag_seed.user_headers()
        anonymous_id = _id()
        await flag_seed.consent(anonymous_id)

        extra = await client.post(
            CAPTURE,
            headers=headers,
            json={
                "anonymous_id": anonymous_id,
                "flags": [{"key": "upgrade_ctas", "enabled": True}],
                "email": "person@example.com",
            },
        )
        assert extra.status_code == 422, extra.text

        unknown = await client.post(
            CAPTURE,
            headers=headers,
            json={
                "anonymous_id": anonymous_id,
                "flags": [{"key": "not_a_real_flag", "enabled": True}],
            },
        )
        assert unknown.status_code == 422, unknown.text

        anonymous = await client.post(
            CAPTURE,
            json={
                "anonymous_id": anonymous_id,
                "flags": [{"key": "upgrade_ctas", "enabled": True}],
            },
        )
        assert anonymous.status_code in (401, 403), anonymous.text


class TestFlagExposureReport:
    async def _seed_group(
        self,
        seed: FlagSeed,
        *,
        enabled: bool,
        count: int,
        activation: int,
        compile_success: int,
        checkout: int,
        retention: int,
        failed_compile: int,
    ) -> None:
        for index in range(count):
            user_id = await seed.user()
            await seed.exposure(user_id, enabled=enabled)
            if index < activation:
                await seed.resume(user_id, EXPOSURE_AT + timedelta(hours=1))
            if index < compile_success:
                await seed.compilation(
                    user_id,
                    status="completed",
                    created_at=EXPOSURE_AT + timedelta(hours=2),
                )
            if index < failed_compile:
                await seed.compilation(
                    user_id,
                    status="failed",
                    created_at=EXPOSURE_AT + timedelta(hours=3),
                )
            if index < checkout:
                await seed.checkout(
                    user_id,
                    paid=True,
                    created_at=EXPOSURE_AT + timedelta(hours=4),
                )
            if index < retention:
                await seed.activity(user_id, EXPOSURE_AT + timedelta(hours=25))

    async def test_joins_outcomes_and_guardrails_with_five_user_suppression(
        self,
        client: AsyncClient,
        flag_seed: FlagSeed,
    ) -> None:
        _user_id, admin_headers = await flag_seed.user_headers(role="admin")
        await self._seed_group(
            flag_seed,
            enabled=True,
            count=10,
            activation=8,
            compile_success=9,
            checkout=3,
            retention=6,
            failed_compile=2,
        )
        await self._seed_group(
            flag_seed,
            enabled=False,
            count=10,
            activation=3,
            compile_success=7,
            checkout=5,
            retention=4,
            failed_compile=5,
        )

        body = await _report(client, admin_headers)
        flag = _flag(body)
        assert flag["outcome_horizon_days"] == 7
        assert flag["minimum_group_size"] == 5
        assert set(flag["windows"]) == {"7", "30"}

        for window_days in ("7", "30"):
            window = flag["windows"][window_days]
            treatment = window["groups"]["treatment"]
            control = window["groups"]["control"]
            assert treatment["sample_size"] == 10
            assert control["sample_size"] == 10
            assert treatment["exposure_events"] == 10
            assert control["exposure_events"] == 10
            assert treatment["suppressed"] is False
            assert control["suppressed"] is False
            assert treatment["right_censored_subjects"] is not None

            activation = _metric(window, "activation")
            assert activation["treatment"]["numerator"] == 8
            assert activation["treatment"]["denominator"] == 10
            assert activation["treatment"]["rate_pct"] == 80.0
            assert activation["control"]["rate_pct"] is None
            assert activation["control"]["suppressed"] is True
            assert activation["difference_pp"] is None

            compile_success = _metric(window, "compile_success")
            assert compile_success["treatment"]["rate_pct"] == 90.0
            assert compile_success["control"]["rate_pct"] == 70.0
            assert compile_success["difference_pp"] == 20.0
            assert compile_success["comparable"] is True

            checkout = _metric(window, "checkout_started")
            assert checkout["treatment"]["rate_pct"] is None
            assert checkout["control"]["rate_pct"] == 50.0

            retention = _metric(window, "retention_7d")
            assert retention["treatment"]["rate_pct"] == 60.0
            assert retention["control"]["rate_pct"] is None

            compile_errors = _metric(window, "compile_error_rate")
            assert compile_errors["kind"] == "guardrail"
            assert compile_errors["treatment"]["rate_pct"] is None
            assert compile_errors["control"]["denominator"] == 7
            assert compile_errors["control"]["rate_pct"] == 71.43

            abandonment = _metric(window, "checkout_abandonment_rate")
            assert abandonment["kind"] == "guardrail"
            assert abandonment["treatment"]["rate_pct"] is None
            assert abandonment["control"]["rate_pct"] == 0.0
            assert {metric["key"] for metric in window["guardrails"]} == {
                "compile_error_rate",
                "checkout_abandonment_rate",
            }

        assert body["claim"]["causality"] == "descriptive_only"
        assert body["claim"]["preregistered_metric"] is None
        assert "No causal" not in body["claim"]["message"]
        assert "no causal claim" in body["claim"]["message"].lower()
        assert len(body["metric_definitions"]) == 6
        assert body["guardrail_metric_keys"] == [
            "compile_error_rate",
            "checkout_abandonment_rate",
        ]
        serialized = json.dumps(body).lower()
        assert "test_flag_exposure_" not in serialized
        assert "@example.com" not in serialized
        assert "anonymous_id" not in serialized
        assert "user_id" not in serialized

    async def test_small_groups_are_hidden_but_the_other_group_is_visible(
        self,
        client: AsyncClient,
        flag_seed: FlagSeed,
    ) -> None:
        _user_id, admin_headers = await flag_seed.user_headers(role="admin")
        for index in range(3):
            user_id = await flag_seed.user()
            await flag_seed.exposure(user_id, enabled=True)
            if index < 3:
                await flag_seed.resume(user_id, EXPOSURE_AT + timedelta(hours=1))
        for index in range(6):
            user_id = await flag_seed.user()
            await flag_seed.exposure(user_id, enabled=False)
            if index < 5:
                await flag_seed.resume(user_id, EXPOSURE_AT + timedelta(hours=1))

        body = await _report(client, admin_headers)
        for window in _flag(body)["windows"].values():
            treatment = window["groups"]["treatment"]
            control = window["groups"]["control"]
            assert treatment["suppressed"] is True
            assert treatment["sample_size"] is None
            assert treatment["exposure_events"] is None
            assert treatment["suppression_reason"] == "fewer_than_five_subjects"
            assert control["suppressed"] is False
            assert control["sample_size"] == 6

            activation = _metric(window, "activation")
            assert activation["treatment"]["suppressed"] is True
            assert activation["treatment"]["rate_pct"] is None
            assert activation["control"]["numerator"] == 5
            assert activation["control"]["rate_pct"] == 83.33
            assert activation["difference_pp"] is None

    async def test_report_is_admin_only_and_empty_state_is_well_formed(
        self,
        client: AsyncClient,
        flag_seed: FlagSeed,
    ) -> None:
        user_id, user_headers = await flag_seed.user_headers()
        assert user_id
        response = await client.get(REPORT, headers=user_headers)
        assert response.status_code == 403, response.text

        anonymous = await client.get(REPORT)
        assert anonymous.status_code in (401, 403), anonymous.text

        _admin_id, admin_headers = await flag_seed.user_headers(role="admin")
        body = await _report(client, admin_headers)
        assert body["windows"] == [7, 30]
        assert body["minimum_group_size"] == 5
        assert len(body["flags"]) == 6
        assert {flag["key"] for flag in body["flags"]} == {
            "trial_limits",
            "deep_analysis_trial",
            "compile_timeouts",
            "task_priority",
            "billing",
            "upgrade_ctas",
        }
        for flag in body["flags"]:
            assert set(flag["windows"]) == {"7", "30"}
            assert "activation" in {metric["key"] for metric in flag["windows"]["7"]["metrics"]}

    async def test_kill_switch_path_remains_audited(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        flag_seed: FlagSeed,
    ) -> None:
        _admin_id, admin_headers = await flag_seed.user_headers(role="admin")
        reason = f"test-flag-exposure-audit-{uuid.uuid4().hex}"
        baseline = await client.patch(
            "/admin/entitlements/kill-switch/cover_letters",
            headers=admin_headers,
            json={"enabled": True, "reason": f"{reason}-baseline"},
        )
        assert baseline.status_code == 200, baseline.text
        try:
            response = await client.patch(
                "/admin/entitlements/kill-switch/cover_letters",
                headers=admin_headers,
                json={"enabled": False, "reason": reason},
            )
            assert response.status_code == 200, response.text
        finally:
            await client.patch(
                "/admin/entitlements/kill-switch/cover_letters",
                headers=admin_headers,
                json={"enabled": True, "reason": f"{reason}-restore"},
            )

        row = (
            await db_session.execute(
                select(AdminAuditLog).where(
                    AdminAuditLog.action == "entitlement.kill_switch.update",
                    AdminAuditLog.target_id == "cover_letters",
                    AdminAuditLog.reason == reason,
                )
            )
        ).scalar_one_or_none()
        assert row is not None
        assert row.before_state == {"enabled": True}
        assert row.after_state == {"enabled": False}
