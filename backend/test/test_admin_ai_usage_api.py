"""Admin AI usage breakdown: reconciliation, filters, outcomes, privacy."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, time, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.resume_engine.credential_scope import credential_scope

SECRET_JD = "private jd marker 2087"
SECRET_LATEX = "private latex marker 2087"
SECRET_KEY = "private token marker 2087"


@pytest.fixture(autouse=True)
async def _isolate_ai_usage_sources(db_session: AsyncSession):
    """Keep the shared test database's older analytics rows out of these assertions."""
    await db_session.execute(text("DELETE FROM resume_optimization_stages"))
    await db_session.execute(text("DELETE FROM resume_optimization_runs"))
    await db_session.execute(text("DELETE FROM optimizations"))
    await db_session.commit()
    yield


async def _create_user(
    db: AsyncSession,
    *,
    role: str = "user",
    plan: str = "pro",
) -> tuple[str, str]:
    user_id = str(uuid.uuid4())
    email = f"test_ai_usage_{user_id.replace('-', '')}@example.com"
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, 'Usage User', :role, true, :plan, 'active', false)"
        ),
        {"id": user_id, "email": email, "role": role, "plan": plan},
    )
    await db.commit()
    return user_id, email


async def _session_headers(db: AsyncSession, user_id: str) -> dict[str, str]:
    token = f"test_sess_ai_usage_{uuid.uuid4().hex}"
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
    user_id, _ = await _create_user(db, role="admin")
    return await _session_headers(db, user_id)


async def _create_resume(
    db: AsyncSession,
    *,
    user_id: str,
    persona: str | None = "startup",
    extra_metadata: dict | None = None,
) -> str:
    resume_id = str(uuid.uuid4())
    metadata = dict(extra_metadata or {})
    if persona:
        metadata["last_persona"] = persona
    await db.execute(
        text(
            "INSERT INTO resumes (id, user_id, title, latex_content, metadata, created_at) "
            "VALUES (:id, :uid, 'Usage Resume', :latex, CAST(:metadata AS jsonb), :created)"
        ),
        {
            "id": resume_id,
            "uid": user_id,
            "latex": SECRET_LATEX,
            "metadata": json.dumps(metadata),
            "created": datetime.now(timezone.utc) - timedelta(days=2),
        },
    )
    await db.commit()
    return resume_id


async def _seed_optimization(
    db: AsyncSession,
    *,
    user_id: str,
    resume_id: str,
    created_at: datetime,
    provider: str = "openai",
    model: str = "gpt-4o-mini",
    tokens: int = 1_000,
    latency_seconds: float = 1.5,
) -> str:
    optimization_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO optimizations (id, user_id, resume_id, job_description, "
            "original_latex, optimized_latex, provider, model, tokens_used, "
            "optimization_time, created_at) "
            "VALUES (:id, :uid, :resume, :jd, :original, :optimized, :provider, :model, "
            ":tokens, :latency, :created)"
        ),
        {
            "id": optimization_id,
            "uid": user_id,
            "resume": resume_id,
            "jd": SECRET_JD,
            "original": SECRET_LATEX,
            "optimized": SECRET_LATEX,
            "provider": provider,
            "model": model,
            "tokens": tokens,
            "latency": latency_seconds,
            "created": created_at,
        },
    )
    await db.commit()
    return optimization_id


