"""Admin AI latency/retry report: percentiles, reconciliation, privacy, access."""

from __future__ import annotations

import importlib.util
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import LLMCallAttempt
from app.services.llm_attempt_recording import (
    build_attempt,
    classify_exception,
    record_llm_attempt,
)

SECRET_ERROR = "customer prompt and latex secret marker 2090"


@pytest.fixture(autouse=True)
async def _isolate_attempts(db_session: AsyncSession):
    await db_session.execute(text("DELETE FROM llm_call_attempts"))
    await db_session.commit()
    yield
    await db_session.execute(text("DELETE FROM llm_call_attempts"))
    await db_session.commit()


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
            "VALUES (:id, :email, 'Latency User', :role, true, :plan, 'active', false)"
        ),
        {
            "id": user_id,
            "email": f"test_ai_latency_{user_id.replace('-', '')}@example.com",
            "role": role,
            "plan": plan,
        },
    )
    await db.commit()
    return user_id


async def _headers(db: AsyncSession, user_id: str) -> dict[str, str]:
    token = f"test_sess_ai_latency_{uuid.uuid4().hex}"
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
    return await _headers(db, await _create_user(db, role="admin"))


async def _seed_attempts(db: AsyncSession, rows: list[dict]) -> None:
    if not rows:
        return
    await db.execute(
        text(
            "INSERT INTO llm_call_attempts "
            "(occurred_at, provider, model, feature, plan, run_ref, attempt_number, "
            "status, retry_reason, error_class, latency_ms) "
            "VALUES (:occurred_at, :provider, :model, :feature, :plan, :run_ref, "
            ":attempt_number, :status, :retry_reason, :error_class, :latency_ms)"
        ),
        rows,
    )
    await db.commit()


def _row(
    *,
    occurred_at: datetime | None = None,
    provider: str = "openai",
    model: str = "gpt-4o-mini",
    feature: str = "resume_optimization",
    plan: str = "pro",
    run_ref: str | None = None,
    attempt: int = 1,
    status: str = "success",
    retry_reason: str = "none",
    error_class: str | None = None,
    latency_ms: float | None = 120.0,
) -> dict:
    return {
        "occurred_at": occurred_at or datetime.now(timezone.utc) - timedelta(minutes=1),
        "provider": provider,
        "model": model,
        "feature": feature,
        "plan": plan,
        "run_ref": run_ref or f"test_run_{uuid.uuid4().hex[:20]}",
        "attempt_number": attempt,
        "status": status,
        "retry_reason": retry_reason,
        "error_class": error_class,
        "latency_ms": latency_ms,
    }


def test_migration_declares_reserved_revision_and_table():
    path = Path(__file__).parents[1] / "alembic" / "versions" / "0089_ai_latency_retry.py"
    spec = importlib.util.spec_from_file_location("ai_latency_retry_migration", path)
    migration = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(migration)
    assert migration.revision == "0089_ai_latency_retry"
    assert migration.down_revision == "0088_admin_incidents"
    source = path.read_text()
    assert '"llm_call_attempts"' in source
    assert "drop_table" in source


