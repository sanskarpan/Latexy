"""BYOK vs platform-key usage mix: classification, reconciliation, privacy."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.credential_source import (
    credential_source_for_api_key,
    credential_source_from_scope,
    platform_credential_scopes,
)
from app.services.resume_engine.credential_scope import credential_scope

SECRET_JD = "private credential mix jd marker 2089"
SECRET_LATEX = "private credential mix latex marker 2089"
SECRET_KEY = "private credential mix token marker 2089"
KEY_NAME = "private key name marker 2089"


@pytest.fixture(autouse=True)
async def _isolate_credential_mix_sources(db_session: AsyncSession):
    """Keep the shared test database's older AI and key rows out of assertions."""
    await db_session.execute(text("DELETE FROM resume_optimization_stages"))
    await db_session.execute(text("DELETE FROM resume_optimization_runs"))
    await db_session.execute(text("DELETE FROM optimizations"))
    await db_session.execute(text("DELETE FROM user_api_keys"))
    await db_session.commit()
    yield


async def _create_user(
    db: AsyncSession,
    *,
    role: str = "user",
    plan: str = "pro",
) -> tuple[str, str]:
    user_id = str(uuid.uuid4())
    email = f"test_cred_mix_{user_id.replace('-', '')}@example.com"
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, 'Credential Mix User', :role, true, :plan, 'active', false)"
        ),
        {"id": user_id, "email": email, "role": role, "plan": plan},
    )
    await db.commit()
    return user_id, email


async def _session_headers(db: AsyncSession, user_id: str) -> dict[str, str]:
    token = f"test_sess_cred_mix_{uuid.uuid4().hex}"
    await db.execute(
        text('INSERT INTO session (id, "userId", "expiresAt", token) VALUES (:id, :uid, :exp, :tok)'),
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
            "VALUES (:id, :uid, 'Credential Mix Resume', :latex, CAST(:metadata AS jsonb), :created)"
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
) -> str:
    optimization_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO optimizations (id, user_id, resume_id, job_description, "
            "original_latex, optimized_latex, provider, model, tokens_used, created_at) "
            "VALUES (:id, :uid, :resume, :jd, :original, :optimized, :provider, :model, "
            ":tokens, :created)"
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
    provider: str = "openai",
    model: str = "gpt-4o-mini",
    credential_scope_value: str = "platform",
    persisted_source: str | None = None,
    usage: dict | None = None,
    run_persona: str | None = "startup",
) -> str:
    job_id = f"test_cred_mix_job_{uuid.uuid4().hex}"
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
    run_id = f"test_cred_mix_run_{uuid.uuid4().hex}"
    context: dict = {"direction": {"persona": run_persona}}
    if persisted_source is not None:
        context["credential_source"] = persisted_source
    context["private_note"] = SECRET_KEY
    await db.execute(
        text(
            "INSERT INTO resume_optimization_runs "
            "(id, job_id, resume_id, user_id, base_revision, source_sha256, context_hash, "
            "effort, provider, model, credential_scope, status, snapshot, context_payload, "
            "budget, decisions, expires_at, created_at, updated_at) "
            "VALUES (:id, :job_id, :resume, :uid, 1, :sha, :sha, 'standard', :provider, :model, "
            ":scope, 'completed', '{}'::jsonb, CAST(:context AS jsonb), '{}'::jsonb, '{}'::jsonb, "
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
            "context": json.dumps(context),
            "expires": created_at + timedelta(days=7),
            "created": created_at,
            "updated": created_at,
        },
    )
    if usage is None:
        usage = {"input_tokens": 1_000, "output_tokens": 1_000, "cost_usd": 0.02}
    await db.execute(
        text(
            "INSERT INTO resume_optimization_stages "
            "(run_id, stage_key, input_hash, status, owner_token, owner_epoch, "
            "reserved_usage, usage, output, output_hash, created_at, completed_at) "
            "VALUES (:run_id, :stage_key, :sha, 'completed', :owner, 1, "
            "CAST(:reserved AS jsonb), CAST(:usage AS jsonb), '{}'::jsonb, :sha, :created, :completed)"
        ),
        {
            "run_id": run_id,
            "stage_key": stage_key,
            "sha": "b" * 64,
            "owner": f"test_owner_{uuid.uuid4().hex}",
            "reserved": json.dumps({"input_tokens": 0, "output_tokens": 0, "cost_usd": 0}),
            "usage": json.dumps(usage),
            "created": created_at,
            "completed": created_at,
        },
    )
    await db.commit()
    return run_id


