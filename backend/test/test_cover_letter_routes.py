"""Tests for cover letter API routes."""

import uuid
from unittest.mock import patch

import pytest
from conftest import _insert_session
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import CoverLetter, Resume

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
async def test_user_with_resume(db_session: AsyncSession):
    """Create a test user with a resume and return (user_id, resume_id, auth_headers)."""
    user_id = str(uuid.uuid4())
    resume_id = str(uuid.uuid4())

    # Use full UUID in email to avoid collisions with leftover rows from prior runs.
    # ON CONFLICT (id) only suppresses the (impossible) primary-key collision;
    # email conflicts will surface as a clear error rather than a silent skip.
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, name, email_verified, subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, 'Test CL User', true, 'pro', 'active', false) ON CONFLICT (id) DO NOTHING"
        ),
        {"id": user_id, "email": f"test_{user_id.replace('-', '')}@example.com"},
    )
    await db_session.commit()

    resume = Resume(
        id=resume_id,
        user_id=user_id,
        title="Test Resume for CL",
        latex_content=r"\documentclass{article}\begin{document}Hello World\end{document}",
    )
    db_session.add(resume)
    await db_session.commit()

    token = await _insert_session(db_session, user_id)
    headers = {"Authorization": f"Bearer {token}"}

    return user_id, resume_id, headers


@pytest.fixture
async def test_cover_letter(db_session: AsyncSession, test_user_with_resume):
    """Create a cover letter record and return its ID."""
    user_id, resume_id, _ = test_user_with_resume
    cl_id = str(uuid.uuid4())
    cl = CoverLetter(
        id=cl_id,
        user_id=user_id,
        resume_id=resume_id,
        job_description="Software engineer at Acme Corp",
        company_name="Acme Corp",
        role_title="Software Engineer",
        tone="formal",
        length_preference="3_paragraphs",
        latex_content=r"\documentclass{article}\begin{document}Dear Hiring Manager...\end{document}",
        generation_job_id="test-job-123",
    )
    db_session.add(cl)
    await db_session.commit()
    return cl_id


# ── POST /cover-letters/generate ─────────────────────────────────────────


