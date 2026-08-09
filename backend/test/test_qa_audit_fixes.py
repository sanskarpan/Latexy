"""Regression tests for QA-audit findings (Aug 2026).

ISSUE-002/003: PUT/DELETE /resumes/{id} with a non-UUID id must 404, not 500
(asyncpg DataError from an invalid UUID reaching Postgres). GET already guards
this; PUT/DELETE/PATCH-settings did not.
ISSUE-004: POST /ats/recommendations must reject out-of-range ats_score (0-100).
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
class TestResumeNonUuidGuards:
    async def test_put_resume_non_uuid_returns_404(self, client: AsyncClient, auth_headers: dict):
        resp = await client.put(
            "/resumes/not-a-uuid", headers=auth_headers, json={"title": "x"}
        )
        assert resp.status_code == 404

    async def test_delete_resume_non_uuid_returns_404(self, client: AsyncClient, auth_headers: dict):
        resp = await client.delete("/resumes/not-a-uuid", headers=auth_headers)
        assert resp.status_code == 404

    async def test_patch_resume_settings_non_uuid_returns_404(self, client: AsyncClient, auth_headers: dict):
        resp = await client.patch(
            "/resumes/not-a-uuid/settings", headers=auth_headers, json={}
        )
        assert resp.status_code == 404

    async def test_put_resume_random_valid_uuid_returns_404(self, client: AsyncClient, auth_headers: dict):
        # Valid UUID that doesn't exist / isn't owned -> 404 (not 500, not 200).
        resp = await client.put(
            "/resumes/11111111-1111-1111-1111-111111111111",
            headers=auth_headers,
            json={"title": "x"},
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestAtsRecommendationsBounds:
    @pytest.mark.parametrize("score", [1e308, -500, 101, -0.0001])
    async def test_out_of_range_score_returns_422(self, client: AsyncClient, auth_headers: dict, score):
        resp = await client.post(
            "/ats/recommendations",
            headers=auth_headers,
            json={"ats_score": score, "category_scores": {}},
        )
        assert resp.status_code == 422

    async def test_valid_score_ok(self, client: AsyncClient, auth_headers: dict):
        resp = await client.post(
            "/ats/recommendations",
            headers=auth_headers,
            json={"ats_score": 75, "category_scores": {"keywords": 60}},
        )
        assert resp.status_code == 200
