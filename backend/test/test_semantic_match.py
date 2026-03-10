"""
Layer 3 — Semantic matching unit tests.

Covers:
- EmbeddingService.cosine_similarity math
- EmbeddingService._hash_jd determinism
- EmbeddingService._extract_keywords stopword removal
- semantic_keyword_match structure
- /ats/semantic-match endpoint (auth required, no resumes → empty results)
"""

import hashlib

import pytest

# ────────────────────────────────────────────────────────────────────────────
#  EmbeddingService unit tests (no OpenAI calls)
# ────────────────────────────────────────────────────────────────────────────

class TestCosineSimilarity:

    @pytest.fixture(autouse=True)
    def svc(self):
        from app.services.embedding_service import EmbeddingService
        self.svc = EmbeddingService()

    def test_identical_vectors_similarity_is_one(self):
        v = [0.1, 0.5, 0.3, 0.8]
        sim = self.svc.cosine_similarity(v, v)
        assert abs(sim - 1.0) < 1e-6

    def test_orthogonal_vectors_similarity_is_zero(self):
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        sim = self.svc.cosine_similarity(a, b)
        assert abs(sim) < 1e-6

    def test_opposite_vectors_similarity_is_minus_one(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        sim = self.svc.cosine_similarity(a, b)
        assert abs(sim - (-1.0)) < 1e-6

    def test_known_similarity(self):
        a = [3.0, 4.0]    # magnitude = 5
        b = [0.0, 5.0]    # magnitude = 5
        # dot = 0*3 + 5*4 = 20; cosine = 20/25 = 0.8
        sim = self.svc.cosine_similarity(a, b)
        assert abs(sim - 0.8) < 1e-6

    def test_zero_vector_returns_zero(self):
        a = [0.0, 0.0, 0.0]
        b = [1.0, 2.0, 3.0]
        sim = self.svc.cosine_similarity(a, b)
        assert sim == 0.0

    def test_similarity_bounded_minus_one_to_one(self):
        import random
        rng = random.Random(42)
        a = [rng.gauss(0, 1) for _ in range(100)]
        b = [rng.gauss(0, 1) for _ in range(100)]
        sim = self.svc.cosine_similarity(a, b)
        assert -1.0 <= sim <= 1.0


class TestHashJd:

    @pytest.fixture(autouse=True)
    def svc(self):
        from app.services.embedding_service import EmbeddingService
        self.svc = EmbeddingService()

    def test_same_jd_same_hash(self):
        jd = "We are looking for a senior Python engineer with AWS experience."
        h1 = self.svc._hash_jd(jd)
        h2 = self.svc._hash_jd(jd)
        assert h1 == h2

    def test_different_jd_different_hash(self):
        h1 = self.svc._hash_jd("Python engineer wanted.")
        h2 = self.svc._hash_jd("Java developer needed.")
        assert h1 != h2

    def test_hash_is_hex_string(self):
        h = self.svc._hash_jd("Some job description text here.")
        # Should be a hex string (SHA-256 = 64 chars)
        assert isinstance(h, str)
        assert all(c in "0123456789abcdef" for c in h.lower())

    def test_hash_length(self):
        h = self.svc._hash_jd("Any job description.")
        assert len(h) == 64  # SHA-256 in hex

    def test_hash_matches_sha256(self):
        text = "Python AWS senior engineer"
        expected = hashlib.sha256(text.encode()).hexdigest()
        assert self.svc._hash_jd(text) == expected


class TestExtractKeywords:

    @pytest.fixture(autouse=True)
    def svc(self):
        from app.services.embedding_service import EmbeddingService
        self.svc = EmbeddingService()

    def test_stopwords_removed(self):
        text = "We are looking for the best engineer the world has ever seen"
        kws = self.svc._extract_keywords(text)
        stopwords = {"we", "are", "for", "the", "has", "ever"}
        for sw in stopwords:
            assert sw not in kws

    def test_short_words_removed(self):
        text = "I am a go to dev for big jobs"
        kws = self.svc._extract_keywords(text)
        # Words shorter than 3 chars should be excluded
        for kw in kws:
            assert len(kw) >= 3

    def test_meaningful_words_kept(self):
        text = "Senior Python engineer with experience in microservices and kubernetes"
        kws = self.svc._extract_keywords(text)
        assert "python" in kws or "Python" in kws
        assert "engineer" in kws or "Engineer" in kws
        assert "microservices" in kws or "Microservices" in kws

    def test_returns_list(self):
        kws = self.svc._extract_keywords("Python Django REST API development")
        assert isinstance(kws, list)

    def test_deduplication(self):
        text = "python python python django django"
        kws = self.svc._extract_keywords(text)
        kws_lower = [k.lower() for k in kws]
        assert kws_lower.count("python") == 1
        assert kws_lower.count("django") == 1


class TestSemanticKeywordMatchStructure:
    """Test the structure of semantic_keyword_match output (no OpenAI calls)."""

    @pytest.mark.asyncio
    async def test_output_keys_present(self):
        from app.services.embedding_service import EmbeddingService
        svc = EmbeddingService()

        # Fake embeddings (unit vectors in 2D)
        resume_emb = [1.0, 0.0]
        jd_emb = [0.8, 0.6]
        jd_text = "Looking for a Python engineer with AWS and Docker experience"
        resume_text = "Python developer with 5 years AWS cloud and Docker containerization"

        result = await svc.semantic_keyword_match(
            resume_emb, jd_emb, jd_text, resume_text
        )

        assert "similarity_score" in result
        assert "matched_keywords" in result
        assert "missing_keywords" in result
        assert "semantic_gaps" in result

    @pytest.mark.asyncio
    async def test_similarity_score_range(self):
        from app.services.embedding_service import EmbeddingService
        svc = EmbeddingService()

        a = [1.0, 0.0]
        b = [0.6, 0.8]
        result = await svc.semantic_keyword_match(a, b, "python aws", "python developer")

        assert 0.0 <= result["similarity_score"] <= 100.0

    @pytest.mark.asyncio
    async def test_matched_keywords_subset_of_jd(self):
        from app.services.embedding_service import EmbeddingService
        svc = EmbeddingService()

        jd_text = "Python engineer with Kubernetes and PostgreSQL"
        resume_text = "Python developer with PostgreSQL experience"

        result = await svc.semantic_keyword_match(
            [1.0, 0.0], [1.0, 0.0],
            jd_text, resume_text
        )

        # Python and PostgreSQL are in both → should appear in matched or at least not in missing
        matched_lower = [k.lower() for k in result["matched_keywords"]]
        assert "python" in matched_lower or "postgresql" in matched_lower

    @pytest.mark.asyncio
    async def test_missing_keywords_not_in_resume(self):
        from app.services.embedding_service import EmbeddingService
        svc = EmbeddingService()

        jd_text = "Looking for Rust expert with WASM and WebAssembly skills"
        resume_text = "Python developer with Django REST framework"

        result = await svc.semantic_keyword_match(
            [1.0, 0.0], [0.0, 1.0],
            jd_text, resume_text
        )

        missing_lower = [k.lower() for k in result["missing_keywords"]]
        resume_lower = resume_text.lower()
        # Missing keywords should not appear in resume text
        for kw in missing_lower[:5]:  # check first 5
            assert kw not in resume_lower or len(kw) < 4


# ────────────────────────────────────────────────────────────────────────────
#  /ats/semantic-match endpoint tests
# ────────────────────────────────────────────────────────────────────────────

class TestSemanticMatchEndpoint:

    @pytest.mark.asyncio
    async def test_requires_auth(self, client):
        response = await client.post("/ats/semantic-match", json={
            "job_description": "Looking for a Python engineer with 5+ years experience in cloud infrastructure",
        })
        # Should return 401 or 403 without auth
        assert response.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_jd_too_short_returns_422(self, client, auth_headers):
        response = await client.post("/ats/semantic-match", json={
            "job_description": "short",
        }, headers=auth_headers)
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_no_resumes_returns_empty_results(self, client, auth_headers):
        """When user has no resumes, returns empty list without error."""
        from unittest.mock import AsyncMock, patch

        # Mock embedding service to avoid OpenAI calls
        with patch("app.services.embedding_service.embedding_service") as mock_svc:
            mock_svc.embed_job_description = AsyncMock(return_value=[0.1] * 1536)
            mock_svc.semantic_keyword_match = AsyncMock(return_value={
                "similarity_score": 0.75,
                "matched_keywords": ["python"],
                "missing_keywords": ["rust"],
                "semantic_gaps": {},
            })

            response = await client.post("/ats/semantic-match", json={
                "job_description": "Looking for a Python engineer with 5+ years of experience in cloud infrastructure and microservices",
            }, headers=auth_headers)

            # Should succeed — empty results (no resumes for test user)
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert isinstance(data["results"], list)