async def _seed_stage(
    db: AsyncSession,
    *,
    user_id: str,
    resume_id: str,
    stage_key: str,
    created_at: datetime,
    status: str = "completed",
    completed_at: datetime | None = None,
    usage: dict | None = None,
    provider: str = "openai",
    model: str = "gpt-4o-mini",
    credential_scope_value: str = "platform",
    run_persona: str | None = None,
    run_status: str = "completed",
) -> str:
    job_id = f"test_usage_job_{uuid.uuid4().hex}"
    await db.execute(
        text(
            "INSERT INTO job_finalizations "
            "(id, job_id, user_id, job_type, resume_id, state, owner_epoch, expires_at, created_at) "
            "VALUES (:id, :job_id, :uid, 'llm_optimization', :resume, 'completed', 1, :expires, :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "job_id": job_id,
            "uid": user_id,
            "resume": resume_id,
            "expires": created_at + timedelta(days=7),
            "created": created_at,
        },
    )
    run_id = f"test_usage_run_{uuid.uuid4().hex}"
    context = {"direction": {"persona": run_persona}} if run_persona else {}
    context["private_note"] = SECRET_KEY
    await db.execute(
        text(
            "INSERT INTO resume_optimization_runs "
            "(id, job_id, resume_id, user_id, base_revision, source_sha256, context_hash, "
            "effort, provider, model, credential_scope, status, snapshot, context_payload, "
            "budget, decisions, expires_at, created_at, updated_at) "
            "VALUES (:id, :job_id, :resume, :uid, 1, :sha, :sha, 'standard', :provider, :model, "
            ":scope, :run_status, '{}'::jsonb, CAST(:context AS jsonb), '{}'::jsonb, '{}'::jsonb, "
            ":expires, :created, :updated)"
        ),
        {
            "id": run_id,
            "job_id": job_id,
            "resume": resume_id,
            "uid": user_id,
            "sha": "a" * 64,
            "provider": provider,
            "model": model,
            "scope": credential_scope_value,
            "run_status": run_status,
            "context": json.dumps(context),
            "expires": created_at + timedelta(days=7),
            "created": created_at,
            "updated": completed_at or created_at,
        },
    )
    if usage is None:
        usage = {"input_tokens": 600, "output_tokens": 400, "cost_usd": 0.12}
    await db.execute(
        text(
            "INSERT INTO resume_optimization_stages "
            "(run_id, stage_key, input_hash, status, owner_token, owner_epoch, "
            "reserved_usage, usage, output, output_hash, created_at, completed_at) "
            "VALUES (:run_id, :stage_key, :sha, :status, :owner, 1, "
            "CAST(:reserved AS jsonb), CAST(:usage AS jsonb), '{}'::jsonb, :sha, :created, :completed)"
        ),
        {
            "run_id": run_id,
            "stage_key": stage_key,
            "sha": "b" * 64,
            "status": status,
            "owner": f"test_owner_{uuid.uuid4().hex}",
            "reserved": json.dumps({"input_tokens": 0, "output_tokens": 0, "cost_usd": 0}),
            "usage": json.dumps(usage),
            "created": created_at,
            "completed": completed_at,
        },
    )
    await db.commit()
    return run_id


