"""AI cost rollups, invoice sampling, spend caps, and rolling anomalies."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services import admin_ai_cost_service, admin_alert_service


async def _create_user(
    db: AsyncSession,
    *,
    role: str = "user",
    plan: str = "pro",
) -> str:
    user_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, 'Spend User', :role, true, :plan, 'active', false)"
        ),
        {
            "id": user_id,
            "email": f"test_spend_{user_id.replace('-', '')}@example.com",
            "role": role,
            "plan": plan,
        },
    )
    await db.commit()
    return user_id


async def _session_headers(db: AsyncSession, user_id: str) -> dict[str, str]:
    token = f"test_sess_spend_{uuid.uuid4().hex}"
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


async def _create_resume(
    db: AsyncSession,
    *,
    user_id: str,
    persona: str | None = "startup",
) -> str:
    resume_id = str(uuid.uuid4())
    metadata = {"last_persona": persona} if persona else {}
    await db.execute(
        text(
            "INSERT INTO resumes (id, user_id, title, latex_content, metadata, created_at) "
            "VALUES (:id, :uid, 'Spend Resume', 'latex', CAST(:metadata AS jsonb), :created)"
        ),
        {
            "id": resume_id,
            "uid": user_id,
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
    tokens: int,
    created_at: datetime,
    provider: str = "openai",
    model: str = "gpt-4o-mini",
) -> str:
    optimization_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO optimizations (id, user_id, resume_id, job_description, "
            "original_latex, optimized_latex, provider, model, tokens_used, created_at) "
            "VALUES (:id, :uid, :resume, 'jd', 'a', 'b', :provider, :model, :tokens, :created)"
        ),
        {
            "id": optimization_id,
            "uid": user_id,
            "resume": resume_id,
            "provider": provider,
            "model": model,
            "tokens": tokens,
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
    usage: dict,
    created_at: datetime,
    provider: str = "openai",
    model: str = "gpt-4o-mini",
) -> None:
    job_id = f"test_spend_job_{uuid.uuid4().hex}"
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
    run_id = f"test_spend_run_{uuid.uuid4().hex}"
    await db.execute(
        text(
            "INSERT INTO resume_optimization_runs "
            "(id, job_id, resume_id, user_id, base_revision, source_sha256, context_hash, "
            "effort, provider, model, credential_scope, status, snapshot, context_payload, "
            "budget, decisions, expires_at, created_at) "
            "VALUES (:id, :job_id, :resume, :uid, 1, :sha, :sha, 'standard', :provider, :model, "
            "'platform', 'completed', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, :expires, :created)"
        ),
        {
            "id": run_id,
            "job_id": job_id,
            "resume": resume_id,
            "uid": user_id,
            "sha": "a" * 64,
            "provider": provider,
            "model": model,
            "expires": created_at + timedelta(days=7),
            "created": created_at,
        },
    )
    await db.execute(
        text(
            "INSERT INTO resume_optimization_stages "
            "(run_id, stage_key, input_hash, status, owner_token, owner_epoch, "
            "reserved_usage, usage, output, output_hash, completed_at) "
            "VALUES (:run_id, :stage_key, :sha, 'completed', :owner, 1, "
            "CAST(:reserved AS jsonb), CAST(:usage AS jsonb), '{}'::jsonb, :sha, :completed)"
        ),
        {
            "run_id": run_id,
            "stage_key": stage_key,
            "sha": "b" * 64,
            "owner": f"test_owner_{uuid.uuid4().hex}",
            "reserved": json.dumps({"input_tokens": 0, "output_tokens": 0, "cost_usd": 0}),
            "usage": json.dumps(usage),
            "completed": created_at,
        },
    )
    await db.commit()


class TestAiCostRollups:
    async def test_feature_persona_filters_and_minor_units(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_headers = await _admin_headers(db_session)
        user_id = await _create_user(db_session, plan="pro")
        resume_id = await _create_resume(db_session, user_id=user_id, persona="startup")
        now = datetime.now(timezone.utc)
        await _seed_optimization(
            db_session,
            user_id=user_id,
            resume_id=resume_id,
            tokens=1_000_000,
            created_at=now - timedelta(days=1),
        )
        await _seed_stage(
            db_session,
            user_id=user_id,
            resume_id=resume_id,
            stage_key="patches.0",
            usage={"input_tokens": 1_000_000, "output_tokens": 1_000_000, "cost_usd": 0.6},
            created_at=now - timedelta(hours=2),
        )

        response = await client.get("/admin/analytics/ai-cost?days=30", headers=admin_headers)
        assert response.status_code == 200
        body = response.json()
        assert body["estimated"] is True
        assert body["cost_currency"] == "USD"
        assert body["cost_minor_unit"] == "cent"
        assert body["revenue_currency"] == "INR"
        assert body["revenue_minor_unit"] == "paise"
        assert body["pricing_version"].startswith("pricing-v1:")
        assert body["pricing"]["models"]
        assert body["total_cost_usd_minor"] == round(body["total_cost_usd"] * 100)
        assert body["total_cost_inr"] == round(body["total_cost_usd"] * settings.ADMIN_AI_COST_USD_INR_RATE, 2)
        assert any(row["feature"] == "optimization_patches" for row in body["by_feature"])
        assert any(row["feature"] == "resume_optimization" for row in body["by_feature"])
        assert any(row["persona"] == "startup" for row in body["by_persona"])
        assert any(row["date"] for row in body["daily_by_feature"])
        assert body["reconciliation"]["provider_keys_required"] is False
        assert body["reconciliation"]["provider_key_included"] is False

        filtered = await client.get(
            "/admin/analytics/ai-cost?days=30&feature=optimization_patches",
            headers=admin_headers,
        )
        assert filtered.status_code == 200
        filtered_body = filtered.json()
        assert filtered_body["filters"]["feature"] == "optimization_patches"
        assert filtered_body["by_feature"]
        assert all(row["feature"] == "optimization_patches" for row in filtered_body["by_feature"])

        plan_filtered = await client.get(
            "/admin/analytics/ai-cost?days=30&plan=pro", headers=admin_headers
        )
        assert plan_filtered.status_code == 200
        assert plan_filtered.json()["by_plan"]
        assert all(row["plan"] == "pro" for row in plan_filtered.json()["by_plan"])

    async def test_unknown_pricing_is_explicit(self, client: AsyncClient, db_session: AsyncSession):
        admin_headers = await _admin_headers(db_session)
        user_id = await _create_user(db_session)
        resume_id = await _create_resume(db_session, user_id=user_id, persona=None)
        await _seed_optimization(
            db_session,
            user_id=user_id,
            resume_id=resume_id,
            tokens=1_000_000,
            created_at=datetime.now(timezone.utc) - timedelta(hours=1),
            provider="acme",
            model="mystery-v1",
        )

        response = await client.get("/admin/analytics/ai-cost?days=30", headers=admin_headers)
        assert response.status_code == 200
        body = response.json()
        row = next(
            item for item in body["by_model"] if item["provider"] == "acme" and item["model"] == "mystery-v1"
        )
        assert row["fallback_price"] is True
        assert row["pricing_status"] == "fallback_estimate"
        assert row["unknown_pricing"] is True
        assert body["pricing_complete"] is False
        assert any(
            item["provider"] == "acme" and item["model"] == "mystery-v1"
            for item in body["unknown_pricing"]["models"]
        )
        assert any(alert["code"] == "ai_unknown_pricing" for alert in body["alerts"])

    async def test_sampled_invoice_reconciliation_contract(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_headers = await _admin_headers(db_session)
        user_id = await _create_user(db_session)
        resume_id = await _create_resume(db_session, user_id=user_id)
        await _seed_optimization(
            db_session,
            user_id=user_id,
            resume_id=resume_id,
            tokens=1_000_000,
            created_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )

        initial = await client.get("/admin/analytics/ai-cost?days=30", headers=admin_headers)
        assert initial.status_code == 200
        ledger_minor = initial.json()["total_cost_usd_minor"]

        response = await client.get(
            "/admin/analytics/ai-cost",
            params={
                "days": 30,
                "invoice_total_minor": ledger_minor,
                "invoice_reference": "test-invoice-2088",
            },
            headers=admin_headers,
        )
        assert response.status_code == 200
        body = response.json()
        reconciliation = body["reconciliation"]
        assert reconciliation["contract_version"] == "ai-invoice-sample-v1"
        assert reconciliation["status"] == "matched"
        assert reconciliation["sampled_invoice"]["provided"] is True
        assert reconciliation["sampled_invoice"]["variance_minor"] == 0
        assert reconciliation["sampled_invoice"]["within_tolerance"] is True
        assert reconciliation["sources"]
        assert "provider_key" not in json.dumps(reconciliation["sampled_invoice"]).lower()
        assert reconciliation["contract"]["provider_credentials_required"] is False


class TestSpendCapsAndAnomalies:
    async def test_cap_boundary_daily_reset_and_no_suspension(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        user_id = await _create_user(db_session, plan="pro")
        resume_id = await _create_resume(db_session, user_id=user_id)
        now = datetime.now(timezone.utc)
        await _seed_optimization(
            db_session,
            user_id=user_id,
            resume_id=resume_id,
            tokens=1_000_000,
            created_at=now - timedelta(minutes=5),
            provider="openai",
            model="gpt-4o",
        )

        monkeypatch.setattr(settings, "ADMIN_AI_USER_MONTHLY_HARD_CAP_USD", 6.25)
        monkeypatch.setattr(settings, "ADMIN_AI_USER_DAILY_HARD_CAP_USD", 0.0)
        monkeypatch.setattr(settings, "ADMIN_AI_JOB_ESTIMATE_USD", 0.0)
        decision = await admin_ai_cost_service.check_user_spend_guard(
            db_session,
            user_id=user_id,
            actor=user_id,
            reason="test_cap_boundary",
            job_type="combined",
            now=now,
        )
        assert decision["allowed"] is False
        assert decision["decision"] == "block"
        assert "monthly_hard_cap_reached" in decision["reasons"]
        assert decision["auto_suspend"] is False
        assert decision["in_flight_jobs_affected"] is False
        assert decision["window"]["month_resets_at"].endswith("T00:00:00+00:00")

        row = (
            await db_session.execute(
                text("SELECT subscription_status, subscription_plan FROM users WHERE id = :id"),
                {"id": user_id},
            )
        ).one()
        assert row.subscription_status == "active"
        assert row.subscription_plan == "pro"

        # A fresh day resets the daily window even though monthly spend exists.
        monkeypatch.setattr(settings, "ADMIN_AI_USER_MONTHLY_HARD_CAP_USD", 0.0)
        monkeypatch.setattr(settings, "ADMIN_AI_USER_DAILY_HARD_CAP_USD", 1.0)
        tomorrow = now + timedelta(days=1)
        reset_decision = await admin_ai_cost_service.check_user_spend_guard(
            db_session,
            user_id=user_id,
            actor=user_id,
            reason="test_daily_reset",
            job_type="combined",
            now=tomorrow,
        )
        assert reset_decision["allowed"] is True
        assert reset_decision["decision"] == "allow"
        assert reset_decision["today_usd"] == 0

    async def test_outlier_fixture_routes_aggregate_signal(
        self, db_session: AsyncSession, monkeypatch
    ):
        user_id = await _create_user(db_session, plan="pro")
        resume_id = await _create_resume(db_session, user_id=user_id)
        now = datetime.now(timezone.utc)
        for offset in range(1, 6):
            await _seed_optimization(
                db_session,
                user_id=user_id,
                resume_id=resume_id,
                tokens=100_000,
                created_at=now - timedelta(days=offset),
                provider="openai",
                model="gpt-4o",
            )
        await _seed_optimization(
            db_session,
            user_id=user_id,
            resume_id=resume_id,
            tokens=1_000_000,
            created_at=now - timedelta(minutes=5),
            provider="openai",
            model="gpt-4o",
        )

        monkeypatch.setattr(settings, "ADMIN_AI_ANOMALY_BASELINE_DAYS", 14)
        monkeypatch.setattr(settings, "ADMIN_AI_ANOMALY_MIN_BASELINE_DAYS", 5)
        monkeypatch.setattr(settings, "ADMIN_AI_ANOMALY_MAD_MULTIPLIER", 3.0)
        monkeypatch.setattr(settings, "ADMIN_AI_ANOMALY_MIN_USD", 0.5)
        entries = await admin_ai_cost_service._load_cost_entries(
            db_session, start=now - timedelta(days=15), end=now + timedelta(minutes=1)
        )
        outliers = admin_ai_cost_service._build_outliers(entries, now)
        assert any(
            row["dimension"] == "user" and row["key"] == user_id for row in outliers
        )

        signals = await admin_alert_service.collect_signals(db_session, now)
        anomaly = next(signal for signal in signals if signal["kind"] == "spend.anomaly")
        assert anomaly["dedupe_key"] == f"spend.anomaly:{now.date().isoformat()}"
        assert "user_id" not in anomaly["payload"]
        assert anomaly["payload"]["users"] >= 1

    async def test_user_cap_signal_is_aggregate_only(self, db_session: AsyncSession, monkeypatch):
        user_id = await _create_user(db_session, plan="pro")
        resume_id = await _create_resume(db_session, user_id=user_id)
        now = datetime.now(timezone.utc)
        await _seed_optimization(
            db_session,
            user_id=user_id,
            resume_id=resume_id,
            tokens=1_000_000,
            created_at=now - timedelta(minutes=5),
            provider="openai",
            model="gpt-4o",
        )
        monkeypatch.setattr(settings, "ADMIN_AI_USER_MONTHLY_HARD_CAP_USD", 1.0)
        monkeypatch.setattr(settings, "ADMIN_AI_USER_DAILY_HARD_CAP_USD", 0.0)
        monkeypatch.setattr(settings, "ADMIN_AI_JOB_ESTIMATE_USD", 0.0)

        decision = await admin_ai_cost_service.check_user_spend_guard(
            db_session,
            user_id=user_id,
            actor="admin-test",
            reason="test_aggregate_signal",
            job_type="ats_scoring",
            now=now,
        )
        assert decision["allowed"] is False
        signals = await admin_alert_service.collect_signals(db_session, now)
        cap_signal = next(signal for signal in signals if signal["kind"] == "spend.user_caps")
        assert cap_signal["payload"]["hard_cap_users"] >= 1
        assert "user_id" not in cap_signal["payload"]
        assert "users" not in cap_signal["payload"]

        # Alert evaluation must not suspend the account.
        await admin_alert_service.evaluate_alerts(db_session, now=now)
        row = (
            await db_session.execute(
                text("SELECT subscription_status FROM users WHERE id = :id"), {"id": user_id}
            )
        ).scalar_one()
        assert row == "active"
