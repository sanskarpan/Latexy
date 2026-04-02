"""Tests for Feature 52: GET /resumes/{resume_id}/score-history endpoint."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
class TestScoreHistoryEndpoint:

    async def test_score_history_empty_when_no_optimizations(
        self, client: AsyncClient, auth_headers: dict
    ):
        """New resume with no optimizations returns empty list, not a 500."""
        # Create a fresh resume
        create_resp = await client.post(
            "/resumes/",
            headers=auth_headers,
            json={"title": "Score History Test", "latex_content": r"\documentclass{article}"},
        )
        assert create_resp.status_code == 201
        resume_id = create_resp.json()["id"]

        resp = await client.get(
            f"/resumes/{resume_id}/score-history", headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_score_history_returns_entries_asc(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Resume with recorded optimizations returns score entries sorted ASC."""
        # Create resume
        create_resp = await client.post(
            "/resumes/",
            headers=auth_headers,
            json={"title": "Score History With Data", "latex_content": r"\documentclass{article}"},
        )
        assert create_resp.status_code == 201
        resume_id = create_resp.json()["id"]

        # Record two optimizations with ATS scores
        for score in (65.0, 80.0):
            rec = await client.post(
                f"/resumes/{resume_id}/record-optimization",
                headers=auth_headers,
                json={
                    "original_latex": r"\documentclass{article}",
                    "optimized_latex": r"\documentclass{article}",
                    "ats_score": score,
                    "tokens_used": 100,
                },
            )
            assert rec.status_code == 201

        resp = await client.get(
            f"/resumes/{resume_id}/score-history", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        # Must be sorted oldest-first (ASC)
        assert data[0]["ats_score"] == 65.0
        assert data[1]["ats_score"] == 80.0

    async def test_score_history_excludes_entries_without_score(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Optimization records without ats_score are excluded from history."""
        create_resp = await client.post(
            "/resumes/",
            headers=auth_headers,
            json={"title": "Score Filter Test", "latex_content": r"\documentclass{article}"},
        )
        resume_id = create_resp.json()["id"]

        # Record one with score, one without
        await client.post(
            f"/resumes/{resume_id}/record-optimization",
            headers=auth_headers,
            json={
                "original_latex": r"\documentclass{article}",
                "optimized_latex": r"\documentclass{article}",
                "ats_score": 72.0,
            },
        )
        await client.post(
            f"/resumes/{resume_id}/record-optimization",
            headers=auth_headers,
            json={
                "original_latex": r"\documentclass{article}",
                "optimized_latex": r"\documentclass{article}",
                # no ats_score
            },
        )

        resp = await client.get(
            f"/resumes/{resume_id}/score-history", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["ats_score"] == 72.0
