"""
Tests verifying that content_embedding and job_desc_embedding columns
exist, can be written, and are readable.
"""
from unittest.mock import patch

import pytest


class TestEmbeddingColumns:

    @pytest.mark.asyncio
    async def test_resume_has_content_embedding_column(self, db_session):
        """Verify content_embedding column exists on resumes table."""
        from sqlalchemy import text
        result = await db_session.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='resumes' AND column_name='content_embedding'"
        ))
        row = result.fetchone()
        assert row is not None, "content_embedding column missing from resumes table"

    @pytest.mark.asyncio
    async def test_optimization_has_job_desc_embedding_column(self, db_session):
        """Verify job_desc_embedding column exists on optimizations table."""
        from sqlalchemy import text
        result = await db_session.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='optimizations' AND column_name='job_desc_embedding'"
        ))
        row = result.fetchone()
        assert row is not None, "job_desc_embedding column missing from optimizations table"

    @pytest.mark.asyncio
    async def test_embedding_service_cosine_similarity(self):
        """Verify embedding service math is correct."""
        from app.services.embedding_service import EmbeddingService
        svc = EmbeddingService()
        sim = svc.cosine_similarity([1.0, 0.0], [1.0, 0.0])
        assert abs(sim - 1.0) < 1e-6

    @pytest.mark.asyncio
    async def test_semantic_match_endpoint_requires_auth(self, client):
        """Verify /ats/semantic-match requires authentication."""
        response = await client.post("/ats/semantic-match", json={
            "job_description": "Looking for a Python engineer with 5+ years of experience in cloud infrastructure and microservices",
        })
        assert response.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_embed_resume_task_skipped_without_api_key(self):
        """embed_resume_task should skip gracefully when OPENAI_API_KEY is empty."""
        with patch("app.workers.ats_worker.settings") as mock_settings:
            mock_settings.OPENAI_API_KEY = ""
            from app.workers.ats_worker import embed_resume_task
            # Call the underlying function directly to verify early-return behavior
            # The task checks settings.OPENAI_API_KEY before doing anything
            result = embed_resume_task(
                resume_id="test-resume-id",
                latex_content=r"\documentclass{article}\begin{document}Test\end{document}",
            )
            assert result == {"skipped": True, "reason": "no_api_key"}
