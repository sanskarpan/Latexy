"""Tests for Feature 52: Resume Score History endpoint."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.main import app


@pytest.fixture
def mock_user_id():
    return "test-user-123"


@pytest.fixture
def mock_resume_id():
    return "test-resume-456"


def make_optimization(resume_id: str, user_id: str, ats_score: float, days_ago: int, label: str | None = None):
    opt = MagicMock()
    opt.id = f"opt-{days_ago}"
    opt.resume_id = resume_id
    opt.user_id = user_id
    opt.ats_score = ats_score
    opt.checkpoint_label = label
    opt.created_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    opt.changes_made = []
    opt.tokens_used = 500
    return opt


@pytest.mark.asyncio
async def test_score_history_returns_entries_asc(mock_user_id, mock_resume_id):
    """Three optimization runs → 3 entries sorted ASC by timestamp."""
    rows = [
        make_optimization(mock_resume_id, mock_user_id, 65.0, 10, "Initial"),
        make_optimization(mock_resume_id, mock_user_id, 72.0, 5, "After tweak"),
        make_optimization(mock_resume_id, mock_user_id, 80.0, 1, "Final"),
    ]

    async def mock_get_db():
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = rows
        db.execute = AsyncMock(return_value=result)
        yield db

    with (
        patch("app.api.resume_routes.get_db", mock_get_db),
        patch(
            "app.middleware.auth_middleware.get_current_user_required",
            return_value=mock_user_id,
        ),
    ):
        async with AsyncClient(app=app, base_url="http://test") as client:
            client.headers["Authorization"] = "Bearer test-token"
            resp = await client.get(f"/resumes/{mock_resume_id}/score-history")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    # Should be oldest first (the mock already returns them in order)
    assert data[0]["ats_score"] == 65.0
    assert data[0]["label"] == "Initial"
    assert data[2]["ats_score"] == 80.0


@pytest.mark.asyncio
async def test_score_history_empty_when_no_optimizations(mock_user_id, mock_resume_id):
    """No optimizations → empty list, not a 500."""

    async def mock_get_db():
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result)
        yield db

    with (
        patch("app.api.resume_routes.get_db", mock_get_db),
        patch(
            "app.middleware.auth_middleware.get_current_user_required",
            return_value=mock_user_id,
        ),
    ):
        async with AsyncClient(app=app, base_url="http://test") as client:
            client.headers["Authorization"] = "Bearer test-token"
            resp = await client.get(f"/resumes/{mock_resume_id}/score-history")

    assert resp.status_code == 200
    assert resp.json() == []
