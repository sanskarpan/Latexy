"""
Layer 2 — Deep Analysis endpoint tests.

Covers:
- Blank latex → 400
- Anonymous without device_fingerprint → 401
- Trial gating: 2 uses then 402
- Valid anonymous submission → 200 with job_id
- Authenticated user → unlimited (no uses_remaining)
"""

import pytest
import uuid
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock, MagicMock


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
        "app.api.ats_routes.deep_analyze_ats_task",
        new_callable=MagicMock,
    ) as mock:
        mock.apply_async = MagicMock(return_value=MagicMock(id="fake-task-id"))
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
        from app.database.models import DeepAnalysisTrial
        from datetime import datetime, timezone

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