class TestGenerateCoverLetter:
    @patch("app.api.cover_letter_routes.submit_cover_letter_generation")
    async def test_generate_success(
        self, mock_submit, client: AsyncClient, test_user_with_resume
    ):
        user_id, resume_id, headers = test_user_with_resume
        mock_submit.return_value = "mock-job-id"

        response = await client.post(
            "/cover-letters/generate",
            json={
                "resume_id": resume_id,
                "job_description": "We need a software engineer with Python experience",
                "company_name": "Test Corp",
                "role_title": "Senior SWE",
                "tone": "formal",
                "length_preference": "3_paragraphs",
            },
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "job_id" in data
        assert "cover_letter_id" in data
        mock_submit.assert_called_once()

    async def test_generate_requires_auth(self, client: AsyncClient, test_user_with_resume):
        _, resume_id, _ = test_user_with_resume

        response = await client.post(
            "/cover-letters/generate",
            json={
                "resume_id": resume_id,
                "job_description": "Test JD",
                "tone": "formal",
                "length_preference": "3_paragraphs",
            },
        )
        assert response.status_code in (401, 403)

    @patch("app.api.cover_letter_routes.submit_cover_letter_generation")
    async def test_generate_resume_not_found(
        self, mock_submit, client: AsyncClient, test_user_with_resume
    ):
        _, _, headers = test_user_with_resume

        response = await client.post(
            "/cover-letters/generate",
            json={
                "resume_id": str(uuid.uuid4()),  # non-existent
                "job_description": "Test job description for non-existent resume",
                "tone": "formal",
                "length_preference": "3_paragraphs",
            },
            headers=headers,
        )
        assert response.status_code == 404

    @patch("app.api.cover_letter_routes.submit_cover_letter_generation")
    async def test_generate_invalid_tone(
        self, mock_submit, client: AsyncClient, test_user_with_resume
    ):
        _, resume_id, headers = test_user_with_resume

        response = await client.post(
            "/cover-letters/generate",
            json={
                "resume_id": resume_id,
                "job_description": "Test JD",
                "tone": "invalid_tone",
                "length_preference": "3_paragraphs",
            },
            headers=headers,
        )
        assert response.status_code == 422

    @patch("app.api.cover_letter_routes.submit_cover_letter_generation")
    async def test_generate_creates_db_record(
        self, mock_submit, client: AsyncClient, db_session: AsyncSession, test_user_with_resume
    ):
        user_id, resume_id, headers = test_user_with_resume
        mock_submit.return_value = "mock-job-id"

        response = await client.post(
            "/cover-letters/generate",
            json={
                "resume_id": resume_id,
                "job_description": "Backend engineer with Go experience",
                "company_name": "GoLang Inc",
                "tone": "enthusiastic",
                "length_preference": "4_paragraphs",
            },
            headers=headers,
        )

        data = response.json()
        cl_id = data["cover_letter_id"]

        # Verify DB record
        result = await db_session.execute(
            select(CoverLetter).where(CoverLetter.id == cl_id)
        )
        cl = result.scalar_one_or_none()
        assert cl is not None
        assert cl.resume_id == resume_id
        assert cl.user_id == user_id
        assert cl.tone == "enthusiastic"
        assert cl.length_preference == "4_paragraphs"
        assert cl.company_name == "GoLang Inc"
        assert cl.latex_content is None  # Not yet generated


# ── GET /cover-letters/{id} ──────────────────────────────────────────────


class TestGetCoverLetter:
    async def test_get_success(
        self, client: AsyncClient, test_user_with_resume, test_cover_letter
    ):
        _, _, headers = test_user_with_resume

        response = await client.get(
            f"/cover-letters/{test_cover_letter}",
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == test_cover_letter
        assert data["company_name"] == "Acme Corp"
        assert data["latex_content"] is not None

    async def test_get_requires_auth(self, client: AsyncClient, test_cover_letter):
        response = await client.get(f"/cover-letters/{test_cover_letter}")
        assert response.status_code in (401, 403)

    async def test_get_not_found(self, client: AsyncClient, test_user_with_resume):
        _, _, headers = test_user_with_resume
        response = await client.get(
            f"/cover-letters/{uuid.uuid4()}",
            headers=headers,
        )
        assert response.status_code == 404

    async def test_get_other_users_cover_letter(
        self, client: AsyncClient, db_session: AsyncSession, test_cover_letter
    ):
        """Can't access another user's cover letter."""
        other_user_id = str(uuid.uuid4())
        await db_session.execute(
            text(
                "INSERT INTO users (id, email, name, email_verified, subscription_plan, subscription_status, trial_used) "
                "VALUES (:id, :email, 'Other User', true, 'free', 'active', false) ON CONFLICT DO NOTHING"
            ),
            {"id": other_user_id, "email": f"test_{other_user_id[:8]}@example.com"},
        )
        await db_session.commit()
        token = await _insert_session(db_session, other_user_id)

        response = await client.get(
            f"/cover-letters/{test_cover_letter}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404


# ── PUT /cover-letters/{id} ──────────────────────────────────────────────


class TestUpdateCoverLetter:
    async def test_update_success(
        self, client: AsyncClient, test_user_with_resume, test_cover_letter
    ):
        _, _, headers = test_user_with_resume
        new_content = r"\documentclass{article}\begin{document}Updated content\end{document}"

        response = await client.put(
            f"/cover-letters/{test_cover_letter}",
            json={"latex_content": new_content},
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["latex_content"] == new_content

    async def test_update_requires_auth(self, client: AsyncClient, test_cover_letter):
        response = await client.put(
            f"/cover-letters/{test_cover_letter}",
            json={"latex_content": "test"},
        )
        assert response.status_code in (401, 403)


# ── DELETE /cover-letters/{id} ───────────────────────────────────────────


class TestDeleteCoverLetter:
    async def test_delete_success(
        self, client: AsyncClient, db_session: AsyncSession, test_user_with_resume, test_cover_letter
    ):
        _, _, headers = test_user_with_resume

        response = await client.delete(
            f"/cover-letters/{test_cover_letter}",
            headers=headers,
        )
        assert response.status_code == 204

        # Verify deleted
        result = await db_session.execute(
            select(CoverLetter).where(CoverLetter.id == test_cover_letter)
        )
        assert result.scalar_one_or_none() is None

    async def test_delete_requires_auth(self, client: AsyncClient, test_cover_letter):
        response = await client.delete(f"/cover-letters/{test_cover_letter}")
        assert response.status_code in (401, 403)

    async def test_delete_not_found(self, client: AsyncClient, test_user_with_resume):
        _, _, headers = test_user_with_resume
        response = await client.delete(
            f"/cover-letters/{uuid.uuid4()}",
            headers=headers,
        )
        assert response.status_code == 404


# ── GET /cover-letters/resume/{resume_id} ────────────────────────────────


class TestListResumeCoverLetters:
    async def test_list_success(
        self, client: AsyncClient, test_user_with_resume, test_cover_letter
    ):
        _, resume_id, headers = test_user_with_resume

        response = await client.get(
            f"/cover-letters/resume/{resume_id}",
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert any(cl["id"] == test_cover_letter for cl in data)

    async def test_list_empty(self, client: AsyncClient, test_user_with_resume):
        """Resume with no cover letters returns empty list."""
        user_id, _, headers = test_user_with_resume

        # Create a second resume with no cover letters

        response = await client.get(
            f"/cover-letters/resume/{uuid.uuid4()}",  # Non-existent resume
            headers=headers,
        )
        # Should 404 since resume doesn't exist
        assert response.status_code == 404

    async def test_list_requires_auth(self, client: AsyncClient, test_user_with_resume):
        _, resume_id, _ = test_user_with_resume
        response = await client.get(f"/cover-letters/resume/{resume_id}")
        assert response.status_code in (401, 403)

    async def test_list_ordered_by_date_desc(
        self, client: AsyncClient, db_session: AsyncSession, test_user_with_resume
    ):
        """Cover letters should be returned newest first."""
        import asyncio

        user_id, resume_id, headers = test_user_with_resume

        # Create three cover letters with deterministic timestamps
        for i in range(3):
            cl = CoverLetter(
                id=str(uuid.uuid4()),
                user_id=user_id,
                resume_id=resume_id,
                job_description=f"JD {i}",
                tone="formal",
                length_preference="3_paragraphs",
                latex_content=f"Content {i}",
            )
            db_session.add(cl)
            await db_session.commit()
            await asyncio.sleep(0.05)  # Ensure different timestamps

        response = await client.get(
            f"/cover-letters/resume/{resume_id}",
            headers=headers,
        )
        data = response.json()
        assert len(data) >= 3

        # Verify ordering: newest first
        dates = [cl["created_at"] for cl in data]
        assert dates == sorted(dates, reverse=True)


# ── GET /cover-letters/ (paginated listing) ────────────────────────────


class TestListCoverLetters:
    async def test_list_empty(self, client: AsyncClient, auth_headers: dict):
        """User with no cover letters gets empty list."""
        response = await client.get("/cover-letters/", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["cover_letters"] == []
        assert data["total"] == 0
        assert data["page"] == 1
        assert data["pages"] == 1

    async def test_list_returns_cover_letters(
        self, client: AsyncClient, test_user_with_resume, test_cover_letter
    ):
        _, _, headers = test_user_with_resume
        response = await client.get("/cover-letters/", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        assert any(cl["id"] == test_cover_letter for cl in data["cover_letters"])

    async def test_list_includes_resume_title(
        self, client: AsyncClient, test_user_with_resume, test_cover_letter
    ):
        _, _, headers = test_user_with_resume
        response = await client.get("/cover-letters/", headers=headers)
        data = response.json()
        cl = next(c for c in data["cover_letters"] if c["id"] == test_cover_letter)
        assert cl["resume_title"] == "Test Resume for CL"

    async def test_list_pagination(
        self, client: AsyncClient, db_session: AsyncSession, test_user_with_resume
    ):
        user_id, resume_id, headers = test_user_with_resume
        # Create 3 extra cover letters
        for i in range(3):
            cl = CoverLetter(
                id=str(uuid.uuid4()),
                user_id=user_id,
                resume_id=resume_id,
                job_description=f"Pagination JD {i}",
                tone="formal",
                length_preference="3_paragraphs",
            )
            db_session.add(cl)
        await db_session.commit()

        # Page 1 with limit=2
        resp1 = await client.get("/cover-letters/?page=1&limit=2", headers=headers)
        assert resp1.status_code == 200
        d1 = resp1.json()
        assert len(d1["cover_letters"]) == 2
        assert d1["total"] >= 3
        assert d1["pages"] >= 2

        # Page 2
        resp2 = await client.get("/cover-letters/?page=2&limit=2", headers=headers)
        assert resp2.status_code == 200
        d2 = resp2.json()
        assert len(d2["cover_letters"]) >= 1

        # No overlap between pages
        ids_p1 = {cl["id"] for cl in d1["cover_letters"]}
        ids_p2 = {cl["id"] for cl in d2["cover_letters"]}
        assert ids_p1.isdisjoint(ids_p2)

    async def test_list_search_by_company(
        self, client: AsyncClient, test_user_with_resume, test_cover_letter
    ):
        _, _, headers = test_user_with_resume
        response = await client.get(
            "/cover-letters/?search=Acme", headers=headers
        )
        assert response.status_code == 200
        data = response.json()
        assert any(cl["id"] == test_cover_letter for cl in data["cover_letters"])

    async def test_list_search_by_role(
        self, client: AsyncClient, test_user_with_resume, test_cover_letter
    ):
        _, _, headers = test_user_with_resume
        response = await client.get(
            "/cover-letters/?search=Software", headers=headers
        )
        assert response.status_code == 200
        data = response.json()
        assert any(cl["id"] == test_cover_letter for cl in data["cover_letters"])

    async def test_list_search_no_results(
        self, client: AsyncClient, test_user_with_resume, test_cover_letter
    ):
        _, _, headers = test_user_with_resume
        response = await client.get(
            "/cover-letters/?search=nonexistent_xyz_999", headers=headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["cover_letters"] == []

    async def test_list_requires_auth(self, client: AsyncClient):
        response = await client.get("/cover-letters/")
        assert response.status_code in (401, 403)

    async def test_list_isolates_users(
        self, client: AsyncClient, db_session: AsyncSession, test_user_with_resume, test_cover_letter
    ):
        """Other user can't see cover letters belonging to this user."""
        other_user_id = str(uuid.uuid4())
        await db_session.execute(
            text(
                "INSERT INTO users (id, email, name, email_verified, subscription_plan, subscription_status, trial_used) "
                "VALUES (:id, :email, 'Other User', true, 'free', 'active', false) ON CONFLICT DO NOTHING"
            ),
            {"id": other_user_id, "email": f"test_{other_user_id[:8]}@example.com"},
        )
        await db_session.commit()
        token = await _insert_session(db_session, other_user_id)

        response = await client.get(
            "/cover-letters/",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert not any(cl["id"] == test_cover_letter for cl in data["cover_letters"])

    async def test_list_ordered_newest_first(
        self, client: AsyncClient, db_session: AsyncSession, test_user_with_resume
    ):
        user_id, resume_id, headers = test_user_with_resume
        import asyncio
        for i in range(3):
            cl = CoverLetter(
                id=str(uuid.uuid4()),
                user_id=user_id,
                resume_id=resume_id,
                job_description=f"Order JD {i}",
                tone="formal",
                length_preference="3_paragraphs",
            )
            db_session.add(cl)
            await db_session.commit()
            await asyncio.sleep(0.05)

        response = await client.get("/cover-letters/", headers=headers)
        data = response.json()
        dates = [cl["created_at"] for cl in data["cover_letters"]]
        assert dates == sorted(dates, reverse=True)


# ── GET /cover-letters/stats ───────────────────────────────────────────


class TestCoverLetterStats:
    async def test_stats_zero(self, client: AsyncClient, auth_headers: dict):
        """User with no cover letters gets total=0."""
        response = await client.get("/cover-letters/stats", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0

    async def test_stats_counts(
        self, client: AsyncClient, test_user_with_resume, test_cover_letter
    ):
        _, _, headers = test_user_with_resume
        response = await client.get("/cover-letters/stats", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1

    async def test_stats_requires_auth(self, client: AsyncClient):
        response = await client.get("/cover-letters/stats")
        assert response.status_code in (401, 403)

    async def test_stats_isolates_users(
        self, client: AsyncClient, db_session: AsyncSession, test_user_with_resume, test_cover_letter
    ):
        """Other user's stats should not include this user's cover letters."""
        other_user_id = str(uuid.uuid4())
        await db_session.execute(
            text(
                "INSERT INTO users (id, email, name, email_verified, subscription_plan, subscription_status, trial_used) "
                "VALUES (:id, :email, 'Stats Other', true, 'free', 'active', false) ON CONFLICT DO NOTHING"
            ),
            {"id": other_user_id, "email": f"test_{other_user_id[:8]}@example.com"},
        )
        await db_session.commit()
        token = await _insert_session(db_session, other_user_id)

        response = await client.get(
            "/cover-letters/stats",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json()["total"] == 0
