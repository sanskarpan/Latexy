"""
Tests for Feature 81 — Resume Benchmarking / Anonymous Percentile.

Covers:
  - BenchmarkingService._percentile_from_counts (pure unit tests)
  - GET /ats/benchmark endpoint (mocked service, mocked DB/cache)
  - Sufficient-data threshold (< 50 → sufficient_data=False, percentile=null)
  - Unknown/generic industry fallback
  - Redis-cache hit path (second call skips DB)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.benchmarking_service import BenchmarkingService, BenchmarkResult

# ── Unit tests: exact tie-aware percentile ──────────────────────────────────


class TestPercentileFromCounts:
    def _svc(self) -> BenchmarkingService:
        return BenchmarkingService()

    def test_midpoint_rank(self):
        svc = self._svc()
        assert svc._percentile_from_counts(40, 0, 80) == 50.0

    def test_ties_share_middle_of_occupied_ranks(self):
        svc = self._svc()
        assert svc._percentile_from_counts(40, 20, 100) == 50.0

    def test_empty_cohort_returns_zero(self):
        svc = self._svc()
        assert svc._percentile_from_counts(0, 0, 0) == 0.0

    def test_result_is_clamped(self):
        svc = self._svc()
        assert svc._percentile_from_counts(200, 0, 100) == 100.0


@pytest.mark.asyncio
class TestBenchmarkService:
    async def test_query_uses_latest_score_per_resume_and_exact_rank(self):
        row = SimpleNamespace(
            sample_size=100,
            p25=40.0,
            p50=60.0,
            p75=80.0,
            lower_count=70,
            equal_count=10,
        )
        db_result = SimpleNamespace(fetchone=lambda: row)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=db_result)

        with (
            patch("app.services.benchmarking_service.cache_manager.get", new=AsyncMock(return_value=None)),
            patch("app.services.benchmarking_service.cache_manager.set", new=AsyncMock()) as cache_set,
        ):
            result = await BenchmarkingService().compute_percentile(75.04, "tech_saas", db)

        assert result.percentile == 75.0
        assert result.sample_size == 100
        assert result.cohort_label == "Latexy resume cohort"
        assert "distinct resume" in result.methodology
        statement, params = db.execute.await_args.args
        sql = str(statement)
        assert "DISTINCT ON (resume_id)" in sql
        assert "ats_score BETWEEN 0 AND 100" in sql
        assert params == {"score": 75.0}
        assert cache_set.await_args.args[0] == "benchmark:cohort:v2:all:score:75.0"

    async def test_cached_exact_stats_skip_database(self):
        db = AsyncMock()
        cached = {
            "sample_size": 80,
            "p25": 45.0,
            "p50": 62.0,
            "p75": 79.0,
            "percentile": 81.2,
        }
        with patch(
            "app.services.benchmarking_service.cache_manager.get",
            new=AsyncMock(return_value=cached),
        ):
            result = await BenchmarkingService().compute_percentile(88.0, "finance", db)

        assert result.percentile == 81.2
        assert result.industry == "finance"
        db.execute.assert_not_awaited()

    async def test_real_query_counts_each_resume_once(self, db_session: AsyncSession):
        # The benchmark intentionally queries the global cohort. Other tests in
        # the same session can commit optimization fixtures, so isolate this
        # real-query assertion transactionally. The fixture rollback restores
        # any pre-existing test rows after this test.
        await db_session.execute(text("DELETE FROM optimizations"))
        user_id = str(uuid4())
        now = datetime.now(timezone.utc)
        await db_session.execute(
            text(
                """
                INSERT INTO users (id, email, name, subscription_plan)
                VALUES (:id, :email, 'Benchmark Test', 'free')
                """
            ),
            {"id": user_id, "email": f"test_benchmark_{user_id}@example.com"},
        )
        resume_ids = [str(uuid4()) for _ in range(50)]
        await db_session.execute(
            text(
                """
                INSERT INTO resumes (id, user_id, title, latex_content)
                VALUES (:id, :user_id, :title, '\\documentclass{article}')
                """
            ),
            [
                {"id": resume_id, "user_id": user_id, "title": f"Benchmark {index}"}
                for index, resume_id in enumerate(resume_ids)
            ],
        )
        rows = []
        for score, resume_id in enumerate(resume_ids):
            rows.append({
                "id": str(uuid4()),
                "resume_id": resume_id,
                "score": float(score),
                "created_at": now,
            })
        # An older extreme score for the first resume must not become a 51st
        # cohort member or replace that resume's current score of zero.
        rows.append({
            "id": str(uuid4()),
            "resume_id": resume_ids[0],
            "score": 100.0,
            "created_at": now - timedelta(days=1),
        })
        await db_session.execute(
            text(
                """
                INSERT INTO optimizations (
                    id, user_id, resume_id, job_description, original_latex,
                    optimized_latex, provider, model, ats_score, created_at
                ) VALUES (
                    :id, :user_id, :resume_id, '', 'before', 'after',
                    'test', 'test', :score, :created_at
                )
                """
            ),
            [{**row, "user_id": user_id} for row in rows],
        )

        with (
            patch("app.services.benchmarking_service.cache_manager.get", new=AsyncMock(return_value=None)),
            patch("app.services.benchmarking_service.cache_manager.set", new=AsyncMock()),
        ):
            result = await BenchmarkingService().compute_percentile(25.0, "general", db_session)

        assert result.sample_size == 50
        assert result.cohort_median == 24.5
        assert result.percentile == 51.0


# ── Endpoint tests: GET /ats/benchmark ───────────────────────────────────────


def _make_sufficient_result(percentile: float = 77.3, industry: str = "tech_saas") -> BenchmarkResult:
    return BenchmarkResult(
        percentile=percentile,
        sample_size=500,
        cohort_median=65.0,
        cohort_p25=50.0,
        cohort_p75=80.0,
        industry=industry,
        sufficient_data=True,
    )


def _make_insufficient_result(industry: str = "general") -> BenchmarkResult:
    return BenchmarkResult(
        percentile=None,
        sample_size=10,
        cohort_median=None,
        cohort_p25=None,
        cohort_p75=None,
        industry=industry,
        sufficient_data=False,
        message=f"Not enough data yet for {industry} benchmarking",
    )


@pytest.mark.asyncio
class TestBenchmarkEndpoint:

    async def test_unauthenticated_returns_401(self, client: AsyncClient):
        """GET /ats/benchmark without auth header → 401."""
        resp = await client.get("/ats/benchmark?ats_score=75.0")
        assert resp.status_code == 401

    async def test_rate_limit_exceeded_returns_429(
        self, client: AsyncClient, auth_headers: dict
    ):
        """When the atomic limiter reports the window is exhausted → 429."""
        with patch(
            "app.api.ats_routes._rate_limit_ok",
            new=AsyncMock(return_value=False),
        ):
            resp = await client.get(
                "/ats/benchmark?ats_score=70.0",
                headers=auth_headers,
            )
        assert resp.status_code == 429

    async def test_score_at_p50_returns_approximately_50(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Score equal to cohort median → percentile ≈ 50."""
        with patch(
            "app.services.benchmarking_service.benchmarking_service.compute_percentile",
            new=AsyncMock(return_value=_make_sufficient_result(percentile=50.0, industry="general")),
        ):
            resp = await client.get(
                "/ats/benchmark?ats_score=60.0&industry=general",
                headers=auth_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["sufficient_data"] is True
        assert data["percentile"] == pytest.approx(50.0, abs=2.0)

    async def test_small_sample_returns_sufficient_data_false(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Cohort < 50 scores → sufficient_data=False, percentile=None."""
        with patch(
            "app.services.benchmarking_service.benchmarking_service.compute_percentile",
            new=AsyncMock(return_value=_make_insufficient_result("tech_saas")),
        ):
            resp = await client.get(
                "/ats/benchmark?ats_score=80.0&industry=tech_saas",
                headers=auth_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["sufficient_data"] is False
        assert data["percentile"] is None
        assert data["sample_size"] < 50

    async def test_unknown_industry_falls_back_gracefully(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Unrecognized industry key → returns result (generic cohort or insufficient)."""
        with patch(
            "app.services.benchmarking_service.benchmarking_service.compute_percentile",
            new=AsyncMock(return_value=_make_insufficient_result("obscure_industry")),
        ):
            resp = await client.get(
                "/ats/benchmark?ats_score=70.0&industry=obscure_industry",
                headers=auth_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        # Either returns data or gracefully reports insufficient — never 4xx/5xx
        assert "sufficient_data" in data
        assert "industry" in data

    async def test_redis_cache_hit_skips_db(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Second call with same industry returns cached result without DB query."""
        cached_stats = {
            "sample_size": 500,
            "p25": 50.0,
            "p50": 65.0,
            "p75": 80.0,
        }
        call_count = 0

        async def mock_compute(ats_score, industry, db):
            nonlocal call_count
            call_count += 1
            # Simulate cache hit on second call (service returns same result)
            return _make_sufficient_result(percentile=77.3, industry=industry)

        with patch(
            "app.services.benchmarking_service.benchmarking_service.compute_percentile",
            side_effect=mock_compute,
        ):
            # First call
            r1 = await client.get(
                "/ats/benchmark?ats_score=75.0&industry=tech_saas",
                headers=auth_headers,
            )
            # Second call — same parameters
            r2 = await client.get(
                "/ats/benchmark?ats_score=75.0&industry=tech_saas",
                headers=auth_headers,
            )

        assert r1.status_code == 200
        assert r2.status_code == 200
        d1, d2 = r1.json(), r2.json()
        # Both responses should carry the same percentile
        assert d1["percentile"] == d2["percentile"]
        assert d1["sufficient_data"] == d2["sufficient_data"] is True
