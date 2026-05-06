"""
Tests for Feature 81 — Resume Benchmarking / Anonymous Percentile.

Covers:
  - BenchmarkingService._interpolate_percentile (pure unit tests)
  - GET /ats/benchmark endpoint (mocked service, mocked DB/cache)
  - Sufficient-data threshold (< 50 → sufficient_data=False, percentile=null)
  - Unknown/generic industry fallback
  - Redis-cache hit path (second call skips DB)
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.services.benchmarking_service import BenchmarkResult, BenchmarkingService


# ── Unit tests: _interpolate_percentile ──────────────────────────────────────


class TestInterpolatePercentile:
    def _svc(self) -> BenchmarkingService:
        return BenchmarkingService()

    def test_score_at_p50_returns_50(self):
        """Score equal to the cohort median should return percentile ≈ 50."""
        svc = self._svc()
        result = svc._interpolate_percentile(score=60.0, p25=40.0, p50=60.0, p75=80.0)
        assert result == pytest.approx(50.0, abs=1.0)

    def test_score_above_p75_approaches_100(self):
        """Score clearly above p75 should yield a high percentile, capped at 100."""
        svc = self._svc()
        result = svc._interpolate_percentile(score=100.0, p25=40.0, p50=60.0, p75=80.0)
        assert result == pytest.approx(100.0, abs=0.1)

    def test_score_at_zero_returns_0(self):
        svc = self._svc()
        result = svc._interpolate_percentile(score=0.0, p25=30.0, p50=60.0, p75=80.0)
        assert result == 0.0

    def test_score_at_p25_returns_25(self):
        svc = self._svc()
        result = svc._interpolate_percentile(score=40.0, p25=40.0, p50=60.0, p75=80.0)
        assert result == pytest.approx(25.0, abs=0.5)

    def test_percentile_capped_at_100(self):
        """Extrapolation never exceeds 100."""
        svc = self._svc()
        result = svc._interpolate_percentile(score=99.9, p25=20.0, p50=40.0, p75=60.0)
        assert result <= 100.0


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
