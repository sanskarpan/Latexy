"""
Tests for Feature 39 — Project-Level Tags & Organization.

Covers:
  - PATCH /{resume_id}/tags          — update tags (replace)
  - PATCH /{resume_id}/archive       — archive resume
  - PATCH /{resume_id}/unarchive     — unarchive resume
  - PATCH /{resume_id}/pin           — pin resume
  - PATCH /{resume_id}/unpin         — unpin resume
  - GET /                            — archived filter
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LATEX = r"\documentclass{article}\begin{document}Hello\end{document}"


async def _create_resume(
    client: AsyncClient, auth_headers: dict, title: str = "Test Resume"
) -> dict:
    """Create a resume via the API and return the full response dict."""
    resp = await client.post(
        "/resumes/",
        headers=auth_headers,
        json={"title": title, "latex_content": _LATEX},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# PATCH /{resume_id}/tags
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestUpdateTags:
    async def test_update_tags_success(
        self, client: AsyncClient, auth_headers: dict
    ):
        """PATCH tags → GET shows updated tags list."""
        resume = await _create_resume(client, auth_headers, title="Tags Test")
        resp = await client.patch(
            f"/resumes/{resume['id']}/tags",
            headers=auth_headers,
            json={"tags": ["python", "backend", "ml"]},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert set(data["tags"]) == {"python", "backend", "ml"}

        # Verify GET endpoint also reflects new tags
        get_resp = await client.get(
            f"/resumes/{resume['id']}",
            headers=auth_headers,
        )
        assert get_resp.status_code == 200
        assert set(get_resp.json()["tags"]) == {"python", "backend", "ml"}

    async def test_update_tags_too_many(
        self, client: AsyncClient, auth_headers: dict
    ):
        """More than 10 tags → 422."""
        resume = await _create_resume(client, auth_headers, title="Too Many Tags")
        too_many = [f"tag{i}" for i in range(11)]
        resp = await client.patch(
            f"/resumes/{resume['id']}/tags",
            headers=auth_headers,
            json={"tags": too_many},
        )
        assert resp.status_code == 422

    async def test_update_tags_too_long(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Tag with 31 chars → 422."""
        resume = await _create_resume(client, auth_headers, title="Long Tag Test")
        long_tag = "a" * 31
        resp = await client.patch(
            f"/resumes/{resume['id']}/tags",
            headers=auth_headers,
            json={"tags": [long_tag]},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# PATCH /{resume_id}/archive + unarchive
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestArchiveResume:
    async def test_archive_resume(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Archive → default GET list excludes it."""
        resume = await _create_resume(client, auth_headers, title="Archive Me")

        arch_resp = await client.patch(
            f"/resumes/{resume['id']}/archive",
            headers=auth_headers,
        )
        assert arch_resp.status_code == 200, arch_resp.text
        data = arch_resp.json()
        assert data["archived_at"] is not None

        # Default list should NOT contain this resume
        list_resp = await client.get("/resumes/", headers=auth_headers)
        assert list_resp.status_code == 200
        ids = [r["id"] for r in list_resp.json()["resumes"]]
        assert resume["id"] not in ids

    async def test_archived_in_archived_param(
        self, client: AsyncClient, auth_headers: dict
    ):
        """GET with ?archived=true → returns archived resume."""
        resume = await _create_resume(client, auth_headers, title="Find Archived")

        await client.patch(
            f"/resumes/{resume['id']}/archive",
            headers=auth_headers,
        )

        list_resp = await client.get(
            "/resumes/?archived=true", headers=auth_headers
        )
        assert list_resp.status_code == 200
        ids = [r["id"] for r in list_resp.json()["resumes"]]
        assert resume["id"] in ids

    async def test_unarchive_resume(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Unarchive → appears in default list again."""
        resume = await _create_resume(client, auth_headers, title="Unarchive Me")

        # Archive first
        await client.patch(
            f"/resumes/{resume['id']}/archive",
            headers=auth_headers,
        )

        # Unarchive
        unarch_resp = await client.patch(
            f"/resumes/{resume['id']}/unarchive",
            headers=auth_headers,
        )
        assert unarch_resp.status_code == 200, unarch_resp.text
        assert unarch_resp.json()["archived_at"] is None

        # Should appear in the default list again
        list_resp = await client.get("/resumes/", headers=auth_headers)
        assert list_resp.status_code == 200
        ids = [r["id"] for r in list_resp.json()["resumes"]]
        assert resume["id"] in ids


# ---------------------------------------------------------------------------
# PATCH /{resume_id}/pin + unpin
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPinResume:
    async def test_pin_resume(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Pin → metadata.pinned = True, pinned field = True."""
        resume = await _create_resume(client, auth_headers, title="Pin Me")

        pin_resp = await client.patch(
            f"/resumes/{resume['id']}/pin",
            headers=auth_headers,
        )
        assert pin_resp.status_code == 200, pin_resp.text
        data = pin_resp.json()
        assert data["pinned"] is True
        assert data["metadata"]["pinned"] is True

    async def test_unpin_resume(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Unpin → metadata.pinned removed, pinned field = False."""
        resume = await _create_resume(client, auth_headers, title="Unpin Me")

        # Pin first
        await client.patch(
            f"/resumes/{resume['id']}/pin",
            headers=auth_headers,
        )

        # Unpin
        unpin_resp = await client.patch(
            f"/resumes/{resume['id']}/unpin",
            headers=auth_headers,
        )
        assert unpin_resp.status_code == 200, unpin_resp.text
        data = unpin_resp.json()
        assert data["pinned"] is False
        metadata = data.get("metadata") or {}
        assert "pinned" not in metadata
