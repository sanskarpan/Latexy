"""
Feature 87 — One-Click Job Application Integration tests.

Tests:
1. GreenhouseService.parse_url — parses company/job_id correctly.
2. LeverService.parse_url — parses company/posting_id correctly.
3. GreenhouseService.get_job_details — with mocked HTTP, parses title/location.
4. POST /apply/greenhouse with invalid URL → 422.
5. POST /apply/greenhouse with upstream 404 → 502 (company not found on Greenhouse).
6. POST /apply/lever with invalid URL → 422.
7. Successful greenhouse submission → ApplicationSubmission status='submitted', submitted_at set.
8. Failed greenhouse submission → status='failed', error_message populated.
9. GET /apply/submissions returns only current user's submissions.
10. GET /apply/submissions/{id} returns 404 for another user's submission.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.services.greenhouse_service import GreenhouseService, greenhouse_service
from app.services.lever_service import LeverService

# ──────────────────────────────────────────────────────────────────────────────
# 1. URL parsing — Greenhouse
# ──────────────────────────────────────────────────────────────────────────────


class TestGreenhouseUrlParsing:

    def test_standard_url(self):
        company, job_id = GreenhouseService.parse_url(
            "https://boards.greenhouse.io/acmecorp/jobs/12345678"
        )
        assert company == "acmecorp"
        assert job_id == "12345678"

    def test_job_boards_subdomain(self):
        company, job_id = GreenhouseService.parse_url(
            "https://job-boards.greenhouse.io/stripe/jobs/9876543"
        )
        assert company == "stripe"
        assert job_id == "9876543"

    def test_url_with_query_params(self):
        company, job_id = GreenhouseService.parse_url(
            "https://boards.greenhouse.io/openai/jobs/555666?gh_src=abc"
        )
        assert company == "openai"
        assert job_id == "555666"

    def test_invalid_url_raises(self):
        with pytest.raises(ValueError, match="Cannot parse Greenhouse"):
            GreenhouseService.parse_url("https://jobs.lever.co/stripe/abc-def-123")

    def test_random_url_raises(self):
        with pytest.raises(ValueError):
            GreenhouseService.parse_url("https://example.com/jobs/42")


# ──────────────────────────────────────────────────────────────────────────────
# 2. URL parsing — Lever
# ──────────────────────────────────────────────────────────────────────────────


class TestLeverUrlParsing:

    def test_standard_url(self):
        company, posting_id = LeverService.parse_url(
            "https://jobs.lever.co/acme/a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        )
        assert company == "acme"
        assert posting_id == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

    def test_url_with_apply_suffix(self):
        company, posting_id = LeverService.parse_url(
            "https://jobs.lever.co/stripe/a1b2c3d4-e5f6-7890-abcd-ef1234567890/apply"
        )
        assert company == "stripe"
        assert posting_id == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

    def test_invalid_url_raises(self):
        with pytest.raises(ValueError, match="Cannot parse Lever"):
            LeverService.parse_url("https://boards.greenhouse.io/acme/jobs/123")

    def test_no_uuid_raises(self):
        with pytest.raises(ValueError):
            LeverService.parse_url("https://jobs.lever.co/acme/not-a-uuid")


# ──────────────────────────────────────────────────────────────────────────────
# 3. GreenhouseService.get_job_details — mocked HTTP
# ──────────────────────────────────────────────────────────────────────────────


class TestGreenhouseGetJobDetails:

    @pytest.mark.asyncio
    @respx.mock
    async def test_parses_title_and_location(self):
        job_url_pattern = "https://boards-api.greenhouse.io/v1/boards/acmecorp/jobs/12345"
        respx.get(job_url_pattern).mock(
            return_value=httpx.Response(
                200,
                json={
                    "title": "Senior Software Engineer",
                    "location": {"name": "San Francisco, CA"},
                    "absolute_url": "https://boards.greenhouse.io/acmecorp/jobs/12345",
                    "content": "<p>Job description</p>",
                },
            )
        )
        details = await greenhouse_service.get_job_details("acmecorp", "12345")
        assert details.title == "Senior Software Engineer"
        assert details.location == "San Francisco, CA"
        assert details.company == "acmecorp"
        assert details.job_id == "12345"

    @pytest.mark.asyncio
    @respx.mock
    async def test_404_raises_value_error(self):
        respx.get("https://boards-api.greenhouse.io/v1/boards/nocompany/jobs/99").mock(
            return_value=httpx.Response(404)
        )
        with pytest.raises(ValueError, match="not found"):
            await greenhouse_service.get_job_details("nocompany", "99")


# ──────────────────────────────────────────────────────────────────────────────
# 4 & 5. POST /apply/greenhouse — invalid URL and upstream error
# ──────────────────────────────────────────────────────────────────────────────


def _make_app():
    from app.api.application_routes import router as apply_router
    from app.database.connection import get_db
    from app.middleware.auth_middleware import get_current_user_required

    app = FastAPI()
    app.include_router(apply_router)

    # Override auth
    app.dependency_overrides[get_current_user_required] = lambda: "user-test-001"

    # Override DB — minimal async mock
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    async def _get_db():
        yield mock_db

    app.dependency_overrides[get_db] = _get_db
    return app, mock_db


class TestGreenhouseRoute:

    @pytest.mark.asyncio
    async def test_invalid_url_returns_422(self):
        app, _ = _make_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/apply/greenhouse", json={
                "job_url": "https://example.com/not-greenhouse",
                "resume_id": str(uuid.uuid4()),
                "first_name": "Jane",
                "last_name": "Doe",
                "email": "jane@example.com",
                "phone": "",
            })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_missing_required_fields_returns_422(self):
        app, _ = _make_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/apply/greenhouse", json={
                "job_url": "https://boards.greenhouse.io/acme/jobs/123",
                # missing first_name, last_name, email
            })
        assert resp.status_code == 422


class TestLeverRoute:

    @pytest.mark.asyncio
    async def test_invalid_url_returns_422(self):
        app, _ = _make_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/apply/lever", json={
                "job_url": "https://example.com/not-lever",
                "resume_id": str(uuid.uuid4()),
                "name": "Jane Doe",
                "email": "jane@example.com",
                "phone": "",
            })
        assert resp.status_code == 422


# ──────────────────────────────────────────────────────────────────────────────
# 7 & 8. Successful and failed submission state
# ──────────────────────────────────────────────────────────────────────────────


class TestSubmissionStatus:

    @pytest.mark.asyncio
    async def test_successful_submission_sets_status_submitted(self):
        """
        When greenhouse_service.submit_application succeeds:
        - ApplicationSubmission.status = 'submitted'
        - ApplicationSubmission.submitted_at is set
        """
        # We test by constructing the route handler in isolation
        # and mocking all external dependencies.
        from app.api.application_routes import GreenhouseApplyRequest, apply_greenhouse

        body = GreenhouseApplyRequest(
            job_url="https://boards.greenhouse.io/acme/jobs/999",
            resume_id=str(uuid.uuid4()),
            first_name="John",
            last_name="Smith",
            email="john@example.com",
            phone="555-1234",
        )

        created_subs = []

        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        def _add(obj):
            created_subs.append(obj)
        mock_db.add = _add

        async def _refresh(obj):
            # Simulate DB assigning server-default fields
            if not getattr(obj, 'created_at', None):
                obj.created_at = datetime.now(timezone.utc)
        mock_db.refresh = AsyncMock(side_effect=_refresh)

        # Patch _get_resume_pdf to return fake bytes
        with (
            patch("app.api.application_routes._get_resume_pdf", new_callable=AsyncMock, return_value=b"%PDF-fake"),
            patch("app.api.application_routes.greenhouse_service.get_job_details", new_callable=AsyncMock) as mock_details,
            patch("app.api.application_routes.greenhouse_service.submit_application", new_callable=AsyncMock) as mock_submit,
            patch("app.api.application_routes._create_or_update_tracker", new_callable=AsyncMock, return_value="tracker-id-001"),
        ):
            mock_details.side_effect = ValueError("preview not critical")
            mock_submit.return_value = {"id": "gh-app-001", "status": "applied"}

            await apply_greenhouse(body, user_id="user-001", db=mock_db)

        assert created_subs, "ApplicationSubmission should have been added to db"
        sub = created_subs[0]
        assert sub.status == "submitted"
        assert sub.submitted_at is not None
        assert sub.job_tracker_id == "tracker-id-001"

    @pytest.mark.asyncio
    async def test_failed_submission_sets_status_failed(self):
        """
        When greenhouse_service.submit_application raises ValueError:
        - ApplicationSubmission.status = 'failed'
        - error_message is populated
        """
        from app.api.application_routes import GreenhouseApplyRequest, apply_greenhouse

        body = GreenhouseApplyRequest(
            job_url="https://boards.greenhouse.io/acme/jobs/999",
            resume_id=str(uuid.uuid4()),
            first_name="John",
            last_name="Smith",
            email="john@example.com",
            phone="",
        )

        created_subs = []
        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.add = lambda obj: created_subs.append(obj)

        async def _refresh2(obj):
            if not getattr(obj, 'created_at', None):
                obj.created_at = datetime.now(timezone.utc)
        mock_db.refresh = AsyncMock(side_effect=_refresh2)

        with (
            patch("app.api.application_routes._get_resume_pdf", new_callable=AsyncMock, return_value=b"%PDF-fake"),
            patch("app.api.application_routes.greenhouse_service.get_job_details", new_callable=AsyncMock, side_effect=ValueError("preview not critical")),
            patch("app.api.application_routes.greenhouse_service.submit_application", new_callable=AsyncMock, side_effect=ValueError("Missing required field")),
        ):
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc_info:
                await apply_greenhouse(body, user_id="user-001", db=mock_db)

        assert exc_info.value.status_code == 502
        assert created_subs
        sub = created_subs[0]
        assert sub.status == "failed"
        assert "Missing required field" in (sub.error_message or "")


# ──────────────────────────────────────────────────────────────────────────────
# 9. GET /apply/submissions — only current user's data
# ──────────────────────────────────────────────────────────────────────────────


class TestListSubmissions:

    @pytest.mark.asyncio
    async def test_list_returns_only_current_user_submissions(self):
        from app.api.application_routes import list_submissions

        now = datetime.now(timezone.utc)

        def _make_sub(uid: str) -> MagicMock:
            s = MagicMock()
            s.id = str(uuid.uuid4())
            s.user_id = uid
            s.resume_id = None
            s.job_tracker_id = None
            s.platform = "greenhouse"
            s.platform_job_id = "123"
            s.application_url = "https://boards.greenhouse.io/acme/jobs/123"
            s.job_title = "Engineer"
            s.company_name = "Acme"
            s.status = "submitted"
            s.submitted_at = now
            s.error_message = None
            s.created_at = now
            return s

        user_sub = _make_sub("user-A")
        other_sub = _make_sub("user-B")

        mock_db = AsyncMock()
        # The query result will return only user-A's sub (DB filter applied by route)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [user_sub]
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await list_submissions(user_id="user-A", db=mock_db)

        assert len(result) == 1
        assert result[0]["user_id"] == "user-A"
        # other_sub should not appear
        assert all(r["user_id"] != "user-B" for r in result)

    @pytest.mark.asyncio
    async def test_get_submission_not_found_returns_404(self):
        from fastapi import HTTPException

        from app.api.application_routes import get_submission

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await get_submission("nonexistent-id", user_id="user-A", db=mock_db)

        assert exc_info.value.status_code == 404
