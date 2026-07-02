"""
Layer 2 — Deep Analysis endpoint tests.

Covers:
- Blank latex → 400
- Anonymous without device_fingerprint → 401
- Trial gating: 2 uses then 402
- Valid anonymous submission → 200 with job_id
- Authenticated user → unlimited (no uses_remaining)
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

# ── Helpers ──────────────────────────────────────────────────────────────────

SAMPLE_LATEX = r"""
\documentclass{article}
\begin{document}
\section{Experience}
\textbf{Engineer, Acme} --- 2020--2024
\begin{itemize}
  \item Built scalable microservices reducing latency by 40\%.
\end{itemize}
\section{Education}
B.Sc. Computer Science, MIT, 2019.
\end{document}
"""


async def _post_deep_analyze(client: AsyncClient, body: dict, headers: dict = {}):
    return await client.post("/ats/deep-analyze", json=body, headers=headers)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_celery_task():
    """Prevent actual Celery task dispatch during endpoint tests."""
    with patch(
        "app.api.ats_routes.submit_deep_analyze_ats",
        new_callable=MagicMock,
    ) as mock:
        yield mock


@pytest.fixture
def mock_redis():
    """Prevent Redis writes during tests."""
    with patch(
        "app.api.ats_routes.get_redis_client",
        new_callable=AsyncMock,
    ) as mock:
        r = AsyncMock()
        r.setex = AsyncMock()
        r.incr = AsyncMock(return_value=1)
        r.expire = AsyncMock()
        r.xadd = AsyncMock(return_value="1-1")
        r.publish = AsyncMock()
        mock.return_value = r
        yield r


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestDeepAnalyzeValidation:

    @pytest.mark.asyncio
    async def test_blank_latex_returns_400(self, client: AsyncClient):
        response = await _post_deep_analyze(client, {
            "latex_content": "   ",
            "device_fingerprint": "fp_test_001",
        })
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_latex_too_short_returns_422(self, client: AsyncClient):
        """Pydantic min_length=50 on latex_content."""
        response = await _post_deep_analyze(client, {
            "latex_content": "hi",
            "device_fingerprint": "fp_test_002",
        })
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_anonymous_no_fingerprint_returns_401(
        self, client: AsyncClient, mock_celery_task, mock_redis
    ):
        response = await _post_deep_analyze(client, {
            "latex_content": SAMPLE_LATEX,
        })
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_anonymous_with_fingerprint_succeeds(
        self, client: AsyncClient, mock_celery_task, mock_redis
    ):
        fp = f"fp_{uuid.uuid4().hex[:12]}"
        response = await _post_deep_analyze(client, {
            "latex_content": SAMPLE_LATEX,
            "device_fingerprint": fp,
        })
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["job_id"] is not None
        assert data["uses_remaining"] == 1  # 2 - 1 = 1 remaining after first use


class TestDeepAnalyzeTrial:

    @pytest.mark.asyncio
    async def test_trial_limit_enforced(
        self, client: AsyncClient, mock_celery_task, mock_redis, db_session
    ):
        """After 2 uses, next request returns 402."""
        from datetime import datetime, timezone

        from app.database.models import DeepAnalysisTrial

        fp = f"fp_{uuid.uuid4().hex[:12]}"

        # Pre-create a trial record at the limit
        trial = DeepAnalysisTrial(
            device_fingerprint=fp,
            usage_count=2,
            last_used=datetime.now(timezone.utc),
        )
        db_session.add(trial)
        await db_session.commit()

        response = await _post_deep_analyze(client, {
            "latex_content": SAMPLE_LATEX,
            "device_fingerprint": fp,
        })
        assert response.status_code == 402

    @pytest.mark.asyncio
    async def test_first_use_remaining_is_one(
        self, client: AsyncClient, mock_celery_task, mock_redis
    ):
        fp = f"fp_{uuid.uuid4().hex[:12]}"
        response = await _post_deep_analyze(client, {
            "latex_content": SAMPLE_LATEX,
            "device_fingerprint": fp,
        })
        assert response.status_code == 200
        data = response.json()
        assert data["uses_remaining"] == 1

    @pytest.mark.asyncio
    async def test_second_use_remaining_is_zero(
        self, client: AsyncClient, mock_celery_task, mock_redis, db_session
    ):
        from app.database.models import DeepAnalysisTrial

        fp = f"fp_{uuid.uuid4().hex[:12]}"

        # Pre-create trial with 1 use
        trial = DeepAnalysisTrial(device_fingerprint=fp, usage_count=1)
        db_session.add(trial)
        await db_session.commit()

        response = await _post_deep_analyze(client, {
            "latex_content": SAMPLE_LATEX,
            "device_fingerprint": fp,
        })
        assert response.status_code == 200
        data = response.json()
        assert data["uses_remaining"] == 0


class TestDeepAnalyzeAuthenticated:

    @pytest.mark.asyncio
    async def test_authenticated_user_no_uses_remaining_field(
        self, client: AsyncClient, mock_celery_task, mock_redis, auth_headers
    ):
        """Authenticated users get uses_remaining=null (unlimited)."""
        response = await _post_deep_analyze(
            client,
            {"latex_content": SAMPLE_LATEX},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["uses_remaining"] is None  # null = unlimited

    @pytest.mark.asyncio
    async def test_authenticated_no_fingerprint_needed(
        self, client: AsyncClient, mock_celery_task, mock_redis, auth_headers
    ):
        """Authenticated users don't need device_fingerprint."""
        response = await _post_deep_analyze(
            client,
            {"latex_content": SAMPLE_LATEX},
            headers=auth_headers,
        )
        assert response.status_code == 200


