"""
Resume benchmarking service — anonymous percentile computation (Feature 81).

Queries the latest valid ATS score for each distinct resume and computes exact,
tie-aware percentile stats against that global cohort. Results are Redis-cached
per normalized score for 1 hour to avoid repeated expensive queries.

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
    cohort_label: str = "Latexy resume cohort"
    methodology: str = "Latest scored optimization per distinct resume"


class BenchmarkingService:
    """Compute anonymous ATS-score percentile ranks against the Latexy cohort."""

    async def compute_percentile(
        self,
        ats_score: float,
        industry: str,
        db: AsyncSession,
    ) -> BenchmarkResult:
        """
        Return the percentile rank of `ats_score` within the GLOBAL cohort.

        Industry is accepted for backwards-compatible request correlation, but
        it does not select the cohort: optimization rows do not currently store
        a trustworthy industry dimension. Responses label this honestly as the
        global Latexy cohort.

        Returns BenchmarkResult with sufficient_data=False when the cohort is
        too small (< MIN_SAMPLE_SIZE) to produce meaningful percentile stats.
        """
        normalized_score = round(float(ats_score), 1)
        cache_key = f"benchmark:cohort:v2:all:score:{normalized_score:.1f}"

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
                    WITH latest_resume_scores AS (
                        SELECT DISTINCT ON (resume_id)
                            resume_id,
                            ats_score
                        FROM optimizations
                        WHERE ats_score BETWEEN 0 AND 100
                        ORDER BY resume_id, created_at DESC, id DESC
                    )
                    SELECT
                        COUNT(*) AS sample_size,
                        percentile_cont(0.25) WITHIN GROUP (ORDER BY ats_score) AS p25,
                        percentile_cont(0.5) WITHIN GROUP (ORDER BY ats_score) AS p50,
                        percentile_cont(0.75) WITHIN GROUP (ORDER BY ats_score) AS p75,
                        COUNT(*) FILTER (WHERE ats_score < :score) AS lower_count,
                        COUNT(*) FILTER (WHERE ats_score = :score) AS equal_count
                    FROM latest_resume_scores
                    """
                ),
                {"score": normalized_score},
            )
            row = result.fetchone()
        except Exception as exc:
            logger.warning("Benchmark DB query failed", extra={"error_type": type(exc).__name__})
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
                message="Not enough data yet for benchmarking (global cohort)",
            )

        stats = {
            "sample_size": int(row.sample_size),
            "p25": float(row.p25) if row.p25 is not None else None,
            "p50": float(row.p50) if row.p50 is not None else None,
            "p75": float(row.p75) if row.p75 is not None else None,
            "percentile": self._percentile_from_counts(
                int(row.lower_count),
                int(row.equal_count),
                int(row.sample_size),
            ),
        }

        # Cache exact cohort stats for this normalized score.
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
                message="Not enough data yet for benchmarking (global cohort)",
            )

        percentile = float(stats.get("percentile", 0.0))

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
    def _percentile_from_counts(lower_count: int, equal_count: int, sample_size: int) -> float:
        """Midrank percentile; ties share the middle of their occupied ranks."""
        if sample_size <= 0:
            return 0.0
        result = 100.0 * (lower_count + (equal_count / 2.0)) / sample_size
        return round(max(0.0, min(100.0, result)), 1)


benchmarking_service = BenchmarkingService()