async def _seed_byok_key(
    db: AsyncSession,
    *,
    user_id: str,
    provider: str = "openai",
    active: bool = True,
) -> str:
    key_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO user_api_keys (id, user_id, provider, encrypted_key, key_name, is_active) "
            "VALUES (:id, :uid, :provider, :encrypted, :name, :active)"
        ),
        {
            "id": key_id,
            "uid": user_id,
            "provider": provider,
            "encrypted": SECRET_KEY,
            "name": KEY_NAME,
            "active": active,
        },
    )
    await db.commit()
    return key_id


async def _mix(client: AsyncClient, headers: dict[str, str], **params) -> dict:
    response = await client.get("/admin/analytics/credential-mix", params={"days": 30, **params}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


class TestCredentialSourceClassification:
    def test_scope_and_api_key_labels_are_non_secret(self, monkeypatch):
        monkeypatch.setattr(settings, "OPENAI_API_KEY", "unit-test-platform-2089")
        platform_scope = credential_scope("unit-test-platform-2089")
        byok_scope = credential_scope("unit-test-byok-2089")
        scopes = platform_credential_scopes()

        assert credential_source_from_scope(platform_scope, scopes) == "platform"
        assert credential_source_from_scope(byok_scope, scopes) == "byok"
        assert credential_source_from_scope(platform_scope, scopes, "byok") == "byok"
        assert credential_source_from_scope(byok_scope, scopes, "platform") == "platform"
        assert credential_source_from_scope(None, scopes) == "unknown"
        assert credential_source_from_scope("not-a-fingerprint", scopes) == "unknown"
        assert credential_source_for_api_key("unit-test-platform-2089") == "platform"
        assert credential_source_for_api_key("unit-test-byok-2089") == "byok"
        assert credential_source_for_api_key("") == "unknown"
        assert credential_source_for_api_key(None) == "unknown"

    async def test_persisted_label_wins_over_scope_inference(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        monkeypatch.setattr(settings, "OPENAI_API_KEY", "unit-test-platform-2089")
        platform_scope = credential_scope("unit-test-platform-2089")
        admin_headers = await _admin_headers(db_session)
        now = datetime.now(timezone.utc)
        for index in range(5):
            user_id, _ = await _create_user(db_session, plan="pro")
            resume_id = await _create_resume(db_session, user_id=user_id)
            await _seed_stage(
                db_session,
                user_id=user_id,
                resume_id=resume_id,
                stage_key="patches.0",
                created_at=now - timedelta(hours=index),
                credential_scope_value=platform_scope,
                persisted_source="byok",
            )

        body = await _mix(client, admin_headers)
        assert body["totals"]["mix"]["byok"]["calls"] == 5
        assert body["totals"]["mix"]["platform"]["calls"] == 0
        assert body["reconciliation"]["unknown_calls"] == 0


class TestCredentialMixReconciliation:
    async def test_byok_platform_unknown_reconcile_with_usage_and_cost(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        monkeypatch.setattr(settings, "OPENAI_API_KEY", "unit-test-platform-2089")
        platform_scope = credential_scope("unit-test-platform-2089")
        byok_scope = credential_scope("unit-test-byok-2089")
        admin_headers = await _admin_headers(db_session)
        now = datetime.now(timezone.utc)

        byok_users: list[str] = []
        for index in range(5):
            user_id, _ = await _create_user(db_session, plan="byok")
            byok_users.append(user_id)
            resume_id = await _create_resume(db_session, user_id=user_id, persona="startup")
            await _seed_stage(
                db_session,
                user_id=user_id,
                resume_id=resume_id,
                stage_key="patches.0",
                created_at=now - timedelta(hours=2 + index),
                credential_scope_value=byok_scope,
                usage={"input_tokens": 1_000, "output_tokens": 1_000, "cost_usd": 0.03},
            )
        for index in range(5):
            user_id, _ = await _create_user(db_session, plan="pro")
            resume_id = await _create_resume(db_session, user_id=user_id, persona="startup")
            await _seed_stage(
                db_session,
                user_id=user_id,
                resume_id=resume_id,
                stage_key="patches.0",
                created_at=now - timedelta(hours=2 + index),
                credential_scope_value=platform_scope,
                usage={"input_tokens": 1_000, "output_tokens": 1_000, "cost_usd": 0.02},
            )
        for index in range(5):
            user_id, _ = await _create_user(db_session, plan="free")
            resume_id = await _create_resume(db_session, user_id=user_id, persona="startup")
            await _seed_optimization(
                db_session,
                user_id=user_id,
                resume_id=resume_id,
                created_at=now - timedelta(hours=1 + index),
            )

        # Ownership counts: one visible provider group and one small hidden group.
        for user_id in byok_users:
            await _seed_byok_key(db_session, user_id=user_id, provider="openai")
        hidden_key_user, _ = await _create_user(db_session, plan="byok")
        hidden_key_id = await _seed_byok_key(db_session, user_id=hidden_key_user, provider="anthropic")

        body = await _mix(client, admin_headers)
        totals = body["totals"]
        assert totals["calls"] == 15
        assert totals["tokens"] == 25_000
        assert totals["users"] == 15
        assert totals["mix"]["byok"]["calls"] == 5
        assert totals["mix"]["platform"]["calls"] == 5
        assert totals["mix"]["unknown"]["calls"] == 5
        assert totals["mix"]["byok"]["cost_usd"] == pytest.approx(0.15)
        assert totals["mix"]["platform"]["cost_usd"] == pytest.approx(0.10)
        assert totals["mix"]["unknown"]["cost_usd"] > 0
        assert body["reconciliation"]["call_share_total_pct"] == 100.0
        assert (
            round(sum(totals["mix"][source]["call_share_pct"] for source in ("byok", "platform", "unknown")), 2)
            == 100.0
        )
        assert all(check["ok"] for check in body["reconciliation"]["checks"])

        sources = {row["credential_source"]: row for row in body["sources"]}
        assert set(sources) == {"byok", "platform", "unknown"}
        assert sources["unknown"]["token_share_pct"] > 0
        assert any(
            row["feature"] == "optimization_patches" and row["credential_source"] == "byok"
            for row in body["by_feature"]
        )
        assert any(
            row["feature"] == "optimization_patches" and row["credential_source"] == "platform"
            for row in body["by_feature"]
        )
        assert any(
            row["feature"] == "resume_optimization" and row["credential_source"] == "unknown"
            for row in body["by_feature"]
        )
        assert any(row["plan"] == "byok" and row["credential_source"] == "byok" for row in body["by_plan"])

        ownership = body["key_ownership"]
        assert ownership["active_keys"] == 6
        assert ownership["users_with_active_keys"] == 6
        assert [row["provider"] for row in ownership["by_provider"]] == ["openai"]
        assert ownership["suppressed_groups"] >= 1

        usage = await client.get("/admin/analytics/ai-usage", params={"days": 30}, headers=admin_headers)
        assert usage.status_code == 200
        assert body["totals"]["calls"] == usage.json()["totals"]["runs"]
        assert body["reconciliation"]["total_tokens"] == usage.json()["totals"]["tokens"]

        serialized = json.dumps(body)
        for secret in (
            platform_scope,
            byok_scope,
            SECRET_JD,
            SECRET_LATEX,
            SECRET_KEY,
            KEY_NAME,
            hidden_key_id,
        ):
            assert secret not in serialized
        assert body["privacy"]["aggregate_only"] is True
        assert body["privacy"]["per_user_rows"] is False


class TestCredentialMixSuppression:
    async def test_small_source_feature_and_key_groups_are_hidden(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        monkeypatch.setattr(settings, "OPENAI_API_KEY", "unit-test-platform-2089")
        platform_scope = credential_scope("unit-test-platform-2089")
        byok_scope = credential_scope("unit-test-byok-2089")
        admin_headers = await _admin_headers(db_session)
        now = datetime.now(timezone.utc)

        for index in range(5):
            user_id, _ = await _create_user(db_session, plan="pro")
            resume_id = await _create_resume(db_session, user_id=user_id)
            await _seed_stage(
                db_session,
                user_id=user_id,
                resume_id=resume_id,
                stage_key="patches.0",
                created_at=now - timedelta(hours=2 + index),
                credential_scope_value=platform_scope,
            )
        small_user_id, _ = await _create_user(db_session, plan="byok")
        small_resume_id = await _create_resume(db_session, user_id=small_user_id)
        await _seed_stage(
            db_session,
            user_id=small_user_id,
            resume_id=small_resume_id,
            stage_key="requirements",
            created_at=now - timedelta(hours=1),
            credential_scope_value=byok_scope,
        )
        await _seed_byok_key(db_session, user_id=small_user_id, provider="anthropic")

        body = await _mix(client, admin_headers)
        assert body["totals"]["mix"]["byok"]["calls"] == 1
        assert body["totals"]["mix"]["platform"]["calls"] == 5
        assert [row["credential_source"] for row in body["sources"]] == ["platform"]
        assert body["suppression"]["by_dimension"]["credential_source"] >= 1
        assert body["suppression"]["by_dimension"]["feature"] >= 1
        assert body["key_ownership"]["by_provider"] == []
        assert body["key_ownership"]["suppressed_groups"] >= 1
        assert body["reconciliation"]["call_share_total_pct"] == 100.0
        assert all(check["ok"] for check in body["reconciliation"]["checks"])


class TestCredentialMixAccessAndFilters:
    async def test_admin_only(self, client: AsyncClient, db_session: AsyncSession):
        non_admin_id, _ = await _create_user(db_session, plan="pro")
        user_headers = await _session_headers(db_session, non_admin_id)
        support_id, _ = await _create_user(db_session, role="support", plan="pro")
        support_headers = await _session_headers(db_session, support_id)
        admin_headers = await _admin_headers(db_session)

        anonymous = await client.get("/admin/analytics/credential-mix")
        assert anonymous.status_code == 401
        forbidden = await client.get("/admin/analytics/credential-mix", headers=user_headers)
        assert forbidden.status_code == 403
        support_forbidden = await client.get("/admin/analytics/credential-mix", headers=support_headers)
        assert support_forbidden.status_code == 403
        allowed = await client.get("/admin/analytics/credential-mix", headers=admin_headers)
        assert allowed.status_code == 200

        for days in (0, 366):
            response = await client.get(f"/admin/analytics/credential-mix?days={days}", headers=admin_headers)
            assert response.status_code == 422
        for days in (1, 365):
            response = await client.get(f"/admin/analytics/credential-mix?days={days}", headers=admin_headers)
            assert response.status_code == 200
            assert response.json()["period_days"] == days

    async def test_each_dimension_filter(self, client: AsyncClient, db_session: AsyncSession, monkeypatch):
        monkeypatch.setattr(settings, "OPENAI_API_KEY", "unit-test-platform-2089")
        platform_scope = credential_scope("unit-test-platform-2089")
        byok_scope = credential_scope("unit-test-byok-2089")
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
                "scope": platform_scope,
            },
            {
                "plan": "team",
                "provider": "anthropic",
                "model": "claude-3-5-sonnet",
                "persona": "fintech",
                "stage_key": "requirements.global",
                "feature": "requirements",
                "scope": byok_scope,
            },
        ]
        for group in groups:
            for index in range(5):
                user_id, _ = await _create_user(db_session, plan=group["plan"])
                resume_id = await _create_resume(db_session, user_id=user_id, persona=group["persona"])
                await _seed_stage(
                    db_session,
                    user_id=user_id,
                    resume_id=resume_id,
                    stage_key=group["stage_key"],
                    created_at=now - timedelta(hours=2 + index),
                    provider=group["provider"],
                    model=group["model"],
                    credential_scope_value=group["scope"],
                    run_persona=group["persona"],
                )

        cases = [
            ("plan", "pro", 5),
            ("plan", "team", 5),
            ("feature", "optimization_patches", 5),
            ("feature", "requirements", 5),
            ("provider", "OpenAI", 5),
            ("provider", "anthropic", 5),
            ("model", "gpt-4o", 5),
            ("model", "claude-3-5-sonnet", 5),
            ("persona", "startup", 5),
            ("persona", "fintech", 5),
        ]
        for dimension, value, expected_calls in cases:
            body = await _mix(client, admin_headers, **{dimension: value})
            assert body["totals"]["calls"] == expected_calls, (dimension, value, body["totals"])
            assert body["filters"][dimension] == value.lower()

        combined = await _mix(
            client,
            admin_headers,
            plan="team",
            feature="requirements",
            provider="anthropic",
            model="claude-3-5-sonnet",
            persona="fintech",
        )
        assert combined["totals"]["calls"] == 5
        assert combined["totals"]["mix"]["byok"]["calls"] == 5
        assert combined["filters"] == {
            "plan": "team",
            "feature": "requirements",
            "provider": "anthropic",
            "model": "claude-3-5-sonnet",
            "persona": "fintech",
        }
