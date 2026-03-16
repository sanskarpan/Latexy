"""
Tests for Resume Variant / Fork system.

Covers:
  - POST /{resume_id}/fork            — create variant
  - GET /{resume_id}/variants          — list variants
  - GET /{resume_id}/diff-with-parent  — diff with parent
  - Variant count in list/get endpoints
  - Fork of fork (unlimited depth)
  - Ownership enforcement
  - Tags cloning
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

_LATEX = r"\documentclass{article}\begin{document}Hello\end{document}"
_LATEX_V2 = r"\documentclass{article}\begin{document}Updated\end{document}"


async def _create_resume(
    client: AsyncClient, auth_headers: dict, title: str = "Test Resume", tags: list | None = None
) -> dict:
    """Create a resume via the API and return the full response dict."""
    body: dict = {"title": title, "latex_content": _LATEX}
    if tags is not None:
        body["tags"] = tags
    resp = await client.post("/resumes/", headers=auth_headers, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _get_user_id(db_session: AsyncSession, auth_headers: dict) -> str:
    token = auth_headers["Authorization"].replace("Bearer ", "")
    result = await db_session.execute(
        text('SELECT "userId" FROM session WHERE token = :tok'),
        {"tok": token},
    )
    row = result.one()
    return row[0]


# ---------------------------------------------------------------------------
# POST /resumes/{resume_id}/fork
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestForkResume:
    async def test_fork_creates_variant(
        self, client: AsyncClient, auth_headers: dict
    ):
        parent = await _create_resume(client, auth_headers, title="Parent Resume")
        resp = await client.post(
            f"/resumes/{parent['id']}/fork",
            headers=auth_headers,
            json={"title": "For Google SWE"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "For Google SWE"
        assert data["parent_resume_id"] == parent["id"]
        assert data["latex_content"] == parent["latex_content"]
        assert data["variant_count"] == 0

    async def test_fork_default_title(
        self, client: AsyncClient, auth_headers: dict
    ):
        parent = await _create_resume(client, auth_headers, title="My Resume")
        resp = await client.post(
            f"/resumes/{parent['id']}/fork",
            headers=auth_headers,
            json={},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "Variant" in data["title"]
        assert "My Resume" in data["title"]

    async def test_cannot_fork_others_resume(
        self,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
    ):
        parent = await _create_resume(client, auth_headers)

        # Create a second user
        user2_id = str(uuid.uuid4())
        await db_session.execute(
            text(
                "INSERT INTO users (id, email, name, email_verified, subscription_plan, subscription_status, trial_used) "
                "VALUES (:id, :email, 'User 2', true, 'free', 'active', false) ON CONFLICT DO NOTHING"
            ),
            {"id": user2_id, "email": f"test_{user2_id[:8]}@example.com"},
        )
        await db_session.commit()
        from conftest import _insert_session

        token2 = await _insert_session(db_session, user2_id)
        headers2 = {"Authorization": f"Bearer {token2}"}

        resp = await client.post(
            f"/resumes/{parent['id']}/fork",
            headers=headers2,
            json={},
        )
        assert resp.status_code == 404

    async def test_fork_clones_tags(
        self, client: AsyncClient, auth_headers: dict
    ):
        parent = await _create_resume(
            client, auth_headers, title="Tagged", tags=["python", "backend"]
        )
        resp = await client.post(
            f"/resumes/{parent['id']}/fork",
            headers=auth_headers,
            json={},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["tags"] == ["python", "backend"]


# ---------------------------------------------------------------------------
# GET /resumes/{resume_id}/variants
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestListVariants:
    async def test_list_variants(
        self, client: AsyncClient, auth_headers: dict
    ):
        parent = await _create_resume(client, auth_headers, title="Parent")

        # Create 2 variants
        await client.post(
            f"/resumes/{parent['id']}/fork",
            headers=auth_headers,
            json={"title": "Variant A"},
        )
        await client.post(
            f"/resumes/{parent['id']}/fork",
            headers=auth_headers,
            json={"title": "Variant B"},
        )

        resp = await client.get(
            f"/resumes/{parent['id']}/variants",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        variants = resp.json()
        assert len(variants) == 2
        titles = {v["title"] for v in variants}
        assert "Variant A" in titles
        assert "Variant B" in titles


# ---------------------------------------------------------------------------
# GET /resumes/{resume_id}/diff-with-parent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDiffWithParent:
    async def test_diff_with_parent(
        self, client: AsyncClient, auth_headers: dict
    ):
        parent = await _create_resume(client, auth_headers, title="Parent")
        fork_resp = await client.post(
            f"/resumes/{parent['id']}/fork",
            headers=auth_headers,
            json={"title": "Fork"},
        )
        variant = fork_resp.json()

        # Update variant content to create a diff
        await client.put(
            f"/resumes/{variant['id']}",
            headers=auth_headers,
            json={"latex_content": _LATEX_V2},
        )

        resp = await client.get(
            f"/resumes/{variant['id']}/diff-with-parent",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["parent_latex"] == _LATEX
        assert data["parent_title"] == "Parent"
        assert data["variant_latex"] == _LATEX_V2
        assert data["variant_title"] == "Fork"

    async def test_diff_no_parent_returns_400(
        self, client: AsyncClient, auth_headers: dict
    ):
        resume = await _create_resume(client, auth_headers)
        resp = await client.get(
            f"/resumes/{resume['id']}/diff-with-parent",
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert "no parent" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Variant count in list/get
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestVariantCount:
    async def test_list_includes_variant_count(
        self, client: AsyncClient, auth_headers: dict
    ):
        parent = await _create_resume(client, auth_headers, title="Counted Parent")
        await client.post(
            f"/resumes/{parent['id']}/fork",
            headers=auth_headers,
            json={"title": "V1"},
        )
        await client.post(
            f"/resumes/{parent['id']}/fork",
            headers=auth_headers,
            json={"title": "V2"},
        )

        resp = await client.get("/resumes/", headers=auth_headers)
        assert resp.status_code == 200
        resumes = resp.json()["resumes"]
        parent_in_list = next(r for r in resumes if r["id"] == parent["id"])
        assert parent_in_list["variant_count"] == 2

    async def test_variant_count_zero_for_leaf(
        self, client: AsyncClient, auth_headers: dict
    ):
        parent = await _create_resume(client, auth_headers)
        fork_resp = await client.post(
            f"/resumes/{parent['id']}/fork",
            headers=auth_headers,
            json={},
        )
        variant = fork_resp.json()

        # Get the variant — should have variant_count=0
        resp = await client.get(
            f"/resumes/{variant['id']}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["variant_count"] == 0


# ---------------------------------------------------------------------------
# Fork of fork (unlimited depth)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestForkOfFork:
    async def test_fork_of_fork(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Grandchild's parent_resume_id = child (not grandparent)."""
        grandparent = await _create_resume(client, auth_headers, title="GP")

        child_resp = await client.post(
            f"/resumes/{grandparent['id']}/fork",
            headers=auth_headers,
            json={"title": "Child"},
        )
        child = child_resp.json()
        assert child["parent_resume_id"] == grandparent["id"]

        grandchild_resp = await client.post(
            f"/resumes/{child['id']}/fork",
            headers=auth_headers,
            json={"title": "Grandchild"},
        )
        grandchild = grandchild_resp.json()
        assert grandchild["parent_resume_id"] == child["id"]
        assert grandchild["parent_resume_id"] != grandparent["id"]