class TestAiLatencyPercentiles:
    async def test_percentiles_reconcile_to_attempt_rows(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        headers = await _admin_headers(db_session)
        for value in (100.0, 200.0, 300.0, 400.0, 500.0):
            await _seed_attempts(
                db_session,
                [_row(provider="lat_provider", model="lat_model", latency_ms=value)],
            )
        # Outside the 7-day window: must not change 7-day percentiles.
        await _seed_attempts(
            db_session,
            [
                _row(
                    provider="lat_provider",
                    model="lat_model",
                    latency_ms=9000.0,
                    occurred_at=datetime.now(timezone.utc) - timedelta(days=10),
                )
            ],
        )

        response = await client.get(
            "/admin/analytics/ai-latency-retry"
            "?days=7&provider=lat_provider&model=lat_model",
            headers=headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["days"] == 7
        assert body["duration_unit"] == "milliseconds"
        assert body["overall"]["attempts"] == 5
        assert body["overall"]["runs"] == 5
        assert body["overall"]["p50_ms"] == pytest.approx(300.0)
        assert body["overall"]["p95_ms"] == pytest.approx(480.0)
        assert body["overall"]["p99_ms"] == pytest.approx(496.0)
        assert body["overall"]["mean_ms"] == pytest.approx(300.0)
        assert body["overall"]["max_ms"] == pytest.approx(500.0)
        assert body["overall"]["sparse"] is False

        assert body["totals"]["attempts"] == 5
        assert body["totals"]["latency_samples"] == 5
        assert body["by_provider"][0]["p95_ms"] == pytest.approx(480.0)
        assert body["by_model"][0]["value"] == "lat_provider/lat_model"
        assert sum(row["attempts"] for row in body["by_provider"]) == 5
        assert body["reconciliation"]["all_dimensions_reconcile"] is True
        assert body["reconciliation"]["statuses_reconcile"] is True

        for days in (30, 90):
            wider = await client.get(
                f"/admin/analytics/ai-latency-retry?days={days}"
                "&provider=lat_provider&model=lat_model",
                headers=headers,
            )
            assert wider.status_code == 200
            assert wider.json()["overall"]["attempts"] == 6
            assert wider.json()["overall"]["max_ms"] == pytest.approx(9000.0)

    async def test_empty_window_returns_zeroed_aggregates(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        headers = await _admin_headers(db_session)
        response = await client.get(
            "/admin/analytics/ai-latency-retry?days=30&provider=no-such-provider",
            headers=headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["overall"]["attempts"] == 0
        assert body["overall"]["p50_ms"] is None
        assert body["overall"]["p95_ms"] is None
        assert body["overall"]["p99_ms"] is None
        assert body["overall"]["retry_rate_pct"] == 0.0
        assert body["by_provider"] == []
        assert body["by_model"] == []
        assert body["by_feature"] == []
        assert body["by_plan"] == []
        assert body["retry_reasons"] == []
        assert body["statuses"] == []
        assert body["reconciliation"]["all_dimensions_reconcile"] is True
        assert body["reconciliation"]["statuses_reconcile"] is True

    async def test_high_cardinality_groups_are_capped_but_reconciled(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        headers = await _admin_headers(db_session)
        rows: list[dict] = []
        for index in range(55):
            for value in (10.0, 20.0, 30.0, 40.0, 50.0):
                rows.append(
                    _row(
                        provider=f"provider_{index:02d}",
                        model="shared-model",
                        latency_ms=value + index,
                    )
                )
        await _seed_attempts(db_session, rows)

        response = await client.get(
            "/admin/analytics/ai-latency-retry?days=30", headers=headers
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["totals"]["attempts"] == 275
        assert len(body["by_provider"]) == body["max_groups"] == 50
        cardinality = body["cardinality"]["provider"]
        assert cardinality["groups"] == 55
        assert cardinality["truncated"] is True
        assert cardinality["truncated_groups"] == 5
        assert cardinality["truncated_attempts"] == 25
        assert body["cardinality"]["model"]["groups"] == 55
        assert body["cardinality"]["model"]["truncated_attempts"] == 25
        assert body["reconciliation"]["dimension_attempts"]["provider"] == 275
        assert body["reconciliation"]["dimension_attempts"]["model"] == 275
        assert body["reconciliation"]["all_dimensions_reconcile"] is True


class TestAiRetryReconciliation:
    async def test_retry_rate_reasons_and_statuses_reconcile(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        headers = await _admin_headers(db_session)
        rows: list[dict] = []
        for _ in range(5):
            run_ref = f"retry_{uuid.uuid4().hex[:18]}"
            rows.append(
                _row(
                    run_ref=run_ref,
                    attempt=1,
                    status="error",
                    retry_reason="empty_output",
                    error_class="invalid_response",
                    latency_ms=80.0,
                )
            )
            rows.append(
                _row(run_ref=run_ref, attempt=2, status="success", latency_ms=160.0)
            )
        timeout_run = f"retry_{uuid.uuid4().hex[:18]}"
        rows.append(
            _row(
                run_ref=timeout_run,
                attempt=1,
                status="timeout",
                retry_reason="timeout",
                error_class="timeout",
                latency_ms=3000.0,
            )
        )
        rows.append(_row(run_ref=timeout_run, attempt=2, status="success"))
        rows.append(_row(status="cancelled", retry_reason="none", latency_ms=None))
        rows.append(
            _row(status="error", retry_reason="none", error_class="provider_error")
        )
        await _seed_attempts(db_session, rows)

        response = await client.get(
            "/admin/analytics/ai-latency-retry?days=30", headers=headers
        )
        assert response.status_code == 200, response.text
        body = response.json()
        overall = body["overall"]
        assert overall["attempts"] == 14
        assert overall["successes"] == 6
        assert overall["errors"] == 6
        assert overall["timeouts"] == 1
        assert overall["cancelled"] == 1
        assert overall["retried_attempts"] == 6
        assert overall["retry_rate_pct"] == pytest.approx(42.86)
        assert overall["timeout_rate_pct"] == pytest.approx(7.14)
        assert overall["error_rate_pct"] == pytest.approx(42.86)

        reasons = {row["reason"]: row["attempts"] for row in body["retry_reasons"]}
        assert reasons == {"empty_output": 5, "timeout": 1}
        assert body["reconciliation"]["retry_reason_attempts"] == 6
        assert body["reconciliation"]["retry_reasons_reconcile"] is True
        assert body["reconciliation"]["status_attempts"] == 14
        assert body["reconciliation"]["statuses_reconcile"] is True
        assert body["reconciliation"]["all_dimensions_reconcile"] is True

    async def test_filters_narrow_all_dimensions(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        headers = await _admin_headers(db_session)
        await _seed_attempts(
            db_session,
            [
                _row(provider="openai", model="gpt-a", feature="resume_optimization", plan="pro"),
                _row(provider="openai", model="gpt-a", feature="resume_optimization", plan="pro"),
                _row(provider="anthropic", model="claude-a", feature="cover_letter", plan="free"),
                _row(provider="anthropic", model="claude-a", feature="cover_letter", plan="free"),
            ],
        )

        response = await client.get(
            "/admin/analytics/ai-latency-retry"
            "?days=30&plan=free&feature=cover_letter&provider=anthropic&model=claude-a",
            headers=headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["filters"] == {
            "plan": "free",
            "feature": "cover_letter",
            "provider": "anthropic",
            "model": "claude-a",
        }
        assert body["overall"]["attempts"] == 2
        assert {row["value"] for row in body["by_provider"]} == {"anthropic"}
        assert {row["value"] for row in body["by_plan"]} == {"free"}
        assert {row["value"] for row in body["by_feature"]} == {"cover_letter"}
        assert {row["value"] for row in body["by_model"]} == {"anthropic/claude-a"}


class TestAiLatencyPrivacyAndAccess:
    async def test_recorder_stores_only_bounded_error_class(
        self, db_session: AsyncSession
    ):
        row = await record_llm_attempt(
            db_session,
            provider="openai",
            model="gpt-4o-mini",
            feature="resume_optimization",
            plan="pro_monthly",
            run_id="job-user-document-123",
            attempt_number=1,
            status="error",
            retry_reason="none",
            latency_ms=10.0,
            exc=RuntimeError(SECRET_ERROR),
        )
        await db_session.commit()
        stored = await db_session.get(LLMCallAttempt, row.id)
        assert stored is not None
        assert stored.error_class == "provider_error"
        assert stored.plan == "pro"
        assert stored.run_ref != "job-user-document-123"
        assert SECRET_ERROR not in json.dumps(
            {column.name: str(getattr(stored, column.name)) for column in stored.__table__.columns}
        )

        payload = build_attempt(
            provider="openai",
            model="m",
            feature="f",
            plan="pro",
            status="timeout",
            latency_ms=12.5,
            exc=TimeoutError(SECRET_ERROR),
        )
        assert payload["status"] == "timeout"
        assert payload["error_class"] == "timeout"
        assert payload["retry_reason"] == "timeout"
        assert classify_exception(RuntimeError(SECRET_ERROR))[1] == "provider_error"

    async def test_response_never_exposes_raw_errors_or_run_references(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        headers = await _admin_headers(db_session)
        run_ref = f"run_secret_{uuid.uuid4().hex}"
        await _seed_attempts(
            db_session,
            [
                _row(
                    run_ref=run_ref,
                    status="error",
                    retry_reason="provider_error",
                    error_class="provider_error",
                )
            ],
        )
        response = await client.get(
            "/admin/analytics/ai-latency-retry?days=30", headers=headers
        )
        assert response.status_code == 200, response.text
        assert run_ref not in response.text
        assert SECRET_ERROR not in response.text
        body = response.json()
        assert body["privacy"]["aggregate_only"] is True
        assert body["privacy"]["per_user_rows"] is False
        assert body["privacy"]["per_row_records"] is False

    async def test_report_is_admin_only(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_headers = await _headers(db_session, await _create_user(db_session))
        forbidden = await client.get(
            "/admin/analytics/ai-latency-retry?days=30", headers=user_headers
        )
        assert forbidden.status_code == 403

        anonymous = await client.get("/admin/analytics/ai-latency-retry?days=30")
        assert anonymous.status_code == 401
