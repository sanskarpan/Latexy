"""
Resume benchmarking service — anonymous percentile computation (Feature 81).

Queries the `optimizations` table for ATS scores and computes percentile stats
against all recorded optimization runs. Results are Redis-cached per industry
key for 1 hour to avoid repeated expensive queries.

Privacy: only aggregate statistics are computed; no individual resume data is
ever returned.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.redis import cache_manager

logger = logging.getLogger(__name__)

# Minimum cohort size before returning meaningful data
MIN_SAMPLE_SIZE = 50
CACHE_TTL_SECONDS = 3600  # 1 hour


@dataclass
class BenchmarkResult:
    percentile: Optional[float]  # 0–100; None if insufficient data
    sample_size: int
    cohort_median: Optional[float]
    cohort_p25: Optional[float]
    cohort_p75: Optional[float]
    industry: str
    sufficient_data: bool
    message: Optional[str] = None


class BenchmarkingService:
    """Compute anonymous ATS-score percentile ranks against the Latexy cohort."""

    async def compute_percentile(
        self,
        ats_score: float,
        industry: str,
        db: AsyncSession,
    ) -> BenchmarkResult:
        """
        Return the percentile rank of `ats_score` within the global cohort.

        `industry` is used as a label (and Redis cache key) but does not
        filter the query — industry data is not stored per-optimization in the
        current schema.  When sufficient per-industry data is available in a
        future migration, the WHERE clause can be narrowed.

        Returns BenchmarkResult with sufficient_data=False when the cohort is
        too small (< MIN_SAMPLE_SIZE) to produce meaningful percentile stats.
        """
        cache_key = f"benchmark:cohort:v1:{industry or 'all'}"

        # ── Try Redis cache first ──────────────────────────────────────────
        try:
            cached = await cache_manager.get(cache_key)
            if cached and isinstance(cached, dict) and cached.get("sample_size", 0) > 0:
                return self._build_result(ats_score, industry, cached)
        except Exception:
            pass

        # ── Query DB for cohort distribution stats ─────────────────────────
        try:
            result = await db.execute(
                text(
                    """
                    SELECT
                        COUNT(*)                                                     AS sample_size,
                        percentile_cont(0.25) WITHIN GROUP (ORDER BY ats_score)     AS p25,
                        percentile_cont(0.5)  WITHIN GROUP (ORDER BY ats_score)     AS p50,
                        percentile_cont(0.75) WITHIN GROUP (ORDER BY ats_score)     AS p75
                    FROM optimizations
                    WHERE ats_score IS NOT NULL
                    """
                )
            )
            row = result.fetchone()
        except Exception as exc:
            logger.warning("Benchmark DB query failed: %s", exc)
            return BenchmarkResult(
                percentile=None,
                sample_size=0,
                cohort_median=None,
                cohort_p25=None,
                cohort_p75=None,
                industry=industry,
                sufficient_data=False,
                message="Benchmark data temporarily unavailable",
            )

        if not row or row.sample_size == 0:
            return BenchmarkResult(
                percentile=None,
                sample_size=0,
                cohort_median=None,
                cohort_p25=None,
                cohort_p75=None,
                industry=industry,
                sufficient_data=False,
                message=f"Not enough data yet for {industry} benchmarking",
            )

        stats = {
            "sample_size": int(row.sample_size),
            "p25": float(row.p25) if row.p25 is not None else None,
            "p50": float(row.p50) if row.p50 is not None else None,
            "p75": float(row.p75) if row.p75 is not None else None,
        }

        # Cache cohort stats (score-independent — cache once, reuse for all scores)
        try:
            await cache_manager.set(cache_key, stats, ttl=CACHE_TTL_SECONDS)
        except Exception:
            pass

        return self._build_result(ats_score, industry, stats)

    # ── Private helpers ────────────────────────────────────────────────────────

    def _build_result(
        self, ats_score: float, industry: str, stats: dict
    ) -> BenchmarkResult:
        """Compute BenchmarkResult from cached/queried cohort stats."""
        sample_size = stats.get("sample_size", 0)
        p25 = stats.get("p25")
        p50 = stats.get("p50")
        p75 = stats.get("p75")

        sufficient = sample_size >= MIN_SAMPLE_SIZE and p50 is not None

        if not sufficient:
            return BenchmarkResult(
                percentile=None,
                sample_size=sample_size,
                cohort_median=p50,
                cohort_p25=p25,
                cohort_p75=p75,
                industry=industry,
                sufficient_data=False,
                message=f"Not enough data yet for {industry} benchmarking",
            )

        percentile = self._interpolate_percentile(
            score=ats_score,
            p25=float(p25),
            p50=float(p50),
            p75=float(p75 or p50),
        )

        return BenchmarkResult(
            percentile=percentile,
            sample_size=sample_size,
            cohort_median=float(p50),
            cohort_p25=float(p25) if p25 is not None else None,
            cohort_p75=float(p75) if p75 is not None else None,
            industry=industry,
            sufficient_data=True,
        )

    @staticmethod
    def _interpolate_percentile(
        score: float, p25: float, p50: float, p75: float
    ) -> float:
        """
        Estimate the percentile rank of `score` via piecewise linear interpolation
        on the quartile distribution: (0→p25), (p25→50%), (p50→75%), (p75→100%).
        """
        if score <= 0.0:
            return 0.0
        if score >= 100.0:
            return 100.0

        if p25 <= 0.0:
            p25 = 1.0  # avoid division by zero

        if score <= p25:
            result = 25.0 * (score / p25)
        elif score <= p50:
            span = p50 - p25
            result = 25.0 + (25.0 * ((score - p25) / span) if span > 0 else 0.0)
        elif score <= p75:
            span = p75 - p50
            result = 50.0 + (25.0 * ((score - p50) / span) if span > 0 else 0.0)
        else:
            # Above p75 — extrapolate towards 100
            remaining = 100.0 - p75
            result = 75.0 + (25.0 * min(1.0, (score - p75) / remaining) if remaining > 0 else 25.0)

        return round(max(0.0, min(100.0, result)), 1)


benchmarking_service = BenchmarkingService()
