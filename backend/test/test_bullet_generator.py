"""
Tests for Feature 22: AI Bullet Point Generator.

Covers:
  - POST /ai/generate-bullets returns 5 bullets (default count)
  - Each bullet starts with a capital letter (action verb)
  - count=3 → returns exactly 3 bullets
  - Same request twice → cached=True on second call
  - responsibility too long (>500) → 422
  - job_title too long (>200) → 422
  - count out of range (0, 11) → 422
  - Endpoint accessible without auth (anonymous)
  - _bullet_cache_key produces consistent 16-char hex
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Helper: build a fake OpenAI response
# ---------------------------------------------------------------------------

def _make_openai_response(bullets: list[str]) -> MagicMock:
    import json
    choice = MagicMock()
    choice.message.content = json.dumps({"bullets": bullets})
    resp = MagicMock()
    resp.choices = [choice]
    return resp


_SAMPLE_5 = [
    "Led cross-functional team of 8 engineers to deliver payment gateway, reducing latency by 40%",
    "Engineered scalable microservices architecture processing 10M daily requests with 99.9% uptime",
    "Automated CI/CD pipeline cutting deployment time from 45 minutes to under 5 minutes",
    "Designed and shipped real-time analytics dashboard used by 200+ enterprise customers",
    "Reduced cloud infrastructure costs by 35% through resource optimisation and right-sizing",
]

_SAMPLE_3 = _SAMPLE_5[:3]

# Shared settings mock values used across LLM tests
_SETTINGS_PATCH = "app.api.ai_routes.settings"


def _mock_settings(mock):
    """Configure a mocked settings object for LLM tests."""
    mock.OPENAI_API_KEY = "sk-test-dummy"
    mock.OPENAI_MODEL = "gpt-4o-mini"


# ---------------------------------------------------------------------------
# 22A — cache key helper
# ---------------------------------------------------------------------------


class TestBulletCacheKey:
    def test_returns_16_hex_chars(self):
        from app.api.ai_routes import _bullet_cache_key
        key = _bullet_cache_key("SWE", "Built API", "technical", 5)
        suffix = key.removeprefix("ai:bullets:")
        assert len(suffix) == 16
        assert all(c in "0123456789abcdef" for c in suffix)

    def test_same_inputs_same_key(self):
        from app.api.ai_routes import _bullet_cache_key
        k1 = _bullet_cache_key("SWE", "Built API", "technical", 5)
        k2 = _bullet_cache_key("SWE", "Built API", "technical", 5)
        assert k1 == k2

    def test_different_tone_different_key(self):
        from app.api.ai_routes import _bullet_cache_key
        k1 = _bullet_cache_key("SWE", "Built API", "technical", 5)
        k2 = _bullet_cache_key("SWE", "Built API", "leadership", 5)
        assert k1 != k2

    def test_different_count_different_key(self):
        from app.api.ai_routes import _bullet_cache_key
        k1 = _bullet_cache_key("SWE", "Built API", "technical", 5)
        k2 = _bullet_cache_key("SWE", "Built API", "technical", 3)
        assert k1 != k2


# ---------------------------------------------------------------------------
# 22B — Endpoint validation (no LLM needed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestBulletGeneratorValidation:
    async def test_responsibility_too_long_returns_422(self, client: AsyncClient):
        resp = await client.post(
            "/ai/generate-bullets",
            json={
                "job_title": "Engineer",
                "responsibility": "x" * 501,
            },
        )
        assert resp.status_code == 422

    async def test_job_title_too_long_returns_422(self, client: AsyncClient):
        resp = await client.post(
            "/ai/generate-bullets",
            json={
                "job_title": "E" * 201,
                "responsibility": "Built stuff",
            },
        )
        assert resp.status_code == 422

    async def test_count_zero_returns_422(self, client: AsyncClient):
        resp = await client.post(
            "/ai/generate-bullets",
            json={
                "job_title": "Engineer",
                "responsibility": "Built stuff",
                "count": 0,
            },
        )
        assert resp.status_code == 422

    async def test_count_eleven_returns_422(self, client: AsyncClient):
        resp = await client.post(
            "/ai/generate-bullets",
            json={
                "job_title": "Engineer",
                "responsibility": "Built stuff",
                "count": 11,
            },
        )
        assert resp.status_code == 422

    async def test_anon_accessible(self, client: AsyncClient):
        """Endpoint works without Authorization header."""
        with patch(_SETTINGS_PATCH) as mock_settings, patch(
            "app.api.ai_routes.openai.AsyncOpenAI"
        ) as mock_cls, patch(
            "app.api.ai_routes.cache_manager.get", new_callable=AsyncMock, return_value=None
        ), patch(
            "app.api.ai_routes.cache_manager.set", new_callable=AsyncMock
        ):
            _mock_settings(mock_settings)
            mock_openai = AsyncMock()
            mock_openai.chat.completions.create = AsyncMock(
                return_value=_make_openai_response(_SAMPLE_5)
            )
            mock_cls.return_value = mock_openai

            resp = await client.post(
                "/ai/generate-bullets",
                json={"job_title": "Engineer", "responsibility": "Built API"},
                # No auth headers
            )
            assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 22C — LLM-backed responses (mock OpenAI + settings)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestBulletGeneratorLLM:
    async def test_default_count_returns_5_bullets(self, client: AsyncClient):
        with patch(_SETTINGS_PATCH) as mock_settings, patch(
            "app.api.ai_routes.openai.AsyncOpenAI"
        ) as mock_cls, patch(
            "app.api.ai_routes.cache_manager.get", new_callable=AsyncMock, return_value=None
        ), patch(
            "app.api.ai_routes.cache_manager.set", new_callable=AsyncMock
        ):
            _mock_settings(mock_settings)
            mock_openai = AsyncMock()
            mock_openai.chat.completions.create = AsyncMock(
                return_value=_make_openai_response(_SAMPLE_5)
            )
            mock_cls.return_value = mock_openai

            resp = await client.post(
                "/ai/generate-bullets",
                json={"job_title": "Software Engineer", "responsibility": "Built payment API"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["bullets"]) == 5
            assert data["cached"] is False

    async def test_each_bullet_starts_with_capital(self, client: AsyncClient):
        with patch(_SETTINGS_PATCH) as mock_settings, patch(
            "app.api.ai_routes.openai.AsyncOpenAI"
        ) as mock_cls, patch(
            "app.api.ai_routes.cache_manager.get", new_callable=AsyncMock, return_value=None
        ), patch(
            "app.api.ai_routes.cache_manager.set", new_callable=AsyncMock
        ):
            _mock_settings(mock_settings)
            mock_openai = AsyncMock()
            mock_openai.chat.completions.create = AsyncMock(
                return_value=_make_openai_response(_SAMPLE_5)
            )
            mock_cls.return_value = mock_openai

            resp = await client.post(
                "/ai/generate-bullets",
                json={"job_title": "Software Engineer", "responsibility": "Built payment API"},
            )
            data = resp.json()
            assert len(data["bullets"]) == 5
            for bullet in data["bullets"]:
                assert bullet[0].isupper(), f"Bullet does not start with capital: {bullet!r}"

    async def test_count_3_returns_3_bullets(self, client: AsyncClient):
        with patch(_SETTINGS_PATCH) as mock_settings, patch(
            "app.api.ai_routes.openai.AsyncOpenAI"
        ) as mock_cls, patch(
            "app.api.ai_routes.cache_manager.get", new_callable=AsyncMock, return_value=None
        ), patch(
            "app.api.ai_routes.cache_manager.set", new_callable=AsyncMock
        ):
            _mock_settings(mock_settings)
            mock_openai = AsyncMock()
            mock_openai.chat.completions.create = AsyncMock(
                return_value=_make_openai_response(_SAMPLE_3)
            )
            mock_cls.return_value = mock_openai

            resp = await client.post(
                "/ai/generate-bullets",
                json={
                    "job_title": "Software Engineer",
                    "responsibility": "Built payment API",
                    "count": 3,
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["bullets"]) == 3

    async def test_second_call_returns_cached(self, client: AsyncClient):
        """Second identical request should get cached=True (cache check is before API key check)."""
        cached_data = {"bullets": _SAMPLE_5}
        with patch(
            "app.api.ai_routes.cache_manager.get",
            new_callable=AsyncMock,
            return_value=cached_data,
        ):
            resp = await client.post(
                "/ai/generate-bullets",
                json={"job_title": "Engineer", "responsibility": "Built APIs"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["cached"] is True
            assert len(data["bullets"]) == 5

    async def test_response_has_bullets_and_cached_fields(self, client: AsyncClient):
        with patch(_SETTINGS_PATCH) as mock_settings, patch(
            "app.api.ai_routes.openai.AsyncOpenAI"
        ) as mock_cls, patch(
            "app.api.ai_routes.cache_manager.get", new_callable=AsyncMock, return_value=None
        ), patch(
            "app.api.ai_routes.cache_manager.set", new_callable=AsyncMock
        ):
            _mock_settings(mock_settings)
            mock_openai = AsyncMock()
            mock_openai.chat.completions.create = AsyncMock(
                return_value=_make_openai_response(_SAMPLE_5)
            )
            mock_cls.return_value = mock_openai

            resp = await client.post(
                "/ai/generate-bullets",
                json={"job_title": "PM", "responsibility": "Led roadmap planning"},
            )
            data = resp.json()
            assert "bullets" in data
            assert "cached" in data
            assert isinstance(data["bullets"], list)
            assert isinstance(data["cached"], bool)

    async def test_context_field_accepted(self, client: AsyncClient):
        """context optional field should be accepted without error."""
        with patch(_SETTINGS_PATCH) as mock_settings, patch(
            "app.api.ai_routes.openai.AsyncOpenAI"
        ) as mock_cls, patch(
            "app.api.ai_routes.cache_manager.get", new_callable=AsyncMock, return_value=None
        ), patch(
            "app.api.ai_routes.cache_manager.set", new_callable=AsyncMock
        ):
            _mock_settings(mock_settings)
            mock_openai = AsyncMock()
            mock_openai.chat.completions.create = AsyncMock(
                return_value=_make_openai_response(_SAMPLE_5)
            )
            mock_cls.return_value = mock_openai

            resp = await client.post(
                "/ai/generate-bullets",
                json={
                    "job_title": "Engineer",
                    "responsibility": "Built auth system",
                    "context": "Resume section: Experience at Acme Corp",
                    "tone": "leadership",
                    "count": 5,
                },
            )
            assert resp.status_code == 200

    async def test_no_api_key_returns_empty_bullets(self, client: AsyncClient):
        """When no API key is available, endpoint returns empty bullets gracefully."""
        with patch(
            "app.api.ai_routes.cache_manager.get", new_callable=AsyncMock, return_value=None
        ), patch(_SETTINGS_PATCH) as mock_settings:
            mock_settings.OPENAI_API_KEY = ""
            mock_settings.OPENAI_MODEL = "gpt-4o-mini"

            resp = await client.post(
                "/ai/generate-bullets",
                json={"job_title": "Engineer", "responsibility": "Built stuff"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["bullets"] == []
