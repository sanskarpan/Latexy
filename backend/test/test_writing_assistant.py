"""
Tests for Feature 23: AI Writing Assistant.

Covers:
  - Each action (improve, shorten, quantify, power_verbs, expand) returns a non-empty string
  - action=invalid → 422
  - selected_text too short (< 5 chars) → 422
  - selected_text too long (> 2000 chars) → 422
  - Same request twice → cached=True on second call
  - No API key → returns original text unchanged
  - change_tone action is accepted
  - _rewrite_cache_key produces consistent 16-char hex
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SETTINGS_PATCH = "app.api.ai_routes.settings"


def _mock_settings(mock: MagicMock) -> None:
    mock.OPENAI_API_KEY = "sk-test-dummy"
    mock.OPENAI_MODEL = "gpt-4o-mini"


def _make_openai_response(text: str) -> MagicMock:
    choice = MagicMock()
    choice.message.content = text
    resp = MagicMock()
    resp.choices = [choice]
    return resp


_SAMPLE_INPUT = "Led a team to build a payment integration that processed transactions."
_SAMPLE_REWRITTEN = "Spearheaded a cross-functional team delivering a payment integration processing 50K+ daily transactions."

# ---------------------------------------------------------------------------
# Cache key helper
# ---------------------------------------------------------------------------


class TestRewriteCacheKey:
    def test_returns_16_hex_chars(self) -> None:
        from app.api.ai_routes import _rewrite_cache_key

        key = _rewrite_cache_key("improve", _SAMPLE_INPUT, None)
        suffix = key.removeprefix("ai:rewrite:")
        assert len(suffix) == 16
        assert all(c in "0123456789abcdef" for c in suffix)

    def test_same_inputs_same_key(self) -> None:
        from app.api.ai_routes import _rewrite_cache_key

        k1 = _rewrite_cache_key("improve", _SAMPLE_INPUT, None)
        k2 = _rewrite_cache_key("improve", _SAMPLE_INPUT, None)
        assert k1 == k2

    def test_different_action_different_key(self) -> None:
        from app.api.ai_routes import _rewrite_cache_key

        k1 = _rewrite_cache_key("improve", _SAMPLE_INPUT, None)
        k2 = _rewrite_cache_key("shorten", _SAMPLE_INPUT, None)
        assert k1 != k2

    def test_tone_changes_key(self) -> None:
        from app.api.ai_routes import _rewrite_cache_key

        k1 = _rewrite_cache_key("change_tone", _SAMPLE_INPUT, "formal")
        k2 = _rewrite_cache_key("change_tone", _SAMPLE_INPUT, "casual")
        assert k1 != k2


# ---------------------------------------------------------------------------
# Validation tests (no LLM needed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRewriteValidation:
    async def test_invalid_action_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/ai/rewrite",
            json={"selected_text": _SAMPLE_INPUT, "action": "invalid_action"},
        )
        assert resp.status_code == 422

    async def test_text_too_short_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/ai/rewrite",
            json={"selected_text": "Hi", "action": "improve"},
        )
        assert resp.status_code == 422

    async def test_text_too_long_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/ai/rewrite",
            json={"selected_text": "x" * 2001, "action": "improve"},
        )
        assert resp.status_code == 422

    async def test_context_too_long_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/ai/rewrite",
            json={
                "selected_text": _SAMPLE_INPUT,
                "action": "improve",
                "context": "c" * 1001,
            },
        )
        assert resp.status_code == 422

    async def test_change_tone_accepted(self, client: AsyncClient) -> None:
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
                return_value=_make_openai_response(_SAMPLE_REWRITTEN)
            )
            mock_cls.return_value = mock_openai

            resp = await client.post(
                "/ai/rewrite",
                json={
                    "selected_text": _SAMPLE_INPUT,
                    "action": "change_tone",
                    "tone": "formal",
                },
            )
            assert resp.status_code == 200


# ---------------------------------------------------------------------------
# LLM-backed tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRewriteLLM:
    async def _call(
        self,
        client: AsyncClient,
        action: str,
        rewritten: str = _SAMPLE_REWRITTEN,
    ) -> dict:
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
                return_value=_make_openai_response(rewritten)
            )
            mock_cls.return_value = mock_openai

            resp = await client.post(
                "/ai/rewrite",
                json={"selected_text": _SAMPLE_INPUT, "action": action},
            )
            assert resp.status_code == 200
            return resp.json()

    async def test_improve_returns_non_empty(self, client: AsyncClient) -> None:
        data = await self._call(client, "improve")
        assert data["rewritten"]
        assert data["action"] == "improve"
        assert data["cached"] is False

    async def test_shorten_returns_non_empty(self, client: AsyncClient) -> None:
        data = await self._call(client, "shorten", "Spearheaded payment integration.")
        assert data["rewritten"]
        assert data["action"] == "shorten"

    async def test_quantify_returns_non_empty(self, client: AsyncClient) -> None:
        data = await self._call(client, "quantify")
        assert data["rewritten"]

    async def test_power_verbs_returns_non_empty(self, client: AsyncClient) -> None:
        data = await self._call(client, "power_verbs")
        assert data["rewritten"]

    async def test_expand_returns_non_empty(self, client: AsyncClient) -> None:
        data = await self._call(client, "expand")
        assert data["rewritten"]

    async def test_response_fields_present(self, client: AsyncClient) -> None:
        data = await self._call(client, "improve")
        assert "rewritten" in data
        assert "action" in data
        assert "cached" in data
        assert isinstance(data["rewritten"], str)
        assert isinstance(data["cached"], bool)

    async def test_second_call_returns_cached(self, client: AsyncClient) -> None:
        cached_data = {"rewritten": _SAMPLE_REWRITTEN}
        with patch(
            "app.api.ai_routes.cache_manager.get",
            new_callable=AsyncMock,
            return_value=cached_data,
        ):
            resp = await client.post(
                "/ai/rewrite",
                json={"selected_text": _SAMPLE_INPUT, "action": "improve"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["cached"] is True
            assert data["rewritten"] == _SAMPLE_REWRITTEN

    async def test_no_api_key_returns_original_text(self, client: AsyncClient) -> None:
        with patch(
            "app.api.ai_routes.cache_manager.get", new_callable=AsyncMock, return_value=None
        ), patch(_SETTINGS_PATCH) as mock_settings:
            mock_settings.OPENAI_API_KEY = ""
            mock_settings.OPENAI_MODEL = "gpt-4o-mini"

            resp = await client.post(
                "/ai/rewrite",
                json={"selected_text": _SAMPLE_INPUT, "action": "improve"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["rewritten"] == _SAMPLE_INPUT
            assert data["cached"] is False

    async def test_context_field_accepted(self, client: AsyncClient) -> None:
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
                return_value=_make_openai_response(_SAMPLE_REWRITTEN)
            )
            mock_cls.return_value = mock_openai

            resp = await client.post(
                "/ai/rewrite",
                json={
                    "selected_text": _SAMPLE_INPUT,
                    "action": "improve",
                    "context": "\\section{Experience}\n\\begin{itemize}",
                },
            )
            assert resp.status_code == 200
