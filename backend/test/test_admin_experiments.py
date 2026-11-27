"""Pre-registered A/B experiments (issue #2158).

Covers registration immutability, consent-gated assignment and exposure dedupe,
five-user suppression, minimum-sample and no-peeking guards, aggregate lifts and
confidence, stop/revert without a flag change, RBAC, audit and privacy.
"""

from __future__ import annotations

import importlib.util
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    AdminAuditLog,
    AdminExperiment,
    AdminExperimentAssignment,
    AdminExperimentExposure,
)

CREATE = "/admin/experiments"
LIST = "/admin/experiments"
ASSIGN = "/analytics/experiments/assignment"
NOW = datetime.now(timezone.utc)
EXPOSURE_AT = (NOW - timedelta(days=3)).replace(hour=12, minute=0, second=0, microsecond=0)

FORBIDDEN_COLUMNS = {
    "email",
    "ip_address",
    "user_agent",
    "document",
    "prompt",
    "token",
    "provider_payload",
}


def _id(prefix: str = "test-experiment") -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


class ExperimentSeed:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.user_ids: list[str] = []
        self.anonymous_ids: set[str] = set()
        self.experiment_ids: list[str] = []

    async def user(self, *, role: str = "user") -> str:
        user_id = str(uuid.uuid4())
        await self.db.execute(
            text(
                "INSERT INTO users (id, email, name, role, email_verified, "
                "subscription_plan, subscription_status, trial_used, created_at) "
                "VALUES (:id, :email, 'Experiment User', :role, true, 'free', "
                "'active', false, :created)"
            ),
            {
                "id": user_id,
                "email": f"test_experiment_{user_id.replace('-', '')}@example.com",
                "role": role,
                "created": NOW,
            },
        )
        self.user_ids.append(user_id)
        await self.db.commit()
        return user_id

    async def headers(self, user_id: str) -> dict[str, str]:
        token = f"test_sess_experiment_{uuid.uuid4().hex}"
        await self.db.execute(
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
                        "event_id": _id("test-experiment-consent"),
                    }
                ),
                "created": created_at or NOW - timedelta(minutes=5),
            },
        )
        await self.db.commit()

    def payload(self, key: str, **overrides) -> dict:
        payload = {
            "key": key,
            "name": "Upgrade CTA copy",
            "hypothesis": (
                "A clearer call to action increases activation without raising "
                "the compile error rate."
            ),
            "primary_metric": "activation",
            "guardrail_metrics": ["compile_error_rate"],
            "variants": [
                {
                    "key": "control",
                    "label": "Current experience",
                    "weight": 50,
                    "flag_enabled": False,
                },
                {
                    "key": "treatment",
                    "label": "Clear call to action",
                    "weight": 50,
                    "flag_enabled": True,
                },
            ],
            "flag_key": None,
            "posthog_insight_url": "https://us.posthog.com/project/1/insights/abc",
            "minimum_sample_per_variant": 10,
            "reason": "Pre-register the quarterly CTA experiment",
            "confirm": True,
        }
        payload.update(overrides)
        return payload

    async def create(
        self,
        client: AsyncClient,
        headers: dict[str, str],
        *,
        key: str | None = None,
        **overrides,
    ) -> dict:
        experiment_key = key or f"test_exp_{uuid.uuid4().hex[:16]}"
        response = await client.post(
            CREATE,
            headers=headers,
            json=self.payload(experiment_key, **overrides),
        )
        assert response.status_code == 201, response.text
        body = response.json()
        self.experiment_ids.append(body["id"])
        return body

    async def start(
        self,
        client: AsyncClient,
        headers: dict[str, str],
        experiment_id: str,
        *,
        reason: str = "Start the pre-registered experiment",
    ) -> dict:
        response = await client.post(
            f"{CREATE}/{experiment_id}/start",
            headers=headers,
            json={"reason": reason, "confirm": True},
        )
        assert response.status_code == 200, response.text
        return response.json()

    async def stop(
        self,
        client: AsyncClient,
        headers: dict[str, str],
        experiment_id: str,
        *,
        reason: str = "Stop the experiment",
        revert: bool = True,
    ) -> dict:
        response = await client.post(
            f"{CREATE}/{experiment_id}/stop",
            headers=headers,
            json={
                "reason": reason,
                "confirm": True,
                "revert_assignments": revert,
            },
        )
        assert response.status_code == 200, response.text
        return response.json()

    async def backdate_start(self, experiment_id: str, started_at: datetime) -> None:
        await self.db.execute(
            text(
                "UPDATE admin_experiments SET started_at = :started WHERE id = :id"
            ),
            {"started": started_at, "id": experiment_id},
        )
        await self.db.commit()

    async def exposure_group(
        self,
        experiment_id: str,
        *,
        variant: str,
        count: int,
        exposed_at: datetime = EXPOSURE_AT,
        activation: int = 0,
        completed: int = 0,
        failed: int = 0,
    ) -> list[str]:
        users: list[str] = []
        for index in range(count):
            user_id = await self.user()
            users.append(user_id)
            assignment_id = str(uuid.uuid4())
            await self.db.execute(
                text(
                    "INSERT INTO admin_experiment_assignments "
                    "(id, experiment_id, user_id, variant, bucket, assigned_at) "
                    "VALUES (:id, :experiment, :user, :variant, :bucket, :assigned)"
                ),
                {
                    "id": assignment_id,
                    "experiment": experiment_id,
                    "user": user_id,
                    "variant": variant,
                    "bucket": index % 100,
                    "assigned": exposed_at,
                },
            )
            await self.db.execute(
                text(
                    "INSERT INTO admin_experiment_exposures "
                    "(id, experiment_id, assignment_id, user_id, variant, "
                    "window_date, source, exposed_at) "
                    "VALUES (:id, :experiment, :assignment, :user, :variant, "
                    ":window, 'first_party_experiment_evaluation', :exposed)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "experiment": experiment_id,
                    "assignment": assignment_id,
                    "user": user_id,
                    "variant": variant,
                    "window": exposed_at.date(),
                    "exposed": exposed_at,
                },
            )
            if index < activation:
                await self.db.execute(
                    text(
                        "INSERT INTO resumes (id, user_id, title, latex_content, "
                        "created_at, updated_at) "
                        "VALUES (:id, :uid, 'test experiment', 'test', :created, :created)"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "uid": user_id,
                        "created": exposed_at + timedelta(hours=1),
                    },
                )
            if index < completed:
                await self.db.execute(
                    text(
                        "INSERT INTO compilations (id, user_id, resume_id, job_id, "
                        "status, error_class, created_at) "
                        "VALUES (:id, :uid, NULL, :job, 'completed', 'unknown', :created)"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "uid": user_id,
                        "job": f"test_exp_job_{uuid.uuid4().hex}",
                        "created": exposed_at + timedelta(hours=2),
                    },
                )
            if index < failed:
                await self.db.execute(
                    text(
                        "INSERT INTO compilations (id, user_id, resume_id, job_id, "
                        "status, error_class, created_at) "
                        "VALUES (:id, :uid, NULL, :job, 'failed', 'timeout', :created)"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "uid": user_id,
                        "job": f"test_exp_job_{uuid.uuid4().hex}",
                        "created": exposed_at + timedelta(hours=3),
                    },
                )
        await self.db.commit()
        return users

    async def cleanup(self) -> None:
        if self.experiment_ids:
            await self.db.execute(
                text(
                    "DELETE FROM admin_experiments "
                    "WHERE id = ANY(CAST(:ids AS uuid[]))"
                ),
                {"ids": self.experiment_ids},
            )
        if self.user_ids:
            params = {"ids": self.user_ids}
            await self.db.execute(
                text("DELETE FROM compilations WHERE user_id = ANY(CAST(:ids AS uuid[]))"),
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
async def seed(db_session: AsyncSession):
    instance = ExperimentSeed(db_session)
    yield instance
    await instance.cleanup()


async def _admin_headers(seed: ExperimentSeed) -> tuple[str, dict[str, str]]:
    return await seed.user_headers(role="admin")


class TestPreregistration:
    async def test_registers_immutable_metrics_variants_and_hash(
        self, client: AsyncClient, seed: ExperimentSeed
    ) -> None:
        admin_id, admin_headers = await _admin_headers(seed)
        assert admin_id
        body = await seed.create(client, admin_headers)

        assert body["status"] == "preregistered"
        assert body["primary_metric"] == "activation"
        assert body["guardrail_metrics"] == ["compile_error_rate"]
        assert [variant["key"] for variant in body["variants"]] == [
            "control",
            "treatment",
        ]
        assert body["registration_intact"] is True
        assert len(body["registration_hash"]) == 64
        assert body["posthog_insight_url"] == "https://us.posthog.com/project/1/insights/abc"
        assert body["sample"]["sample_size"] == 0
        assert body["results_ready"] is False

        listed = await client.get(LIST, headers=admin_headers)
        assert listed.status_code == 200, listed.text
        listed_body = listed.json()
        assert listed_body["catalog"]["minimum_group_size"] == 5
        assert listed_body["catalog"]["claim"]["automatic_rollout"] is False
        match = next(
            experiment
            for experiment in listed_body["experiments"]
            if experiment["id"] == body["id"]
        )
        assert match["registration_hash"] == body["registration_hash"]

    async def test_rejects_duplicate_keys_and_invalid_preregistration(
        self, client: AsyncClient, seed: ExperimentSeed
    ) -> None:
        _admin_id, admin_headers = await _admin_headers(seed)
        created = await seed.create(client, admin_headers)

        duplicate = await client.post(
            CREATE,
            headers=admin_headers,
            json=seed.payload(created["key"]),
        )
        assert duplicate.status_code == 409, duplicate.text

        invalid_metric = await client.post(
            CREATE,
            headers=admin_headers,
            json=seed.payload(
                f"test_exp_{uuid.uuid4().hex[:16]}",
                primary_metric="revenue_forecast",
            ),
        )
        assert invalid_metric.status_code == 422, invalid_metric.text

        invalid_guardrail = await client.post(
            CREATE,
            headers=admin_headers,
            json=seed.payload(
                f"test_exp_{uuid.uuid4().hex[:16]}",
                guardrail_metrics=[],
            ),
        )
        assert invalid_guardrail.status_code == 422, invalid_guardrail.text

        missing_control = await client.post(
            CREATE,
            headers=admin_headers,
            json=seed.payload(
                f"test_exp_{uuid.uuid4().hex[:16]}",
                variants=[
                    {"key": "treatment", "label": "Treatment", "weight": 50},
                    {"key": "other", "label": "Other", "weight": 50},
                ],
            ),
        )
        assert missing_control.status_code == 422, missing_control.text

        bad_weight = await client.post(
            CREATE,
            headers=admin_headers,
            json=seed.payload(
                f"test_exp_{uuid.uuid4().hex[:16]}",
                variants=[
                    {"key": "control", "label": "Control", "weight": 80},
                    {"key": "treatment", "label": "Treatment", "weight": 80},
                ],
            ),
        )
        assert bad_weight.status_code == 422, bad_weight.text

        pii = await client.post(
            CREATE,
            headers=admin_headers,
            json=seed.payload(
                f"test_exp_{uuid.uuid4().hex[:16]}",
                hypothesis="Email person@example.com and ask them to click the clearer call to action.",
            ),
        )
        assert pii.status_code == 422, pii.text

        for bad_url in (
            "https://evil.example.com/project/1/insights/abc",
            "http://us.posthog.com/project/1/insights/abc",
            "https://us.posthog.com/project/1/insights/abc?token=secret",
        ):
            response = await client.post(
                CREATE,
                headers=admin_headers,
                json=seed.payload(
                    f"test_exp_{uuid.uuid4().hex[:16]}",
                    posthog_insight_url=bad_url,
                ),
            )
            assert response.status_code == 422, (bad_url, response.text)

        extra = await client.post(
            CREATE,
            headers=admin_headers,
            json={
                **seed.payload(f"test_exp_{uuid.uuid4().hex[:16]}"),
                "email": "person@example.com",
            },
        )
        assert extra.status_code == 422, extra.text

    async def test_database_trigger_blocks_preregistration_edits(
        self, client: AsyncClient, db_session: AsyncSession, seed: ExperimentSeed
    ) -> None:
        _admin_id, admin_headers = await _admin_headers(seed)
        created = await seed.create(client, admin_headers)

        for statement, params in (
            (
                "UPDATE admin_experiments SET hypothesis = :value WHERE id = :id",
                {"value": "A retrospective rewrite of the hypothesis that should fail.", "id": created["id"]},
            ),
            (
                "UPDATE admin_experiments SET minimum_sample_per_variant = 1 WHERE id = :id",
                {"id": created["id"]},
            ),
            (
                "UPDATE admin_experiments SET variants = CAST(:value AS JSONB) WHERE id = :id",
                {
                    "value": json.dumps(
                        [
                            {"key": "control", "label": "C", "weight": 100, "flag_enabled": False},
                            {"key": "other", "label": "O", "weight": 100, "flag_enabled": True},
                        ]
                    ),
                    "id": created["id"],
                },
            ),
        ):
            with pytest.raises(DBAPIError):
                await db_session.execute(text(statement), params)
                await db_session.commit()
            await db_session.rollback()

        stored = (
            await db_session.execute(
                select(AdminExperiment).where(AdminExperiment.id == created["id"])
            )
        ).scalar_one()
        assert stored.minimum_sample_per_variant == 10
        assert stored.registration_hash == created["registration_hash"]

    async def test_create_and_list_are_admin_only(
        self, client: AsyncClient, seed: ExperimentSeed
    ) -> None:
        _user_id, user_headers = await seed.user_headers()
        response = await client.post(
            CREATE,
            headers=user_headers,
            json=seed.payload(f"test_exp_{uuid.uuid4().hex[:16]}"),
        )
        assert response.status_code == 403, response.text
        assert (await client.get(LIST, headers=user_headers)).status_code == 403

        anonymous = await client.post(
            CREATE,
            json=seed.payload(f"test_exp_{uuid.uuid4().hex[:16]}"),
        )
        assert anonymous.status_code in (401, 403), anonymous.text
        anonymous_list = await client.get(LIST)
        assert anonymous_list.status_code in (401, 403), anonymous_list.text


class TestAssignmentAndExposure:
    async def test_requires_consent_and_dedupes_assignment_and_exposure(
        self, client: AsyncClient, db_session: AsyncSession, seed: ExperimentSeed
    ) -> None:
        _admin_id, admin_headers = await _admin_headers(seed)
        experiment = await seed.create(client, admin_headers)
        await seed.start(client, admin_headers, experiment["id"])
        user_id, user_headers = await seed.user_headers()
        anonymous_id = _id("test-experiment-anon")
        payload = {"anonymous_id": anonymous_id, "experiment_keys": [experiment["key"]]}

        denied = await client.post(ASSIGN, headers=user_headers, json=payload)
        assert denied.status_code == 403, denied.text
        await seed.consent(anonymous_id, decision="denied")
        denied_again = await client.post(ASSIGN, headers=user_headers, json=payload)
        assert denied_again.status_code == 403, denied_again.text

        await seed.consent(anonymous_id, created_at=NOW - timedelta(minutes=4))
        first = await client.post(ASSIGN, headers=user_headers, json=payload)
        assert first.status_code == 202, first.text
        first_body = first.json()
        assert first_body["accepted"] == 1
        assert first_body["duplicate"] == 0
        assert len(first_body["assignments"]) == 1
        assignment = first_body["assignments"][0]
        assert assignment["experiment_key"] == experiment["key"]
        assert assignment["variant"] in {"control", "treatment"}
        assert assignment["exposure_recorded"] is True
        assert assignment["flag_key"] is None
        assert assignment["flag_override"] is None

        second = await client.post(ASSIGN, headers=user_headers, json=payload)
        assert second.status_code == 202, second.text
        second_body = second.json()
        assert second_body["accepted"] == 0
        assert second_body["duplicate"] == 1
        assert second_body["assignments"][0]["variant"] == assignment["variant"]
        assert second_body["assignments"][0]["exposure_recorded"] is False

        assignment_count = (
            await db_session.execute(
                text(
                    "SELECT count(*) FROM admin_experiment_assignments "
                    "WHERE experiment_id = :experiment AND user_id = :user"
                ),
                {"experiment": experiment["id"], "user": user_id},
            )
        ).scalar_one()
        exposure_count = (
            await db_session.execute(
                text(
                    "SELECT count(*) FROM admin_experiment_exposures "
                    "WHERE experiment_id = :experiment AND user_id = :user"
                ),
                {"experiment": experiment["id"], "user": user_id},
            )
        ).scalar_one()
        assert assignment_count == 1
        assert exposure_count == 1

        row = (
            await db_session.execute(
                select(AdminExperimentExposure).where(
                    AdminExperimentExposure.experiment_id == experiment["id"]
                )
            )
        ).scalar_one()
        assert row.source == "first_party_experiment_evaluation"
        assert row.variant == assignment["variant"]
        serialized = json.dumps(
            {
                "variant": row.variant,
                "source": row.source,
                "window": row.window_date.isoformat(),
            }
        )
        assert anonymous_id not in serialized
        assert "@" not in serialized

        await seed.consent(
            anonymous_id,
            decision="withdrawn",
            created_at=NOW + timedelta(minutes=1),
        )
        withdrawn = await client.post(ASSIGN, headers=user_headers, json=payload)
        assert withdrawn.status_code == 403, withdrawn.text
        unchanged = (
            await db_session.execute(
                text(
                    "SELECT count(*) FROM admin_experiment_exposures "
                    "WHERE experiment_id = :experiment"
                ),
                {"experiment": experiment["id"]},
            )
        ).scalar_one()
        assert unchanged == 1

    async def test_rejects_unknown_fields_keys_and_unauthenticated_callers(
        self, client: AsyncClient, seed: ExperimentSeed
    ) -> None:
        _admin_id, admin_headers = await _admin_headers(seed)
        experiment = await seed.create(client, admin_headers)
        await seed.start(client, admin_headers, experiment["id"])
        _user_id, user_headers = await seed.user_headers()
        anonymous_id = _id("test-experiment-anon")
        await seed.consent(anonymous_id)

        extra = await client.post(
            ASSIGN,
            headers=user_headers,
            json={
                "anonymous_id": anonymous_id,
                "experiment_keys": [experiment["key"]],
                "email": "person@example.com",
            },
        )
        assert extra.status_code == 422, extra.text

        unknown = await client.post(
            ASSIGN,
            headers=user_headers,
            json={
                "anonymous_id": anonymous_id,
                "experiment_keys": [experiment["key"], "not_a_real_experiment"],
            },
        )
        assert unknown.status_code == 202, unknown.text
        unknown_body = unknown.json()
        assert unknown_body["rejected"] == 1
        assert len(unknown_body["assignments"]) == 1

        invalid_id = await client.post(
            ASSIGN,
            headers=user_headers,
            json={"anonymous_id": "has spaces", "experiment_keys": [experiment["key"]]},
        )
        assert invalid_id.status_code == 422, invalid_id.text

        anonymous = await client.post(
            ASSIGN,
            json={"anonymous_id": anonymous_id, "experiment_keys": [experiment["key"]]},
        )
        assert anonymous.status_code in (401, 403), anonymous.text

    async def test_disabled_linked_flag_skips_assignment_and_never_rolls_out(
        self, client: AsyncClient, db_session: AsyncSession, seed: ExperimentSeed
    ) -> None:
        _admin_id, admin_headers = await _admin_headers(seed)
        baseline = await client.get("/admin/feature-flags", headers=admin_headers)
        assert baseline.status_code == 200, baseline.text
        original = next(
            flag for flag in baseline.json() if flag["key"] == "upgrade_ctas"
        )["enabled"]

        reason = f"test-experiment-flag-{uuid.uuid4().hex}"
        try:
            disabled = await client.patch(
                "/admin/feature-flags/upgrade_ctas",
                headers=admin_headers,
                json={"enabled": False, "reason": reason},
            )
            assert disabled.status_code == 200, disabled.text

            experiment = await seed.create(
                client,
                admin_headers,
                flag_key="upgrade_ctas",
            )
            await seed.start(client, admin_headers, experiment["id"])
            _user_id, user_headers = await seed.user_headers()
            anonymous_id = _id("test-experiment-anon")
            await seed.consent(anonymous_id)

            skipped = await client.post(
                ASSIGN,
                headers=user_headers,
                json={
                    "anonymous_id": anonymous_id,
                    "experiment_keys": [experiment["key"]],
                },
            )
            assert skipped.status_code == 202, skipped.text
            assert skipped.json()["assignments"] == []
            assert skipped.json()["skipped"] == 1
            count = (
                await db_session.execute(
                    text(
                        "SELECT count(*) FROM admin_experiment_assignments "
                        "WHERE experiment_id = :experiment"
                    ),
                    {"experiment": experiment["id"]},
                )
            ).scalar_one()
            assert count == 0

            # Re-enable the flag and then prove an assigned variant only changes
            # the response override, never the persisted operational flag.
            restored = await client.patch(
                "/admin/feature-flags/upgrade_ctas",
                headers=admin_headers,
                json={"enabled": True, "reason": f"{reason}-restore"},
            )
            assert restored.status_code == 200, restored.text
            running = await client.post(
                ASSIGN,
                headers=user_headers,
                json={
                    "anonymous_id": anonymous_id,
                    "experiment_keys": [experiment["key"]],
                },
            )
            assert running.status_code == 202, running.text
            body = running.json()
            assert len(body["assignments"]) == 1
            assigned = body["assignments"][0]
            assert assigned["flag_key"] == "upgrade_ctas"
            assert assigned["flag_override"] is (
                assigned["variant"] == "treatment"
            )

            after = await client.get("/admin/feature-flags", headers=admin_headers)
            assert after.status_code == 200, after.text
            assert next(
                flag for flag in after.json() if flag["key"] == "upgrade_ctas"
            )["enabled"] is True
        finally:
            await client.patch(
                "/admin/feature-flags/upgrade_ctas",
                headers=admin_headers,
                json={
                    "enabled": original,
                    "reason": f"{reason}-cleanup",
                },
            )


class TestResults:
    async def _ready_experiment(
        self,
        client: AsyncClient,
        seed: ExperimentSeed,
        *,
        minimum_sample: int = 10,
    ) -> tuple[dict, dict[str, str]]:
        _admin_id, admin_headers = await _admin_headers(seed)
        experiment = await seed.create(
            client,
            admin_headers,
            minimum_sample_per_variant=minimum_sample,
        )
        await seed.start(client, admin_headers, experiment["id"])
        await seed.backdate_start(
            experiment["id"], EXPOSURE_AT - timedelta(hours=1)
        )
        return experiment, admin_headers

    async def test_publishes_aggregate_lifts_confidence_and_guardrails(
        self, client: AsyncClient, seed: ExperimentSeed
    ) -> None:
        experiment, admin_headers = await self._ready_experiment(client, seed)
        await seed.exposure_group(
            experiment["id"],
            variant="control",
            count=10,
            activation=5,
            completed=10,
            failed=6,
        )
        await seed.exposure_group(
            experiment["id"],
            variant="treatment",
            count=10,
            activation=9,
            completed=10,
            failed=5,
        )

        response = await client.get(
            f"{CREATE}/{experiment['id']}/results", headers=admin_headers
        )
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["ready"] is True
        assert body["sample"]["minimum_sample_met"] is True
        assert body["sample"]["sample_size"] == 20
        assert {variant["variant"]: variant["sample_size"] for variant in body["sample"]["variants"]} == {
            "control": 10,
            "treatment": 10,
        }

        primary = body["primary_metric"]
        assert primary["key"] == "activation"
        assert primary["cells"]["control"]["rate_pct"] == 50.0
        assert primary["cells"]["treatment"]["rate_pct"] == 90.0
        comparison = primary["comparisons"][0]
        assert comparison["variant"] == "treatment"
        assert comparison["lift_pp"] == 40.0
        assert comparison["relative_lift_pct"] == 80.0
        assert comparison["ci_low_pp"] is not None
        assert comparison["ci_high_pp"] is not None
        assert comparison["ci_low_pp"] < comparison["lift_pp"] < comparison["ci_high_pp"]
        assert comparison["confidence_level"] == 0.95

        guardrail = body["guardrails"][0]
        assert guardrail["key"] == "compile_error_rate"
        assert guardrail["cells"]["control"]["rate_pct"] == 60.0
        assert guardrail["cells"]["treatment"]["rate_pct"] == 50.0
        assert guardrail["comparisons"][0]["lift_pp"] == -10.0
        assert guardrail["direction"] == "down"

        claim = body["claim"]
        assert claim["automatic_rollout"] is False
        assert claim["policy"] == "fixed_horizon_preregistered_metric"
        assert "minimum sample" in claim["peeking"].lower()
        assert "never rolled out automatically" in claim["winner"].lower()

        serialized = json.dumps(body).lower()
        assert "test_experiment_" not in serialized
        assert "@example.com" not in serialized
        assert "anonymous_id" not in serialized
        assert "assignment_id" not in serialized
        assert "user_id" not in serialized

    async def test_minimum_sample_guard_hides_lifts_before_readiness(
        self, client: AsyncClient, seed: ExperimentSeed
    ) -> None:
        experiment, admin_headers = await self._ready_experiment(
            client, seed, minimum_sample=20
        )
        await seed.exposure_group(
            experiment["id"], variant="control", count=10, activation=2, completed=10
        )
        await seed.exposure_group(
            experiment["id"], variant="treatment", count=10, activation=8, completed=10
        )

        body = (
            await client.get(
                f"{CREATE}/{experiment['id']}/results", headers=admin_headers
            )
        ).json()
        assert body["ready"] is False
        assert body["sample"]["minimum_sample_met"] is False
        assert body["sample"]["sample_size"] == 20
        comparison = body["primary_metric"]["comparisons"][0]
        assert comparison["lift_pp"] is None
        assert comparison["ci_low_pp"] is None
        assert "minimum sample" in body["message"].lower()

    async def test_five_user_suppression_hides_small_variant_samples(
        self, client: AsyncClient, seed: ExperimentSeed
    ) -> None:
        experiment, admin_headers = await self._ready_experiment(
            client, seed, minimum_sample=10
        )
        await seed.exposure_group(
            experiment["id"], variant="control", count=3, activation=1, completed=3
        )
        await seed.exposure_group(
            experiment["id"], variant="treatment", count=3, activation=3, completed=3
        )

        body = (
            await client.get(
                f"{CREATE}/{experiment['id']}/results", headers=admin_headers
            )
        ).json()
        assert body["sample"]["suppressed"] is True
        assert body["sample"]["sample_size"] is None
        for variant in body["sample"]["variants"]:
            assert variant["suppressed"] is True
            assert variant["sample_size"] is None
        primary = body["primary_metric"]
        assert primary["ready"] is False
        assert primary["cells"]["control"]["rate_pct"] is None
        assert primary["cells"]["treatment"]["rate_pct"] is None
        assert primary["comparisons"][0]["lift_pp"] is None

    async def test_preregistered_experiment_has_no_results(
        self, client: AsyncClient, seed: ExperimentSeed
    ) -> None:
        _admin_id, admin_headers = await _admin_headers(seed)
        experiment = await seed.create(client, admin_headers)
        body = (
            await client.get(
                f"{CREATE}/{experiment['id']}/results", headers=admin_headers
            )
        ).json()
        assert body["ready"] is False
        assert body["experiment"]["status"] == "preregistered"
        assert "not started" in body["message"].lower()
        assert body["primary_metric"]["cells"]["control"]["rate_pct"] is None

    async def test_stop_reverts_assignments_keeps_results_and_does_not_touch_flags(
        self, client: AsyncClient, db_session: AsyncSession, seed: ExperimentSeed
    ) -> None:
        experiment, admin_headers = await self._ready_experiment(client, seed)
        _user_id, user_headers = await seed.user_headers()
        anonymous_id = _id("test-experiment-anon")
        await seed.consent(anonymous_id)

        assigned = await client.post(
            ASSIGN,
            headers=user_headers,
            json={
                "anonymous_id": anonymous_id,
                "experiment_keys": [experiment["key"]],
            },
        )
        assert assigned.status_code == 202, assigned.text
        assert len(assigned.json()["assignments"]) == 1

        baseline = await client.get("/admin/feature-flags", headers=admin_headers)
        flags_before = {
            flag["key"]: flag["enabled"] for flag in baseline.json()
        }

        stopped = await seed.stop(
            client,
            admin_headers,
            experiment["id"],
            reason="Stop after the planned enrollment window",
            revert=True,
        )
        assert stopped["status"] == "stopped"
        assert stopped["reverted_assignments"] == 1

        rows = (
            await db_session.execute(
                select(AdminExperimentAssignment).where(
                    AdminExperimentAssignment.experiment_id == experiment["id"]
                )
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].reverted_at is not None

        after_assignment = await client.post(
            ASSIGN,
            headers=user_headers,
            json={
                "anonymous_id": anonymous_id,
                "experiment_keys": [experiment["key"]],
            },
        )
        assert after_assignment.status_code == 202, after_assignment.text
        assert after_assignment.json()["assignments"] == []
        assert after_assignment.json()["skipped"] == 1

        results = await client.get(
            f"{CREATE}/{experiment['id']}/results", headers=admin_headers
        )
        assert results.status_code == 200, results.text
        assert results.json()["experiment"]["status"] == "stopped"

        flags_after = await client.get("/admin/feature-flags", headers=admin_headers)
        assert {
            flag["key"]: flag["enabled"] for flag in flags_after.json()
        } == flags_before

        audits = (
            await db_session.execute(
                select(AdminAuditLog.action).where(
                    AdminAuditLog.target_id == experiment["id"]
                )
            )
        ).scalars().all()
        assert "admin.experiment.create" in audits
        assert "admin.experiment.start" in audits
        assert "admin.experiment.stop" in audits

    async def test_explicit_revert_requires_a_stopped_experiment(
        self, client: AsyncClient, db_session: AsyncSession, seed: ExperimentSeed
    ) -> None:
        experiment, admin_headers = await self._ready_experiment(client, seed)
        _user_id, user_headers = await seed.user_headers()
        anonymous_id = _id("test-experiment-anon")
        await seed.consent(anonymous_id)
        assigned = await client.post(
            ASSIGN,
            headers=user_headers,
            json={
                "anonymous_id": anonymous_id,
                "experiment_keys": [experiment["key"]],
            },
        )
        assert assigned.status_code == 202, assigned.text

        before_stop = await client.post(
            f"{CREATE}/{experiment['id']}/revert",
            headers=admin_headers,
            json={"reason": "Revert before stopping", "confirm": True},
        )
        assert before_stop.status_code == 409, before_stop.text

        stopped = await seed.stop(
            client,
            admin_headers,
            experiment["id"],
            reason="Stop without reverting",
            revert=False,
        )
        assert stopped["reverted_assignments"] == 0
        open_rows = (
            await db_session.execute(
                select(AdminExperimentAssignment).where(
                    AdminExperimentAssignment.experiment_id == experiment["id"]
                )
            )
        ).scalars().all()
        assert len(open_rows) == 1
        assert open_rows[0].reverted_at is None

        reverted = await client.post(
            f"{CREATE}/{experiment['id']}/revert",
            headers=admin_headers,
            json={"reason": "Revert remaining assignments", "confirm": True},
        )
        assert reverted.status_code == 200, reverted.text
        assert reverted.json()["reverted_assignments"] == 1

        refreshed = await db_session.execute(
            select(AdminExperimentAssignment).where(
                AdminExperimentAssignment.experiment_id == experiment["id"]
            )
        )
        assert refreshed.scalar_one().reverted_at is not None
        detail = await client.get(
            f"{CREATE}/{experiment['id']}", headers=admin_headers
        )
        assert detail.status_code == 200, detail.text
        assert detail.json()["status"] == "stopped"

    async def test_start_and_stop_require_confirmation_and_valid_state(
        self, client: AsyncClient, seed: ExperimentSeed
    ) -> None:
        _admin_id, admin_headers = await _admin_headers(seed)
        experiment = await seed.create(client, admin_headers)

        no_confirm = await client.post(
            f"{CREATE}/{experiment['id']}/start",
            headers=admin_headers,
            json={"reason": "Start without confirmation"},
        )
        assert no_confirm.status_code == 422, no_confirm.text

        missing_reason = await client.post(
            f"{CREATE}/{experiment['id']}/start",
            headers=admin_headers,
            json={"confirm": True},
        )
        assert missing_reason.status_code == 422, missing_reason.text

        await seed.start(client, admin_headers, experiment["id"])
        restart = await client.post(
            f"{CREATE}/{experiment['id']}/start",
            headers=admin_headers,
            json={"reason": "Attempt a second start", "confirm": True},
        )
        assert restart.status_code == 409, restart.text

        await seed.stop(client, admin_headers, experiment["id"])
        restart_stopped = await client.post(
            f"{CREATE}/{experiment['id']}/start",
            headers=admin_headers,
            json={"reason": "Attempt to restart a stopped experiment", "confirm": True},
        )
        assert restart_stopped.status_code == 409, restart_stopped.text
        stop_again = await client.post(
            f"{CREATE}/{experiment['id']}/stop",
            headers=admin_headers,
            json={"reason": "Stop a stopped experiment", "confirm": True},
        )
        assert stop_again.status_code == 409, stop_again.text

    async def test_results_and_lifecycle_are_admin_only(
        self, client: AsyncClient, seed: ExperimentSeed
    ) -> None:
        _admin_id, admin_headers = await _admin_headers(seed)
        experiment = await seed.create(client, admin_headers)
        _user_id, user_headers = await seed.user_headers()

        assert (
            await client.get(
                f"{CREATE}/{experiment['id']}/results", headers=user_headers
            )
        ).status_code == 403
        assert (
            await client.post(
                f"{CREATE}/{experiment['id']}/start",
                headers=user_headers,
                json={"reason": "A user cannot start this", "confirm": True},
            )
        ).status_code == 403
        assert (
            await client.get(
                f"{CREATE}/{experiment['id']}/results"
            )
        ).status_code in (401, 403)


class TestPrivacyAndMigration:
    async def test_experiment_tables_contain_no_direct_identifier_columns(
        self, db_session: AsyncSession
    ) -> None:
        result = (
            await db_session.execute(
                text(
                    "SELECT table_name, column_name FROM information_schema.columns "
                    "WHERE table_name IN ('admin_experiments', "
                    "'admin_experiment_assignments', 'admin_experiment_exposures')"
                )
            )
        ).all()
        assert result
        names = {column for _table, column in result}
        assert names.isdisjoint(FORBIDDEN_COLUMNS)
        assert {"ip_address", "user_agent", "email"}.isdisjoint(names)

    def test_migration_uses_the_assigned_revision_and_previous_head(self) -> None:
        path = (
            Path(__file__).parents[1]
            / "alembic/versions/0106_admin_experiments.py"
        )
        spec = importlib.util.spec_from_file_location("experiment_migration", path)
        assert spec and spec.loader
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        assert migration.revision == "0106_admin_experiments"
        assert migration.down_revision == "0104_refund_requests"

    def test_models_expose_aggregate_safe_state(self) -> None:
        assert "ip_address" not in AdminExperimentExposure.__table__.c
        assert "user_agent" not in AdminExperimentExposure.__table__.c
        assert "email" not in AdminExperiment.__table__.c
        assert AdminExperimentExposure.__table__.c.source.default.arg == (
            "first_party_experiment_evaluation"
        )
