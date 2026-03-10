"""
Embedding service for Layer 3 semantic job-description matching.

Uses OpenAI text-embedding-3-small (1536 dim) to embed resume content
and job descriptions. Similarity is computed in Python (no pgvector operator
queries needed for our 1K-10K user scale).
"""

import hashlib
import math
import re
from typing import Any, Dict, List, Optional

from ..core.config import settings
from ..core.logging import get_logger

logger = get_logger(__name__)

# Stopwords for keyword extraction
_STOPWORDS = {
    "the", "and", "for", "are", "but", "not", "you", "all", "can", "had",
    "her", "was", "one", "our", "out", "day", "get", "has", "him", "his",
    "how", "its", "may", "new", "now", "old", "see", "two", "who", "did",
    "she", "use", "way", "many", "will", "with", "that", "this", "from",
    "have", "they", "been", "your", "more", "also", "able", "each", "been",
    "than", "into", "over", "when", "what", "some", "time", "very", "just",
    "been", "such", "make", "like", "him", "into", "time", "has", "look",
    "more", "write", "come", "could", "its", "than", "then", "could",
    "which", "their", "said", "would", "there", "about", "through",
    "ever", "seen", "best", "look", "find", "give", "take", "need",
    "work", "used", "want", "know", "well", "also", "both", "each",
    "even", "here", "only", "same", "turn", "good", "come", "goes",
}


class EmbeddingService:
    """Service for computing and comparing text embeddings."""

    def __init__(self) -> None:
        self._client = None

    def _get_client(self):
        """Lazy-init OpenAI client."""
        if self._client is None:
            if not settings.OPENAI_API_KEY:
                raise RuntimeError("OPENAI_API_KEY not configured")
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        return self._client

    # ------------------------------------------------------------------ #
    #  Embedding helpers                                                  #
    # ------------------------------------------------------------------ #

    async def embed_text(self, text: str) -> List[float]:
        """Embed a text string using text-embedding-3-small (1536 dims)."""
        client = self._get_client()
        # Truncate to ~32K chars to stay within model limits
        truncated = text[:32000]
        response = await client.embeddings.create(
            model="text-embedding-3-small",
            input=truncated,
        )
        return response.data[0].embedding

    async def embed_resume(
        self, resume_id: str, latex_content: str, db
    ) -> Optional[List[float]]:
        """
        Compute embedding for a resume and persist to DB.
        Returns the embedding vector.
        """
        from sqlalchemy import update

        from ..database.models import Resume
        from ..services.ats_scoring_service import ats_scoring_service

        try:
            text = ats_scoring_service._extract_text_from_latex(latex_content)
            if not text.strip():
                return None

            embedding = await self.embed_text(text)

            # Persist to DB
            await db.execute(
                update(Resume)
                .where(Resume.id == resume_id)
                .values(content_embedding=embedding)
            )
            await db.commit()
            logger.info(f"Embedded resume {resume_id} ({len(embedding)} dims)")
            return embedding
        except Exception as e:
            logger.error(f"Failed to embed resume {resume_id}: {e}")
            return None

    async def embed_job_description(self, jd_text: str) -> List[float]:
        """Embed a job description text."""
        return await self.embed_text(jd_text)

    # ------------------------------------------------------------------ #
    #  Similarity & keyword matching                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def cosine_similarity(a: List[float], b: List[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        mag_a = math.sqrt(sum(x * x for x in a))
        mag_b = math.sqrt(sum(x * x for x in b))
        if mag_a == 0.0 or mag_b == 0.0:
            return 0.0
        return dot / (mag_a * mag_b)

    @staticmethod
    def _hash_jd(jd_text: str) -> str:
        """SHA-256 hex digest of the JD text — used as cache key."""
        return hashlib.sha256(jd_text.encode("utf-8")).hexdigest()

    @staticmethod
    def _extract_keywords(text: str) -> List[str]:
        """Extract meaningful words from text (lowercased, deduplicated)."""
        words = re.findall(r'\b[a-zA-Z][a-zA-Z0-9+#\-.]{2,}\b', text.lower())
        return list(dict.fromkeys(w for w in words if w not in _STOPWORDS))

    async def semantic_keyword_match(
        self,
        resume_emb: List[float],
        jd_emb: List[float],
        jd_text: str,
        resume_text: str,
    ) -> Dict[str, Any]:
        """
        Combine cosine similarity with lexical keyword gap analysis.

        Returns:
            similarity_score  — 0-100
            matched_keywords  — keywords present in both JD and resume
            missing_keywords  — JD keywords absent from resume
            semantic_gaps     — breakdown by category
        """
        from .ats_scoring_service import ATSScoringService

        similarity_score = round(self.cosine_similarity(resume_emb, jd_emb) * 100, 1)

        jd_keywords = set(self._extract_keywords(jd_text))
        resume_keywords = set(self._extract_keywords(resume_text))

        matched = sorted(jd_keywords & resume_keywords)
        missing = sorted(jd_keywords - resume_keywords)

        # Categorise missing keywords
        tech_set = {k.lower() for k in ATSScoringService.TECH_KEYWORDS}
        soft_set = {k.lower() for k in ATSScoringService.SOFT_SKILLS}

        semantic_gaps: Dict[str, Any] = {
            "technical_skills": [k for k in missing if k in tech_set][:15],
            "soft_skills": [k for k in missing if k in soft_set][:10],
            "domain_specific": [
                k for k in missing
                if k not in tech_set and k not in soft_set
            ][:20],
            "similarity_score": similarity_score,
        }

        return {
            "similarity_score": similarity_score,
            "matched_keywords": matched[:30],
            "missing_keywords": missing[:30],
            "semantic_gaps": semantic_gaps,
        }


# Singleton
embedding_service = EmbeddingService()