class TestDeepAnalyzeLimitsAndFailure:
    """Payload caps, anonymous IP rate limiting, and trial-charge rollback."""

    @pytest.mark.asyncio
    async def test_oversized_latex_returns_422(self, client: AsyncClient):
        """latex_content over 200_000 chars is rejected by validation."""
        response = await _post_deep_analyze(client, {
            "latex_content": "a" * 200_001,
            "device_fingerprint": "fp_big",
        })
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_oversized_job_description_returns_422(self, client: AsyncClient):
        """job_description over 20_000 chars is rejected by validation."""
        response = await _post_deep_analyze(client, {
            "latex_content": SAMPLE_LATEX,
            "job_description": "x" * 20_001,
            "device_fingerprint": "fp_jd_big",
        })
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_anonymous_ip_rate_limit_returns_429(
        self, client: AsyncClient, mock_celery_task, mock_redis
    ):
        """Anonymous deep-analysis is IP rate-limited regardless of the trial flag."""
        with patch(
            "app.api.ats_routes._rate_limit_ok",
            new=AsyncMock(return_value=False),
        ):
            response = await _post_deep_analyze(client, {
                "latex_content": SAMPLE_LATEX,
                "device_fingerprint": f"fp_{uuid.uuid4().hex[:12]}",
            })
        assert response.status_code == 429

    @pytest.mark.asyncio
    async def test_enqueue_failure_refunds_trial(
        self, client: AsyncClient, mock_redis, db_session
    ):
        """If task dispatch fails, the trial use charged before dispatch is refunded."""
        from sqlalchemy import select

        from app.database.models import DeepAnalysisTrial

        fp = f"fp_{uuid.uuid4().hex[:12]}"

        with patch(
            "app.api.ats_routes.submit_deep_analyze_ats",
            new=MagicMock(side_effect=RuntimeError("broker down")),
        ):
            response = await _post_deep_analyze(client, {
                "latex_content": SAMPLE_LATEX,
                "device_fingerprint": fp,
            })
        assert response.status_code == 503

        # Trial use should have been rolled back to 0 (charged then refunded)
        result = await db_session.execute(
            select(DeepAnalysisTrial).where(
                DeepAnalysisTrial.device_fingerprint == fp
            )
        )
        trial = result.scalar_one_or_none()
        assert trial is not None
        assert trial.usage_count == 0
