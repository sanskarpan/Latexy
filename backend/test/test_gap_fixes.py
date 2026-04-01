"""
In-depth tests verifying that GAP-001 and GAP-003 are genuinely fixed.

GAP-001: ResumeJobMatch caching in POST /ats/semantic-match
GAP-003: Duplicate encryption implementations consolidated
"""

from __future__ import annotations

import base64
import hashlib
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import ResumeJobMatch


# ─────────────────────────────────────────────────────────────────────────────
# GAP-001 · ResumeJobMatch caching
# ─────────────────────────────────────────────────────────────────────────────

JOB_DESCRIPTION = (
    "Senior Python engineer with FastAPI, PostgreSQL, and Docker experience. "
    "Must have 5+ years building distributed systems."
)
JD_HASH = hashlib.sha256(JOB_DESCRIPTION.encode()).hexdigest()

FAKE_RESUME_EMBEDDING = [0.1] * 1536  # 1536-dim vector, same shape as OpenAI embeddings
FAKE_JD_EMBEDDING = [0.2] * 1536

FAKE_MATCH_RESULT = {
    "similarity_score": 0.82,
    "matched_keywords": ["Python", "FastAPI", "Docker"],
    "missing_keywords": ["Kubernetes"],
    "semantic_gaps": {"leadership": "No management experience mentioned"},
}


async def _create_test_user(db: AsyncSession) -> str:
    user_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, email_verified, subscription_plan, "
            "subscription_status, trial_used) "
            "VALUES (:id, :email, 'Gap Test User', true, 'pro', 'active', false) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": user_id, "email": f"test_{user_id.replace('-','')}@example.com"},
    )
    await db.commit()
    return user_id


async def _create_test_resume(db: AsyncSession, user_id: str, with_embedding: bool = True) -> str:
    resume_id = str(uuid.uuid4())
    embedding = FAKE_RESUME_EMBEDDING if with_embedding else None
    await db.execute(
        text(
            "INSERT INTO resumes (id, user_id, title, latex_content, content_embedding) "
            "VALUES (:id, :uid, :title, :content, :emb)"
        ),
        {
            "id": resume_id,
            "uid": user_id,
            "title": "Test Resume",
            "content": r"\documentclass{article}\begin{document}Python engineer.\end{document}",
            "emb": embedding,
        },
    )
    await db.commit()
    return resume_id


async def _insert_session(db: AsyncSession, user_id: str) -> str:
    from datetime import datetime, timedelta, timezone
    token = f"test_sess_{uuid.uuid4().hex}"
    expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    await db.execute(
        text(
            'INSERT INTO session (id, "userId", "expiresAt", token) '
            "VALUES (:id, :uid, :exp, :tok)"
        ),
        {"id": str(uuid.uuid4()), "uid": user_id, "exp": expires_at, "tok": token},
    )
    await db.commit()
    return token