async def _usage(
    client: AsyncClient,
    headers: dict[str, str],
    **params,
) -> dict:
    response = await client.get("/admin/analytics/ai-usage", params={"days": 30, **params}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


class TestAiUsageReconciliation:
    async def test_reconciles_sources_and_preserves_outcomes(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_headers = await _admin_headers(db_session)
        now = datetime.now(timezone.utc)
        users: list[str] = []
        for index in range(5):
            user_id, _ = await _create_user(db_session, plan="pro")
            resume_id = await _create_resume(db_session, user_id=user_id, persona="startup")
            await _seed_optimization(
                db_session,
                user_id=user_id,
                resume_id=resume_id,
                created_at=now - timedelta(hours=6 + index),
            )
            await _seed_stage(
                db_session,
                user_id=user_id,
                resume_id=resume_id,
                stage_key="patches.0",
                created_at=now - timedelta(hours=4 + index),
                completed_at=now - timedelta(hours=4 + index) + timedelta(seconds=2),
                run_persona="startup",
            )
            users.append(user_id)

        # One failed stage/run must be visible as an error without hiding the rest.
        failed_resume_id = await _create_resume(db_session, user_id=users[0], persona="startup")
        await _seed_stage(
            db_session,
            user_id=users[0],
            resume_id=failed_resume_id,
            stage_key="requirements",
            created_at=now - timedelta(hours=2),
            completed_at=now - timedelta(hours=2) + timedelta(seconds=1),
            status="failed",
            usage={"input_tokens": 100, "output_tokens": 0, "cost_usd": 0},
            run_persona="startup",
            run_status="failed",
        )

        body = await _usage(client, admin_headers)
        assert body["period_days"] == 30
        assert body["minimum_group_size"] == 5
        assert body["filters"] == {
            "plan": None,
            "feature": None,
            "provider": None,
            "model": None,
            "persona": None,
        }

        totals = body["totals"]
        assert totals["runs"] == 11
        assert totals["successes"] == 10
        assert totals["errors"] == 1
        assert totals["pending"] == 0
        assert totals["users"] == 5
        assert totals["tokens"] == 5 * 1_000 + 5 * 1_000 + 100
        assert totals["latency_samples"] == 11
        assert totals["latency_p50_ms"] is not None
        assert totals["latency_p95_ms"] is not None
        assert totals["latency_p95_ms"] >= totals["latency_p50_ms"]
        assert totals["credential_sources"] == {"platform": 6, "unknown": 5}

        start = datetime.combine(
            datetime.fromisoformat(body["start_date"]).date(), time.min, tzinfo=timezone.utc
        )
        end = datetime.combine(
            datetime.fromisoformat(body["end_date"]).date() + timedelta(days=1),
            time.min,
            tzinfo=timezone.utc,
        )
        optimization_count = (
            await db_session.execute(
                text(
                    "SELECT count(*), coalesce(sum(tokens_used), 0) FROM optimizations "
                    "WHERE created_at >= :start AND created_at < :end "
                    "AND coalesce(is_auto_save, false) = false "
                    "AND coalesce(is_checkpoint, false) = false"
                ),
                {"start": start, "end": end},
            )
        ).one()
        stage_count = (
            await db_session.execute(
                text(
                    "SELECT count(*) FROM resume_optimization_stages "
                    "WHERE coalesce(completed_at, created_at) >= :start "
                    "AND coalesce(completed_at, created_at) < :end"
                ),
                {"start": start, "end": end},
            )
        ).scalar_one()
        sources = {row["source"]: row for row in body["reconciliation"]["sources"]}
        assert sources["optimizations"]["runs"] == optimization_count[0]
        assert sources["optimizations"]["tokens"] == optimization_count[1]
        assert sources["resume_optimization_stages"]["runs"] == stage_count
        assert body["reconciliation"]["total_events"] == totals["runs"]
        assert body["reconciliation"]["total_successes"] == totals["successes"]
        assert body["reconciliation"]["total_errors"] == totals["errors"]
        assert body["reconciliation"]["resume_engine_runs"]["runs"] == 6
        assert body["reconciliation"]["resume_engine_runs"]["successes"] == 5
        assert body["reconciliation"]["resume_engine_runs"]["errors"] == 1
        assert body["reconciliation"]["resume_engine_runs"]["latency_samples"] == 6

        assert any(row["feature"] == "resume_optimization" for row in body["by_feature"])
        assert any(row["feature"] == "optimization_patches" for row in body["by_feature"])
        assert any(row["provider"] == "openai" for row in body["by_provider"])
        assert any(row["model"] == "gpt-4o-mini" for row in body["by_model"])
        assert any(row["persona"] == "startup" for row in body["by_persona"])
        assert any(row["credential_source"] == "platform" for row in body["by_credential_source"])
        assert any(row["credential_source"] == "unknown" for row in body["by_credential_source"])
        assert body["reconciliation"]["resume_engine_runs"]["by_status"] == {
            "completed": 5,
            "failed": 1,
        }


class TestAiUsageFilters:
    async def test_each_dimension_filter(self, client: AsyncClient, db_session: AsyncSession):
        admin_headers = await _admin_headers(db_session)
        now = datetime.now(timezone.utc)
        groups = [
            {
                "plan": "pro",
                "provider": "openai",
                "model": "gpt-4o",
                "persona": "startup",
                "stage_key": "patches.0",
                "feature": "optimization_patches",
            },
            {
                "plan": "team",
                "provider": "anthropic",
                "model": "claude-3-5-sonnet",
                "persona": "fintech",
                "stage_key": "requirements.global",
                "feature": "requirements",
            },
        ]
        for group in groups:
            for index in range(5):
                user_id, _ = await _create_user(db_session, plan=group["plan"])
                resume_id = await _create_resume(db_session, user_id=user_id, persona=group["persona"])
                await _seed_optimization(
                    db_session,
                    user_id=user_id,
                    resume_id=resume_id,
                    created_at=now - timedelta(hours=10 + index),
                    provider=group["provider"],
                    model=group["model"],
                )
                await _seed_stage(
                    db_session,
                    user_id=user_id,
                    resume_id=resume_id,
                    stage_key=group["stage_key"],
                    created_at=now - timedelta(hours=5 + index),
                    completed_at=now - timedelta(hours=5 + index) + timedelta(seconds=2),
                    provider=group["provider"],
                    model=group["model"],
                    run_persona=group["persona"],
                )

        base = await _usage(client, admin_headers)
        assert base["totals"]["runs"] == 20

        cases = [
            ("plan", "pro", 10, "by_plan", "plan"),
            ("plan", "team", 10, "by_plan", "plan"),
            ("feature", "optimization_patches", 5, "by_feature", "feature"),
            ("feature", "resume_optimization", 10, "by_feature", "feature"),
            ("provider", "OpenAI", 10, "by_provider", "provider"),
            ("provider", "anthropic", 10, "by_provider", "provider"),
            ("model", "gpt-4o", 10, "by_model", "model"),
            ("model", "claude-3-5-sonnet", 10, "by_model", "model"),
            ("persona", "startup", 10, "by_persona", "persona"),
            ("persona", "fintech", 10, "by_persona", "persona"),
        ]
        for dimension, value, expected_runs, rows_key, row_field in cases:
            body = await _usage(client, admin_headers, **{dimension: value})
            assert body["totals"]["runs"] == expected_runs, (dimension, value, body["totals"])
            assert body["filters"][dimension] == value.lower()
            assert body[rows_key], (dimension, value)
            assert all(row[row_field] == value.lower() for row in body[rows_key]), (
                dimension,
                value,
                body[rows_key],
            )
            assert body["suppressed_groups"] == 0

        combined = await _usage(
            client,
            admin_headers,
            plan="pro",
            feature="resume_optimization",
            provider="openai",
            model="gpt-4o",
            persona="startup",
        )
        assert combined["totals"]["runs"] == 5
        assert combined["totals"]["successes"] == 5
        assert combined["totals"]["errors"] == 0
        assert combined["filters"] == {
            "plan": "pro",
            "feature": "resume_optimization",
            "provider": "openai",
            "model": "gpt-4o",
            "persona": "startup",
        }


class TestAiUsageSuppression:
    async def test_groups_under_five_users_or_runs_are_hidden(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_headers = await _admin_headers(db_session)
        now = datetime.now(timezone.utc)
        small_user_id, _ = await _create_user(db_session, plan="pro")
        small_resume_id = await _create_resume(db_session, user_id=small_user_id, persona="solo")
        for index in range(6):
            await _seed_optimization(
                db_session,
                user_id=small_user_id,
                resume_id=small_resume_id,
                created_at=now - timedelta(hours=12 + index),
                provider="cohere",
                model="command-r",
            )

        for index in range(5):
            user_id, _ = await _create_user(db_session, plan="pro")
            resume_id = await _create_resume(db_session, user_id=user_id, persona="startup")
            await _seed_optimization(
                db_session,
                user_id=user_id,
                resume_id=resume_id,
                created_at=now - timedelta(hours=6 + index),
                provider="openai",
                model="gpt-4o-mini",
            )

        body = await _usage(client, admin_headers)
        assert body["totals"]["runs"] == 11
        assert body["suppression"]["minimum_group_size"] == 5
        assert body["suppression"]["rule"].startswith("Hide a breakdown row")
        assert body["suppression"]["by_dimension"]["provider"] >= 1
        assert body["suppression"]["by_dimension"]["model"] >= 1
        assert body["suppression"]["by_dimension"]["persona"] >= 1
        assert body["suppressed_groups"] >= 3
        assert all(row["provider"] != "cohere" for row in body["by_provider"])
        assert all(row["model"] != "command-r" for row in body["by_model"])
        assert all(row["persona"] != "solo" for row in body["by_persona"])
        assert any(row["provider"] == "openai" for row in body["by_provider"])
        assert any(row["persona"] == "startup" for row in body["by_persona"])


class TestAiUsageAccessAndPrivacy:
    async def test_day_range_is_bounded(self, client: AsyncClient, db_session: AsyncSession):
        admin_headers = await _admin_headers(db_session)
        for days in (0, 366):
            response = await client.get(
                f"/admin/analytics/ai-usage?days={days}", headers=admin_headers
            )
            assert response.status_code == 422
        for days in (1, 365):
            response = await client.get(
                f"/admin/analytics/ai-usage?days={days}", headers=admin_headers
            )
            assert response.status_code == 200
            assert response.json()["period_days"] == days

    async def test_admin_only_and_no_content_or_per_user_data(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_headers = await _admin_headers(db_session)
        now = datetime.now(timezone.utc)
        user_ids: list[str] = []
        emails: list[str] = []
        for index in range(5):
            user_id, email = await _create_user(db_session, plan="pro")
            user_ids.append(user_id)
            emails.append(email)
            resume_id = await _create_resume(
                db_session,
                user_id=user_id,
                persona="startup",
                extra_metadata={"private_note": SECRET_KEY},
            )
            await _seed_optimization(
                db_session,
                user_id=user_id,
                resume_id=resume_id,
                created_at=now - timedelta(hours=8 + index),
            )
            await _seed_stage(
                db_session,
                user_id=user_id,
                resume_id=resume_id,
                stage_key="patches.0",
                created_at=now - timedelta(hours=4 + index),
                completed_at=now - timedelta(hours=4 + index) + timedelta(seconds=3),
                run_persona="startup",
            )

        non_admin_id, non_admin_email = await _create_user(db_session, plan="pro")
        user_headers = await _session_headers(db_session, non_admin_id)
        forbidden = await client.get("/admin/analytics/ai-usage", headers=user_headers)
        assert forbidden.status_code == 403

        anonymous = await client.get("/admin/analytics/ai-usage")
        assert anonymous.status_code == 401

        response = await client.get(
            "/admin/analytics/ai-usage?days=30&provider=openai",
            headers=admin_headers,
        )
        assert response.status_code == 200
        assert response.headers.get("content-type", "").startswith("application/json")
        body = response.json()
        serialized = json.dumps(body)
        for secret in (SECRET_JD, SECRET_LATEX, SECRET_KEY, non_admin_email):
            assert secret not in serialized
        for user_id in user_ids:
            assert user_id not in serialized
        for email in emails:
            assert email not in serialized
        assert SECRET_KEY not in serialized
        assert body["privacy"]["aggregate_only"] is True
        assert body["privacy"]["per_user_rows"] is False
        assert "per_user_rows" in serialized
        assert body["totals"]["users"] == 5
        assert body["by_provider"]
        assert all("user_id" not in row for row in body["by_provider"])

    async def test_platform_and_byok_are_labelled_without_key_material(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        monkeypatch.setattr(settings, "OPENAI_API_KEY", "unit-test-platform-value-2087")
        platform_scope = credential_scope("unit-test-platform-value-2087")
        byok_scope = credential_scope("unit-test-byok-value-2087")
        admin_headers = await _admin_headers(db_session)
        now = datetime.now(timezone.utc)
        for index in range(7):
            user_id, _ = await _create_user(db_session, plan="pro")
            resume_id = await _create_resume(db_session, user_id=user_id, persona="startup")
            await _seed_stage(
                db_session,
                user_id=user_id,
                resume_id=resume_id,
                stage_key="patches.0",
                created_at=now - timedelta(hours=4 + index),
                completed_at=now - timedelta(hours=4 + index) + timedelta(seconds=2),
                credential_scope_value=platform_scope if index < 5 else byok_scope,
                run_persona="startup",
            )

        body = await _usage(client, admin_headers)
        sources = {
            row["credential_source"]: row for row in body["by_credential_source"]
        }
        # The BYOK group has only two distinct users, so it is suppressed.
        assert sources["platform"]["runs"] == 5
        assert "byok" not in sources
        assert body["suppression"]["by_dimension"]["credential_source"] >= 1
        serialized = json.dumps(body)
        assert platform_scope not in serialized
        assert byok_scope not in serialized
        assert "unit-test-platform-value-2087" not in serialized
        assert "unit-test-byok-value-2087" not in serialized
