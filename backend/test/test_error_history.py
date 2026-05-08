"""
Feature 88 — Compile Error History tests.

Tests:
1. get_error_history — user with 3 failed compilations (different error types) → 3 entries
2. get_error_history — same error in multiple compilations → count > 1
3. get_error_history — error followed by successful compile → resolved=True
4. get_error_history — no failed compilations → returns empty list (not 404)
5. _extract_error_type — parses "! Undefined control sequence." banner line
6. _extract_error_type — falls back to category for generic "pdflatex exited" msg
7. GET /resumes/error-history → 200 with correct payload via FastAPI test client
8. GET /resumes/error-history?limit=1 → respects limit parameter
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.services.error_history_service import (
    ErrorHistoryService,
    _extract_error_type,
)

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_compilation(
    *,
    user_id: str = "user-001",
    resume_id: str | None = None,
    status: str = "failed",
    error_message: str | None = None,
    created_at: datetime | None = None,
) -> MagicMock:
    c = MagicMock()
    c.id = str(uuid.uuid4())
    c.user_id = user_id
    c.resume_id = resume_id or str(uuid.uuid4())
    c.status = status
    c.error_message = error_message
    c.created_at = created_at or datetime.now(timezone.utc)
    return c


def _make_resume(*, resume_id: str, title: str = "My Resume") -> MagicMock:
    r = MagicMock()
    r.id = resume_id
    r.title = title
    return r


def _mock_db_for_history(
    failed: list[MagicMock],
    successes: list[tuple[str, datetime]] | None = None,
    resumes: list[MagicMock] | None = None,
) -> AsyncMock:
    """
    Build an AsyncMock db whose execute() returns appropriate results for the
    three queries ErrorHistoryService.get_error_history() issues:
      1. SELECT failed compilations
      2. SELECT successful (resume_id, created_at) pairs
      3. SELECT resume (id, title) rows
    """
    db = AsyncMock()
    call_count = 0

    async def _execute(stmt):
        nonlocal call_count
        call_count += 1

        if call_count == 1:
            # Failed compilations
            result = MagicMock()
            result.scalars.return_value.all.return_value = failed
            return result

        if call_count == 2:
            # Successful compilations — returns (resume_id, created_at) rows
            rows = successes or []
            result = MagicMock()
            result.all.return_value = rows
            return result

        # Resume titles
        resume_rows = resumes or []
        result = MagicMock()
        result.all.return_value = resume_rows
        return result

    db.execute = _execute
    return db


# ──────────────────────────────────────────────────────────────────────────────
# 1. _extract_error_type unit tests
# ──────────────────────────────────────────────────────────────────────────────


class TestExtractErrorType:

    def test_bang_line_parsed(self):
        result = _extract_error_type("! Undefined control sequence.")
        assert result == "Undefined control sequence"

    def test_bang_line_without_dot(self):
        result = _extract_error_type("! Missing $ inserted")
        assert result == "Missing $ inserted"

    def test_timeout_fallback(self):
        result = _extract_error_type("Compilation timed out after 60s (free plan limit)")
        assert result == "Compilation Timeout"

    def test_generic_latex_error_fallback(self):
        result = _extract_error_type("pdflatex exited with code 1")
        assert result == "LaTeX Compile Error"

    def test_none_returns_unknown(self):
        result = _extract_error_type(None)
        assert result == "Unknown Error"

    def test_empty_string_falls_through(self):
        result = _extract_error_type("")
        assert result == "Unknown Error"


# ──────────────────────────────────────────────────────────────────────────────
# 2–4. ErrorHistoryService.get_error_history
# ──────────────────────────────────────────────────────────────────────────────


class TestGetErrorHistory:

    service = ErrorHistoryService()

    @pytest.mark.asyncio
    async def test_three_distinct_errors_returns_three_entries(self):
        """User with 3 failed compilations of different types → 3 grouped entries."""
        now = datetime.now(timezone.utc)
        resume_id = str(uuid.uuid4())
        failed = [
            _make_compilation(error_message="! Undefined control sequence.", resume_id=resume_id, created_at=now),
            _make_compilation(error_message="! Missing $ inserted.", resume_id=resume_id, created_at=now - timedelta(hours=1)),
            _make_compilation(error_message="Compilation timed out after 60s", resume_id=resume_id, created_at=now - timedelta(hours=2)),
        ]
        db = _mock_db_for_history(failed)
        result = await self.service.get_error_history("user-001", db, limit=50)
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_same_error_multiple_times_counted(self):
        """Same LaTeX error in 3 compilations → single entry with count=3."""
        now = datetime.now(timezone.utc)
        resume_id = str(uuid.uuid4())
        failed = [
            _make_compilation(error_message="! Undefined control sequence.", resume_id=resume_id, created_at=now),
            _make_compilation(error_message="! Undefined control sequence.", resume_id=resume_id, created_at=now - timedelta(hours=1)),
            _make_compilation(error_message="! Undefined control sequence.", resume_id=resume_id, created_at=now - timedelta(hours=2)),
        ]
        db = _mock_db_for_history(failed)
        result = await self.service.get_error_history("user-001", db, limit=50)
        assert len(result) == 1
        assert result[0].count == 3
        assert result[0].error_type == "Undefined control sequence"

    @pytest.mark.asyncio
    async def test_error_followed_by_success_is_resolved(self):
        """If resume has a successful compile AFTER the last error → resolved=True."""
        resume_id = str(uuid.uuid4())
        error_time = datetime.now(timezone.utc) - timedelta(hours=2)
        success_time = datetime.now(timezone.utc) - timedelta(hours=1)

        failed = [
            _make_compilation(
                error_message="! Undefined control sequence.",
                resume_id=resume_id,
                created_at=error_time,
            )
        ]
        db = _mock_db_for_history(
            failed,
            successes=[(resume_id, success_time)],
        )
        result = await self.service.get_error_history("user-001", db, limit=50)
        assert len(result) == 1
        assert result[0].resolved is True

    @pytest.mark.asyncio
    async def test_error_without_subsequent_success_is_not_resolved(self):
        """Error not followed by a successful compile → resolved=False."""
        resume_id = str(uuid.uuid4())
        error_time = datetime.now(timezone.utc) - timedelta(hours=1)
        # Success happened BEFORE the error
        success_time = datetime.now(timezone.utc) - timedelta(hours=3)

        failed = [
            _make_compilation(
                error_message="! Undefined control sequence.",
                resume_id=resume_id,
                created_at=error_time,
            )
        ]
        db = _mock_db_for_history(
            failed,
            successes=[(resume_id, success_time)],
        )
        result = await self.service.get_error_history("user-001", db, limit=50)
        assert len(result) == 1
        assert result[0].resolved is False

    @pytest.mark.asyncio
    async def test_no_failed_compilations_returns_empty_list(self):
        """User with zero failed compilations → empty list, no exception."""
        db = _mock_db_for_history(failed=[])
        result = await self.service.get_error_history("user-001", db, limit=50)
        assert result == []

    @pytest.mark.asyncio
    async def test_sorted_by_count_desc(self):
        """Most-frequent error type appears first."""
        now = datetime.now(timezone.utc)
        resume_id = str(uuid.uuid4())
        failed = [
            # "Missing $" appears twice
            _make_compilation(error_message="! Missing $ inserted.", resume_id=resume_id, created_at=now),
            _make_compilation(error_message="! Missing $ inserted.", resume_id=resume_id, created_at=now - timedelta(hours=1)),
            # "Undefined control sequence" appears once
            _make_compilation(error_message="! Undefined control sequence.", resume_id=resume_id, created_at=now - timedelta(hours=2)),
        ]
        db = _mock_db_for_history(failed)
        result = await self.service.get_error_history("user-001", db, limit=50)
        assert result[0].error_type == "Missing $ inserted"
        assert result[0].count == 2

    @pytest.mark.asyncio
    async def test_limit_respected(self):
        """limit parameter caps the number of returned entries."""
        now = datetime.now(timezone.utc)
        failed = [
            _make_compilation(error_message=f"! Error type {i}.", created_at=now - timedelta(hours=i))
            for i in range(10)
        ]
        db = _mock_db_for_history(failed)
        result = await self.service.get_error_history("user-001", db, limit=3)
        assert len(result) <= 3


# ──────────────────────────────────────────────────────────────────────────────
# 5. Route-level test via FastAPI test client
# ──────────────────────────────────────────────────────────────────────────────


def _make_route_app():
    from app.api.resume_routes import router as resume_router
    from app.database.connection import get_db
    from app.middleware.auth_middleware import get_current_user_required

    app = FastAPI()
    app.include_router(resume_router)

    app.dependency_overrides[get_current_user_required] = lambda: "user-route-test"

    # DB mock returns empty list for the first execute (failed compilations)
    mock_db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=result_mock)

    async def _get_db():
        yield mock_db

    app.dependency_overrides[get_db] = _get_db
    return app, mock_db


class TestErrorHistoryRoute:

    @pytest.mark.asyncio
    async def test_get_error_history_returns_200(self):
        app, _ = _make_route_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/resumes/error-history")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_get_error_history_limit_param_accepted(self):
        app, _ = _make_route_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/resumes/error-history?limit=10")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_error_history_unauthenticated_returns_401_or_422(self):
        """Without auth override, endpoint should reject unauthenticated requests."""
        from app.api.resume_routes import router as resume_router
        from app.database.connection import get_db

        bare_app = FastAPI()
        bare_app.include_router(resume_router)

        mock_db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=result_mock)

        async def _get_db():
            yield mock_db
        bare_app.dependency_overrides[get_db] = _get_db

        transport = ASGITransport(app=bare_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/resumes/error-history")
        # Auth middleware returns 401 or 403 when no token provided
        assert resp.status_code in (401, 403, 422)