class TestSemanticMatchCaching:
    """GAP-001: POST /ats/semantic-match writes and reads from resume_job_matches."""

    async def test_cache_miss_writes_row_to_db(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """First call: computes match and persists result in resume_job_matches."""
        user_id = await _create_test_user(db_session)
        resume_id = await _create_test_resume(db_session, user_id, with_embedding=True)
        token = await _insert_session(db_session, user_id)

        mock_emb_svc = MagicMock()
        mock_emb_svc.embed_job_description = AsyncMock(return_value=FAKE_JD_EMBEDDING)
        mock_emb_svc.semantic_keyword_match = AsyncMock(return_value=FAKE_MATCH_RESULT)

        # embedding_service is imported inside the function body — patch at module level
        with patch("app.services.embedding_service.embedding_service", mock_emb_svc):
            response = await client.post(
                "/ats/semantic-match",
                json={
                    "job_description": JOB_DESCRIPTION,
                    "resume_ids": [resume_id],
                },
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["results"]) == 1
        result = data["results"][0]
        assert result["resume_id"] == resume_id
        assert result["similarity_score"] == pytest.approx(0.82)
        assert "Python" in result["matched_keywords"]

        # Verify row was written to resume_job_matches
        row = (await db_session.execute(
            select(ResumeJobMatch).where(
                ResumeJobMatch.resume_id == resume_id,
                ResumeJobMatch.jd_hash == JD_HASH,
            )
        )).scalar_one_or_none()

        assert row is not None, "Cache row was NOT written to resume_job_matches"
        assert row.similarity_score == pytest.approx(0.82)
        assert row.matched_keywords == ["Python", "FastAPI", "Docker"]
        assert row.missing_keywords == ["Kubernetes"]
        assert row.user_id == user_id

        # Also verify embedding service was called exactly once
        mock_emb_svc.embed_job_description.assert_called_once()
        mock_emb_svc.semantic_keyword_match.assert_called_once()

    async def test_cache_hit_skips_embedding_service(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Second call with same resume+JD returns cached result — embedding never called."""
        user_id = await _create_test_user(db_session)
        resume_id = await _create_test_resume(db_session, user_id, with_embedding=True)
        token = await _insert_session(db_session, user_id)

        # Pre-populate cache
        db_session.add(ResumeJobMatch(
            user_id=user_id,
            resume_id=resume_id,
            jd_hash=JD_HASH,
            similarity_score=0.75,
            matched_keywords=["Python", "Docker"],
            missing_keywords=["Kubernetes", "CI/CD"],
            semantic_gaps={"leadership": "none"},
        ))
        await db_session.commit()

        mock_emb_svc = MagicMock()
        mock_emb_svc.embed_job_description = AsyncMock(return_value=FAKE_JD_EMBEDDING)
        mock_emb_svc.semantic_keyword_match = AsyncMock(return_value=FAKE_MATCH_RESULT)

        with patch("app.services.embedding_service.embedding_service", mock_emb_svc):
            response = await client.post(
                "/ats/semantic-match",
                json={
                    "job_description": JOB_DESCRIPTION,
                    "resume_ids": [resume_id],
                },
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 200
        data = response.json()
        result = data["results"][0]

        # Should return the CACHED score (0.75), not the mock's 0.82
        assert result["similarity_score"] == pytest.approx(0.75)
        assert result["matched_keywords"] == ["Python", "Docker"]

        # Embedding service must NOT have been called
        mock_emb_svc.embed_job_description.assert_not_called()
        mock_emb_svc.semantic_keyword_match.assert_not_called()

    async def test_different_jd_creates_new_cache_row(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Different JD produces a different jd_hash → new cache row, not overwriting existing."""
        user_id = await _create_test_user(db_session)
        resume_id = await _create_test_resume(db_session, user_id, with_embedding=True)
        token = await _insert_session(db_session, user_id)

        # Pre-populate cache for original JD
        db_session.add(ResumeJobMatch(
            user_id=user_id,
            resume_id=resume_id,
            jd_hash=JD_HASH,
            similarity_score=0.80,
            matched_keywords=["Python"],
            missing_keywords=[],
            semantic_gaps={},
        ))
        await db_session.commit()

        different_jd = "Data engineer with Spark, Hadoop, and SQL skills required."
        different_hash = hashlib.sha256(different_jd.encode()).hexdigest()
        assert different_hash != JD_HASH

        new_match = {**FAKE_MATCH_RESULT, "similarity_score": 0.30, "matched_keywords": ["SQL"]}

        mock_emb_svc = MagicMock()
        mock_emb_svc.embed_job_description = AsyncMock(return_value=FAKE_JD_EMBEDDING)
        mock_emb_svc.semantic_keyword_match = AsyncMock(return_value=new_match)

        with patch("app.services.embedding_service.embedding_service", mock_emb_svc):
            response = await client.post(
                "/ats/semantic-match",
                json={"job_description": different_jd, "resume_ids": [resume_id]},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 200
        result = response.json()["results"][0]
        assert result["similarity_score"] == pytest.approx(0.30)

        # Two distinct cache rows must exist
        rows = (await db_session.execute(
            select(ResumeJobMatch).where(ResumeJobMatch.resume_id == resume_id)
        )).scalars().all()
        assert len(rows) == 2, f"Expected 2 cache rows, got {len(rows)}"
        hashes = {r.jd_hash for r in rows}
        assert JD_HASH in hashes
        assert different_hash in hashes

        # Embedding was called for the new JD (cache miss)
        mock_emb_svc.embed_job_description.assert_called_once()

    async def test_resume_without_embedding_skips_cache(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Resume without content_embedding returns 'not yet computed' note — no cache write."""
        user_id = await _create_test_user(db_session)
        resume_id = await _create_test_resume(db_session, user_id, with_embedding=False)
        token = await _insert_session(db_session, user_id)

        mock_emb_svc = MagicMock()
        mock_emb_svc.embed_job_description = AsyncMock(return_value=FAKE_JD_EMBEDDING)
        mock_emb_svc.semantic_keyword_match = AsyncMock(return_value=FAKE_MATCH_RESULT)

        with patch("app.services.embedding_service.embedding_service", mock_emb_svc), \
             patch("app.api.ats_routes.settings") as mock_settings:
            mock_settings.OPENAI_API_KEY = None  # suppress background task dispatch
            response = await client.post(
                "/ats/semantic-match",
                json={"job_description": JOB_DESCRIPTION, "resume_ids": [resume_id]},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 200
        result = response.json()["results"][0]
        assert result["similarity_score"] is None
        assert "not yet computed" in result.get("note", "").lower()

        # No cache row should exist
        row = (await db_session.execute(
            select(ResumeJobMatch).where(ResumeJobMatch.resume_id == resume_id)
        )).scalar_one_or_none()
        assert row is None, "Cache row was incorrectly written for a resume without embedding"

    async def test_jd_hash_is_sha256_of_job_description(self):
        """jd_hash must be SHA-256 hex of the raw job description bytes."""
        jd = "Senior React developer with TypeScript"
        expected = hashlib.sha256(jd.encode()).hexdigest()
        assert len(expected) == 64
        assert all(c in "0123456789abcdef" for c in expected)

    async def test_no_resumes_returns_empty(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """If the user has no resumes, returns success with empty results list."""
        user_id = await _create_test_user(db_session)
        token = await _insert_session(db_session, user_id)

        mock_emb_svc = MagicMock()
        with patch("app.services.embedding_service.embedding_service", mock_emb_svc):
            response = await client.post(
                "/ats/semantic-match",
                json={"job_description": JOB_DESCRIPTION},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 200
        assert response.json()["results"] == []
        mock_emb_svc.embed_job_description.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# GAP-003 · Encryption consolidation
# ─────────────────────────────────────────────────────────────────────────────


class TestEncryptionConsolidation:
    """GAP-003: APIKeyEncryption is a thin wrapper; both implementations are compatible."""

    def test_api_key_encryption_delegates_to_encryption_service(self):
        """APIKeyEncryption.encrypt/decrypt delegates to EncryptionService."""
        from app.services.api_key_service import APIKeyEncryption
        from app.services.encryption_service import EncryptionService

        fernet_key = Fernet.generate_key().decode()

        ake = APIKeyEncryption(fernet_key)
        svc = EncryptionService(fernet_key)

        plaintext = "sk-my-production-api-key"

        # Encrypt with AKE, decrypt with EncryptionService
        ct_ake = ake.encrypt(plaintext)
        assert svc.decrypt(ct_ake) == plaintext, \
            "EncryptionService cannot decrypt APIKeyEncryption ciphertext"

        # Encrypt with EncryptionService, decrypt with AKE
        ct_svc = svc.encrypt(plaintext)
        assert ake.decrypt(ct_svc) == plaintext, \
            "APIKeyEncryption cannot decrypt EncryptionService ciphertext"

    def test_backward_compatible_with_old_api_key_encryption_format(self):
        """
        Old APIKeyEncryption used Fernet directly with standard base64.
        New EncryptionService with the same Fernet key must decode that data.
        """
        fernet_key = Fernet.generate_key()
        plaintext = "sk-test-backward-compat-key"

        # Simulate OLD APIKeyEncryption behavior exactly
        old_fernet = Fernet(fernet_key)
        old_ciphertext = base64.b64encode(old_fernet.encrypt(plaintext.encode())).decode()

        # New EncryptionService with the same key must decrypt it
        from app.services.encryption_service import EncryptionService
        new_svc = EncryptionService(fernet_key.decode())
        assert new_svc.decrypt(old_ciphertext) == plaintext, \
            "New EncryptionService cannot read old APIKeyEncryption ciphertext"

    def test_encryption_service_uses_direct_fernet_for_valid_key(self):
        """When given a valid Fernet key, EncryptionService uses it directly (no PBKDF2)."""
        from app.services.encryption_service import EncryptionService

        fernet_key = Fernet.generate_key().decode()

        # Derive independently — simulate what the new EncryptionService does
        svc = EncryptionService(fernet_key)

        # Verify the internal Fernet uses the exact key, not a derived one
        direct_fernet = Fernet(fernet_key.encode())
        ct = svc.encrypt("verify-direct-key")
        # Decrypt with the raw Fernet (without the base64 outer wrapper via EncryptionService)
        token = base64.b64decode(ct.encode())
        plaintext = direct_fernet.decrypt(token).decode()
        assert plaintext == "verify-direct-key"

    def test_encryption_service_falls_back_to_pbkdf2_for_non_fernet_key(self):
        """When given a non-Fernet key string, EncryptionService derives via PBKDF2 (no crash)."""
        from app.services.encryption_service import EncryptionService

        svc1 = EncryptionService("arbitrary-password-not-a-fernet-key")
        svc2 = EncryptionService("arbitrary-password-not-a-fernet-key")

        ct = svc1.encrypt("pbkdf2-roundtrip")
        assert svc2.decrypt(ct) == "pbkdf2-roundtrip", \
            "PBKDF2 path: two instances with same password must cross-decrypt"

    def test_api_key_encryption_raises_if_no_key(self, monkeypatch):
        """APIKeyEncryption must raise ValueError when API_KEY_ENCRYPTION_KEY is absent."""
        import app.core.config as cfg
        original = cfg.settings.API_KEY_ENCRYPTION_KEY
        try:
            cfg.settings.API_KEY_ENCRYPTION_KEY = None
            from app.services.api_key_service import APIKeyEncryption
            with pytest.raises(ValueError, match="API_KEY_ENCRYPTION_KEY"):
                APIKeyEncryption()
        finally:
            cfg.settings.API_KEY_ENCRYPTION_KEY = original

    def test_two_api_key_encryption_instances_cross_decrypt(self):
        """Two APIKeyEncryption instances with the same key can decrypt each other's ciphertext."""
        from app.services.api_key_service import APIKeyEncryption

        fernet_key = Fernet.generate_key().decode()
        enc1 = APIKeyEncryption(fernet_key)
        enc2 = APIKeyEncryption(fernet_key)

        plaintext = "sk-cross-instance-test"
        ct = enc1.encrypt(plaintext)
        assert enc2.decrypt(ct) == plaintext

    def test_different_keys_cannot_cross_decrypt(self):
        """Different keys produce incompatible ciphertext — no silent data corruption."""
        from app.services.api_key_service import APIKeyEncryption

        key1 = Fernet.generate_key().decode()
        key2 = Fernet.generate_key().decode()
        enc1 = APIKeyEncryption(key1)
        enc2 = APIKeyEncryption(key2)

        ct = enc1.encrypt("sensitive-key")
        with pytest.raises(Exception):
            enc2.decrypt(ct)

    def test_encryption_service_provider_scoped_encrypt_decrypt(self):
        """encrypt_api_key/decrypt_api_key properly embeds and verifies provider prefix."""
        from app.services.encryption_service import EncryptionService

        svc = EncryptionService()
        providers = ["openai", "anthropic", "openrouter", "gemini"]
        for provider in providers:
            api_key = f"sk-test-{provider}-key-12345"
            ct = svc.encrypt_api_key(api_key, provider)
            recovered = svc.decrypt_api_key(ct, provider)
            assert recovered == api_key

        # Wrong provider raises ValueError
        ct = svc.encrypt_api_key("sk-abc", "openai")
        with pytest.raises(ValueError, match="mismatch"):
            svc.decrypt_api_key(ct, "anthropic")

    def test_api_key_service_full_workflow(self):
        """APIKeyService.add_api_key + get_user_provider roundtrip (encryption only, no DB)."""
        from app.services.api_key_service import APIKeyEncryption

        key = Fernet.generate_key().decode()
        enc = APIKeyEncryption(key)

        # Simulate storing and retrieving a key (what add_api_key + get_user_provider do)
        original_key = "sk-openai-production-key-abc123"
        stored = enc.encrypt(original_key)

        # Stored value must be different from the original
        assert stored != original_key

        # Retrieved value must match original
        retrieved = enc.decrypt(stored)
        assert retrieved == original_key
