"""
Tests for Feature 13: Project-Wide Search.

Covers:
  - GET /resumes/search?q=... — search across title + latex_content
  - Query too short → 422
  - Query too long → 422
  - Results scoped to current user
  - Correct line numbers returned
  - limit parameter respected
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_latex(text: str = "Hello world") -> str:
    return rf"\documentclass{{article}}\begin{{document}}{text}\end{{document}}"


async def _create_resume(
    client: AsyncClient,
    auth_headers: dict,
    title: str,
    latex: str | None = None,
) -> dict:
    body = {"title": title, "latex_content": latex or _make_latex(title)}
    resp = await client.post("/resumes/", headers=auth_headers, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Extra fixture — second user (for scope-isolation test)
# ---------------------------------------------------------------------------


@pytest.fixture
async def auth_headers_2(db_session: AsyncSession) -> dict:
    """Auth headers for a second independent test user."""
    from conftest import _insert_session  # type: ignore[import]

    user_id = str(uuid.uuid4())
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, name, email_verified, subscription_plan, "
            "subscription_status, trial_used) "
            "VALUES (:id, :email, 'Test User 2', true, 'free', 'active', false) "
            "ON CONFLICT DO NOTHING"
        ),
        {"id": user_id, "email": f"test2_{user_id.replace('-', '')}@example.com"},
    )
    await db_session.commit()
    token = await _insert_session(db_session, user_id)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# TestSearchEndpoint
# ---------------------------------------------------------------------------


class TestSearchEndpoint:
    async def test_query_too_short_returns_422(self, client: AsyncClient, auth_headers: dict):
        resp = await client.get("/resumes/search?q=x", headers=auth_headers)
        assert resp.status_code == 422

    async def test_query_too_long_returns_422(self, client: AsyncClient, auth_headers: dict):
        long_q = "a" * 201
        resp = await client.get(f"/resumes/search?q={long_q}", headers=auth_headers)
        assert resp.status_code == 422

    async def test_unauthenticated_returns_401(self, client: AsyncClient):
        resp = await client.get("/resumes/search?q=hello")
        assert resp.status_code in (401, 403)

    async def test_match_in_title(self, client: AsyncClient, auth_headers: dict):
        unique = "test_srch_title_UNIQUE"
        await _create_resume(client, auth_headers, title=unique)
        resp = await client.get(f"/resumes/search?q={unique}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_resumes_matched"] >= 1
        titles = [r["resume_title"] for r in data["results"]]
        assert any(unique in t for t in titles)

    async def test_match_in_latex_content(self, client: AsyncClient, auth_headers: dict):
        unique_token = "test_srch_latex_XYZUNIQ42"
        latex = rf"\documentclass{{article}}\begin{{document}}{unique_token}\end{{document}}"
        await _create_resume(client, auth_headers, title="test_srch_latex_resume", latex=latex)
        resp = await client.get(f"/resumes/search?q={unique_token}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_resumes_matched"] >= 1
        assert data["query"] == unique_token

    async def test_correct_line_number_returned(self, client: AsyncClient, auth_headers: dict):
        unique_token = "test_srch_line_LINECHECK99"
        latex = "\\documentclass{article}\n\\begin{document}\nLine three\n" + unique_token + "\nLine five\n\\end{document}"
        await _create_resume(client, auth_headers, title="test_srch_line_resume", latex=latex)
        resp = await client.get(f"/resumes/search?q={unique_token}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_resumes_matched"] >= 1
        result = next(r for r in data["results"] if any(unique_token in m["line_content"] for m in r["matches"]))
        match = next(m for m in result["matches"] if unique_token in m["line_content"])
        assert match["line_number"] == 4

    async def test_results_scoped_to_current_user(
        self, client: AsyncClient, auth_headers: dict, auth_headers_2: dict
    ):
        unique_token = "test_srch_scope_OTHERUSER88"
        # Create resume under user 2
        await _create_resume(client, auth_headers_2, title="test_srch_other", latex=rf"\documentclass{{article}}\begin{{document}}{unique_token}\end{{document}}")
        # User 1 should not see it
        resp = await client.get(f"/resumes/search?q={unique_token}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["total_resumes_matched"] == 0

    async def test_limit_parameter_respected(self, client: AsyncClient, auth_headers: dict):
        shared_word = "test_srch_limit_SHAREDWORD77"
        for i in range(4):
            await _create_resume(
                client, auth_headers,
                title=f"test_srch_limit_resume_{i}",
                latex=rf"\documentclass{{article}}\begin{{document}}{shared_word}\end{{document}}",
            )
        resp = await client.get(f"/resumes/search?q={shared_word}&limit=2", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) <= 2

    async def test_no_match_returns_empty(self, client: AsyncClient, auth_headers: dict):
        resp = await client.get("/resumes/search?q=test_srch_NOMATCH_ZZZNEVEREXISTS", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_resumes_matched"] == 0
        assert data["results"] == []

    async def test_response_schema_fields_present(self, client: AsyncClient, auth_headers: dict):
        unique = "test_srch_schema_FIELDS55"
        latex = rf"\documentclass{{article}}\begin{{document}}{unique}\end{{document}}"
        await _create_resume(client, auth_headers, title="test_srch_schema_resume", latex=latex)
        resp = await client.get(f"/resumes/search?q={unique}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert "total_resumes_matched" in data
        assert "query" in data
        if data["results"]:
            r = data["results"][0]
            assert "resume_id" in r
            assert "resume_title" in r
            assert "updated_at" in r
            assert "matches" in r
            if r["matches"]:
                m = r["matches"][0]
                assert "line_number" in m
                assert "line_content" in m
                assert "context_before" in m
                assert "context_after" in m
                assert "highlight_start" in m
                assert "highlight_end" in m

    async def test_highlight_offsets_correct(self, client: AsyncClient, auth_headers: dict):
        unique = "test_srch_highlight_OFFSET33"
        prefix = "some text before "
        latex = rf"\documentclass{{article}}\begin{{document}}{prefix}{unique} after\end{{document}}"
        await _create_resume(client, auth_headers, title="test_srch_hl_resume", latex=latex)
        resp = await client.get(f"/resumes/search?q={unique}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        result = next((r for r in data["results"] if r["matches"]), None)
        assert result is not None
        m = result["matches"][0]
        line = m["line_content"]
        extracted = line[m["highlight_start"]:m["highlight_end"]]
        assert extracted.lower() == unique.lower()
