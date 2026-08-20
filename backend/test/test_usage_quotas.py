"""Per-plan usage quota metering (the money meter).

Covers the numeric layer of the entitlement engine:
  * config.get_plan_quota / get_plan_quota_window — the allowance table
  * entitlement_service.consume_quota / refund_quota / enforce_quota
  * atomicity under a concurrent burst (no read-modify-write race)
  * fail-CLOSED when the counter store is unavailable
  * route enforcement on /jobs/submit and the previously-anonymous /optimize

Counters live in Redis under ``latexy:quota:{dimension}:{user_id}:{period}``,
where the period is the UTC day (``YYYYMMDD``) or month (``YYYYMM``) depending
on the plan/dimension window.
Every test uses a fresh random user id, so no cleanup between tests is needed.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_plan_quota, get_plan_quota_window
from app.services.entitlement_service import entitlement_service

VALID_LATEX = r"""
\documentclass[letterpaper,11pt]{article}
\begin{document}
\section*{Skills}
Python, TypeScript, Docker
\end{document}
"""


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _create_user(db: AsyncSession, plan: str = "free") -> str:
    user_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, email_verified, subscription_plan, "
            "subscription_status, trial_used) "
            "VALUES (:id, :email, 'Quota User', true, :plan, 'active', false)"
        ),
        {"id": user_id, "email": f"test_{user_id.replace('-', '')}@example.com", "plan": plan},
    )
    await db.commit()
    return user_id


async def _headers(db: AsyncSession, user_id: str) -> dict:
    token = f"test_sess_{uuid.uuid4().hex}"
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


# ── Allowance table ──────────────────────────────────────────────────────────

class TestPlanQuotaTable:

    def test_free_is_generous_and_beats_the_anonymous_trial(self):
        # Signing up must always be an UPGRADE over browsing anonymously, which
        # is capped at trial_service.TRIAL_LIMIT uses per device.
        from app.services.trial_service import TRIAL_LIMIT

        assert get_plan_quota("free", "compilations") == 10
        assert get_plan_quota("free", "optimizations") == 3
        assert get_plan_quota("free", "ai_assists") == 25
        for dimension in ("compilations", "optimizations", "ai_assists"):
            assert get_plan_quota("free", dimension) >= TRIAL_LIMIT, dimension

    def test_free_compilations_reset_daily_not_monthly(self):
        # A burst of edits must not lock a free user out for the rest of the month.
        assert get_plan_quota_window("free", "compilations") == "day"
        assert get_plan_quota_window("free", "optimizations") == "month"
        assert get_plan_quota_window("basic", "compilations") == "month"

    def test_advertised_copy_is_generated_from_the_enforced_table(self):
        # SUBSCRIPTION_PLANS is pricing copy only — it is rewritten from
        # PLAN_QUOTAS at import so it can never advertise an unenforced number.
        from app.core.config import get_plan_config

        assert get_plan_config("free")["features"]["compilations"] == "10 / day"
        assert get_plan_config("free")["features"]["optimizations"] == "3 / month"
        assert get_plan_config("basic")["features"]["compilations"] == "400 / month"
        assert get_plan_config("pro")["features"]["compilations"] == "unlimited"

    def test_basic_matches_advertised_plan(self):
        assert get_plan_quota("basic", "compilations") == 400
        assert get_plan_quota("basic", "optimizations") == 10
        assert get_plan_quota("basic_annual", "optimizations") == 10

    def test_basic_compilations_is_not_a_downgrade_from_free(self):
        # B3/#1283 regression guard: the first PAID tier must never grant a
        # lower effective monthly compile allowance than the free tier does.
        # Free is metered per DAY, so its worst-case monthly equivalent is
        # ~31 * daily limit; Basic (a paid, monthly-windowed plan) must clear
        # that bar, or paying becomes a downgrade on the headline metric.
        free_daily = get_plan_quota("free", "compilations")
        assert get_plan_quota_window("free", "compilations") == "day"
        free_monthly_equivalent = free_daily * 31

        basic_monthly = get_plan_quota("basic", "compilations")
        assert get_plan_quota_window("basic", "compilations") == "month"

        assert basic_monthly is not None
        assert basic_monthly >= free_monthly_equivalent, (
            f"basic compilations quota ({basic_monthly}/month) must be >= "
            f"free's 31-day equivalent ({free_monthly_equivalent}) — paying "
            "must never grant fewer compiles than staying free."
        )

    @pytest.mark.parametrize("plan", ["pro", "pro_annual", "byok", "team", "student"])
    def test_paid_unlimited_is_none(self, plan):
        assert get_plan_quota(plan, "compilations") is None
        assert get_plan_quota(plan, "optimizations") is None

    def test_unknown_plan_falls_back_to_free(self):
        assert get_plan_quota("not_a_plan", "compilations") == 10
        assert get_plan_quota(None, "compilations") == 10

    def test_unknown_dimension_raises(self):
        # A typo must fail loudly, never silently grant unlimited usage.
        with pytest.raises(KeyError):
            get_plan_quota("free", "widgets")


# ── consume / refund / enforce ───────────────────────────────────────────────

@pytest.mark.asyncio
class TestConsumeQuota:

    async def test_counts_up_then_denies(self):
        limit = get_plan_quota("free", "compilations")
        user_id = str(uuid.uuid4())
        results = [
            await entitlement_service.consume_quota(
                "compilations", user_id=user_id, plan="free"
            )
            for _ in range(limit + 1)
        ]
        assert [r.allowed for r in results] == [True] * limit + [False]
        assert [r.used for r in results[:limit]] == list(range(1, limit + 1))
        assert results[-1].remaining == 0

    async def test_rejected_attempt_does_not_inflate_counter(self):
        limit = get_plan_quota("free", "compilations")
        user_id = str(uuid.uuid4())
        for _ in range(limit + 3):
            await entitlement_service.consume_quota(
                "compilations", user_id=user_id, plan="free"
            )
        snapshot = await entitlement_service.quota_snapshot(user_id, "free")
        assert snapshot["dimensions"]["compilations"]["used"] == limit

    async def test_unlimited_plan_never_denied_but_still_counted(self):
        user_id = str(uuid.uuid4())
        for _ in range(5):
            ticket = await entitlement_service.consume_quota(
                "compilations", user_id=user_id, plan="pro"
            )
            assert ticket.allowed is True
            assert ticket.limit is None
        assert ticket.used == 5
        assert ticket.remaining is None

    async def test_free_optimizations_are_scarce_but_not_zero(self):
        # Registering must never REMOVE a capability the anonymous visitor had.
        user_id = str(uuid.uuid4())
        tickets = [
            await entitlement_service.consume_quota(
                "optimizations", user_id=user_id, plan="free"
            )
            for _ in range(4)
        ]
        assert [t.allowed for t in tickets] == [True, True, True, False]
        assert tickets[0].limit == 3
        assert tickets[0].window == "month"

    async def test_daily_and_monthly_dimensions_use_different_period_keys(self):
        user_id = str(uuid.uuid4())
        compile_ticket = await entitlement_service.consume_quota(
            "compilations", user_id=user_id, plan="free"
        )
        optimize_ticket = await entitlement_service.consume_quota(
            "optimizations", user_id=user_id, plan="free"
        )
        assert compile_ticket.window == "day"
        assert len(compile_ticket.period) == 8  # YYYYMMDD
        assert optimize_ticket.window == "month"
        assert len(optimize_ticket.period) == 6  # YYYYMM

    async def test_refund_returns_the_unit(self):
        user_id = str(uuid.uuid4())
        ticket = await entitlement_service.consume_quota(
            "compilations", user_id=user_id, plan="free"
        )
        await entitlement_service.refund_quota(ticket)
        snapshot = await entitlement_service.quota_snapshot(user_id, "free")
        assert snapshot["dimensions"]["compilations"]["used"] == 0

    async def test_concurrent_burst_cannot_exceed_the_allowance(self):
        # A simultaneous burst well past the allowance: an atomic INCR must
        # hand out exactly ``limit`` slots, never more.
        user_id = str(uuid.uuid4())
        limit = get_plan_quota("free", "compilations")
        tickets = await asyncio.gather(
            *[
                entitlement_service.consume_quota(
                    "compilations", user_id=user_id, plan="free"
                )
                for _ in range(limit + 17)
            ]
        )
        assert sum(1 for t in tickets if t.allowed) == limit

    async def test_separate_dimensions_do_not_share_a_counter(self):
        user_id = str(uuid.uuid4())
        await entitlement_service.consume_quota("compilations", user_id=user_id, plan="free")
        snapshot = await entitlement_service.quota_snapshot(user_id, "free")
        assert snapshot["dimensions"]["compilations"]["used"] == 1
        assert snapshot["dimensions"]["ai_assists"]["used"] == 0

    async def test_snapshot_reports_period_and_reset(self):
        snapshot = await entitlement_service.quota_snapshot(str(uuid.uuid4()), "free")
        assert snapshot["period"] == datetime.now(timezone.utc).strftime("%Y%m")
        # Resets at midnight UTC on the 1st of the following month.
        resets = datetime.fromisoformat(snapshot["resets_at"])
        assert resets.day == 1 and resets.hour == 0

        # Each dimension carries its own window/reset — free compiles are daily.
        compilations = snapshot["dimensions"]["compilations"]
        assert compilations["window"] == "day"
        tomorrow = datetime.now(timezone.utc).date() + timedelta(days=1)
        assert datetime.fromisoformat(compilations["resets_at"]).date() == tomorrow


@pytest.mark.asyncio
class TestEnforceQuota:

    async def test_raises_402_with_error_envelope(self):
        from fastapi import HTTPException

        user_id = str(uuid.uuid4())
        limit = get_plan_quota("free", "optimizations")
        for _ in range(limit):
            await entitlement_service.enforce_quota(
                "optimizations", user_id=user_id, plan="free"
            )
        with pytest.raises(HTTPException) as exc:
            await entitlement_service.enforce_quota(
                "optimizations", user_id=user_id, plan="free"
            )
        assert exc.value.status_code == 402
        error = exc.value.detail["error"]
        assert error["code"] == "quota_exceeded"
        assert error["details"]["dimension"] == "optimizations"
        assert error["details"]["limit"] == limit
        assert error["details"]["plan_family"] == "free"
        assert error["details"]["window"] == "month"
        assert error["details"]["resets_at"]

    async def test_fails_closed_when_counter_store_is_down(self, monkeypatch):
        # No counter => no accounting => we must NOT hand out paid resources.
        from fastapi import HTTPException

        import app.core.redis as core_redis

        async def _boom():
            raise RuntimeError("redis down")

        monkeypatch.setattr(core_redis, "get_redis_cache_client", _boom)

        ticket = await entitlement_service.consume_quota(
            "compilations", user_id=str(uuid.uuid4()), plan="free"
        )
        assert ticket.allowed is False
        assert ticket.unavailable is True

        with pytest.raises(HTTPException) as exc:
            await entitlement_service.enforce_quota(
                "compilations", user_id=str(uuid.uuid4()), plan="free"
            )
        assert exc.value.status_code == 503
        assert exc.value.detail["error"]["code"] == "quota_unavailable"

    async def test_unlimited_plan_fails_open_when_counter_store_is_down(
        self, monkeypatch
    ):
        # Nothing to meter on an unlimited plan, so a counter outage must not
        # deny the highest-paying tiers on endpoints with no other Redis need.
        import app.core.redis as core_redis

        async def _boom():
            raise RuntimeError("redis down")

        monkeypatch.setattr(core_redis, "get_redis_cache_client", _boom)

        for plan in ("pro", "byok", "team"):
            assert get_plan_quota(plan, "compilations") is None, plan
            ticket = await entitlement_service.consume_quota(
                "compilations", user_id=str(uuid.uuid4()), plan=plan
            )
            assert ticket.allowed is True, plan
            assert ticket.unavailable is True
            assert ticket.limit is None

            # enforce_quota must let it through rather than raising 503.
            ticket = await entitlement_service.enforce_quota(
                "ai_assists", user_id=str(uuid.uuid4()), plan=plan
            )
            assert ticket.allowed is True


# ── Route enforcement ────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestJobSubmitQuota:

    async def test_free_user_blocked_only_at_the_daily_allowance(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        limit = get_plan_quota("free", "compilations")
        user_id = await _create_user(db_session, plan="free")
        headers = await _headers(db_session, user_id)
        body = {"job_type": "latex_compilation", "latex_content": VALID_LATEX}

        codes = []
        for _ in range(limit + 1):
            resp = await client.post("/jobs/submit", json=body, headers=headers)
            codes.append(resp.status_code)

        assert codes[:limit] == [200] * limit
        assert codes[limit] == 402
        body = resp.json()["error"]
        assert body["code"] == "quota_exceeded"
        assert body["details"]["window"] == "day"

    async def test_pro_user_gets_more_than_the_free_allowance(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id = await _create_user(db_session, plan="pro")
        headers = await _headers(db_session, user_id)
        body = {"job_type": "latex_compilation", "latex_content": VALID_LATEX}

        for _ in range(get_plan_quota("free", "compilations") + 3):
            resp = await client.post("/jobs/submit", json=body, headers=headers)
            assert resp.status_code == 200

    async def test_watermarked_compile_spends_the_same_meter(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        # /jobs/compile-watermarked runs the same pdflatex, so it must not be a
        # way around the compilations allowance.
        limit = get_plan_quota("free", "compilations")
        user_id = await _create_user(db_session, plan="free")
        headers = await _headers(db_session, user_id)
        body = {
            "latex_content": VALID_LATEX,
            "watermark": "DRAFT",
        }

        for _ in range(limit):
            resp = await client.post(
                "/jobs/compile-watermarked", json=body, headers=headers
            )
            assert resp.status_code == 200

        resp = await client.post("/jobs/compile-watermarked", json=body, headers=headers)
        assert resp.status_code == 402
        assert resp.json()["error"]["details"]["dimension"] == "compilations"

    async def test_anonymous_watermarked_compile_needs_a_fingerprint(
        self, client: AsyncClient
    ):
        resp = await client.post(
            "/jobs/compile-watermarked",
            json={"latex_content": VALID_LATEX, "watermark": "DRAFT"},
        )
        assert resp.status_code == 400

    async def test_free_user_can_run_optimizations_up_to_the_allowance(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        # A registered free user must never be worse off than an anonymous one.
        limit = get_plan_quota("free", "optimizations")
        user_id = await _create_user(db_session, plan="free")
        headers = await _headers(db_session, user_id)
        payload = {
            "job_type": "combined",
            "latex_content": VALID_LATEX,
            "job_description": "Senior backend engineer",
        }

        for _ in range(limit):
            resp = await client.post("/jobs/submit", json=payload, headers=headers)
            assert resp.status_code == 200

        resp = await client.post("/jobs/submit", json=payload, headers=headers)
        assert resp.status_code == 402
        assert resp.json()["error"]["details"]["dimension"] == "optimizations"

    async def test_rejected_request_does_not_burn_quota(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id = await _create_user(db_session, plan="free")
        headers = await _headers(db_session, user_id)

        # Missing latex_content → 422 before the meter runs.
        resp = await client.post(
            "/jobs/submit", json={"job_type": "latex_compilation"}, headers=headers
        )
        assert resp.status_code == 422

        snapshot = await entitlement_service.quota_snapshot(user_id, "free")
        assert snapshot["dimensions"]["compilations"]["used"] == 0

    async def test_anonymous_submit_is_not_plan_metered(
        self, client: AsyncClient
    ):
        # Anonymous callers are governed by the device trial, not a plan quota.
        fingerprint = f"test_fp_{uuid.uuid4().hex}"
        resp = await client.post(
            "/jobs/submit",
            json={
                "job_type": "latex_compilation",
                "latex_content": VALID_LATEX,
                "device_fingerprint": fingerprint,
            },
        )
        assert resp.status_code == 200
        snapshot = await entitlement_service.quota_snapshot(fingerprint, "free")
        assert snapshot["dimensions"]["compilations"]["used"] == 0


@pytest.mark.asyncio
class TestLegacyOptimizeEndpointsRequireAuth:
    """POST /optimize + /optimize-and-compile used to be open LLM endpoints."""

    @pytest.mark.parametrize("path", ["/optimize", "/optimize-and-compile"])
    async def test_anonymous_is_refused(self, client: AsyncClient, path: str):
        resp = await client.post(
            path,
            json={"latex_content": VALID_LATEX, "job_description": "Backend engineer"},
        )
        assert resp.status_code in (401, 403)

    async def test_authenticated_free_user_hits_the_optimization_quota(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id = await _create_user(db_session, plan="free")
        headers = await _headers(db_session, user_id)
        # Burn the monthly optimization allowance first — a free user is
        # entitled to a few real runs before the meter bites.
        for _ in range(get_plan_quota("free", "optimizations")):
            await entitlement_service.consume_quota(
                "optimizations", user_id=user_id, plan="free"
            )
        resp = await client.post(
            "/optimize",
            json={"latex_content": VALID_LATEX, "job_description": "Backend engineer"},
            headers=headers,
        )
        # 402 when the LLM service is configured, 503 when it is not — either way
        # the endpoint is no longer an anonymous, unmetered LLM call.
        assert resp.status_code in (402, 503)


@pytest.mark.asyncio
class TestEntitlementsEndpointExposesQuotas:

    async def test_authenticated_response_includes_quota_usage(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id = await _create_user(db_session, plan="basic")
        headers = await _headers(db_session, user_id)
        resp = await client.get("/config/entitlements", headers=headers)
        assert resp.status_code == 200
        quotas = resp.json()["quotas"]
        assert quotas["dimensions"]["optimizations"]["limit"] == 10
        assert quotas["dimensions"]["compilations"]["limit"] == 400
        assert quotas["dimensions"]["compilations"]["window"] == "month"

    async def test_anonymous_response_has_no_quotas(self, client: AsyncClient):
        resp = await client.get("/config/entitlements")
        assert resp.status_code == 200
        assert "quotas" not in resp.json()
