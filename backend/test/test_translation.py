"""
Tests for Feature 44: Multilingual Resume Translation.

Covers:
  - _translate_cache_key unit tests (prefix, determinism, sensitivity)
  - Validation: missing/too-long fields → 422
  - Endpoint: LaTeX command preservation, variant title, caching, auth, 404, 503
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


_SAMPLE_LATEX = r"""
\documentclass{article}
\begin{document}
\section{Experience}
\textbf{Senior Engineer} at Acme Corp\\
\begin{itemize}
\item Developed scalable microservices architecture
\item Led team of 5 engineers to deliver platform
\end{itemize}
\section{Education}
B.Sc. Computer Science, MIT, 2018
\end{document}
"""

_TRANSLATED_FR = r"""
\documentclass{article}
\begin{document}
\section{Expérience}
\textbf{Ingénieur Senior} at Acme Corp\\
\begin{itemize}
\item Développé une architecture de microservices évolutive
\item Dirigé une équipe de 5 ingénieurs
\end{itemize}
\section{Formation}
B.Sc. Informatique, MIT, 2018
\end{document}
"""

# ---------------------------------------------------------------------------
# Cache key unit tests (no server needed)
# ---------------------------------------------------------------------------


class TestTranslateCacheKey:
    def test_returns_ai_translate_prefix(self) -> None:
        from app.api.ai_routes import _translate_cache_key

        key = _translate_cache_key(_SAMPLE_LATEX, "French")
        assert key.startswith("ai:translate:")

    def test_same_inputs_same_key(self) -> None:
        from app.api.ai_routes import _translate_cache_key

        k1 = _translate_cache_key(_SAMPLE_LATEX, "French")
        k2 = _translate_cache_key(_SAMPLE_LATEX, "French")
        assert k1 == k2

    def test_different_language_different_key(self) -> None:
        from app.api.ai_routes import _translate_cache_key

        k1 = _translate_cache_key(_SAMPLE_LATEX, "French")
        k2 = _translate_cache_key(_SAMPLE_LATEX, "German")
        assert k1 != k2

    def test_only_first_1000_chars_used(self) -> None:
        """Two inputs differing only after char 1000 should produce the same key."""
        from app.api.ai_routes import _translate_cache_key

        base = "x" * 1000
        content_a = base + "AAA"
        content_b = base + "BBB"
        k1 = _translate_cache_key(content_a, "French")
        k2 = _translate_cache_key(content_b, "French")
        assert k1 == k2


# ---------------------------------------------------------------------------
# Validation tests — no auth required, just bad payloads → 422
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTranslateValidation:
    async def test_missing_target_language_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/ai/translate",
            json={"resume_id": "some-id", "language_code": "fr"},
        )
        assert resp.status_code == 422

    async def test_target_language_too_long_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/ai/translate",
            json={
                "resume_id": "some-id",
                "target_language": "F" * 51,
                "language_code": "fr",
            },
        )
        assert resp.status_code == 422

    async def test_language_code_too_long_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/ai/translate",
            json={
                "resume_id": "some-id",
                "target_language": "French",
                "language_code": "f" * 11,
            },
        )
        assert resp.status_code == 422

    async def test_missing_resume_id_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/ai/translate",
            json={"target_language": "French", "language_code": "fr"},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Full endpoint tests — require auth and a real DB resume row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTranslateEndpoint:
    async def _create_resume(self, client: AsyncClient, auth_headers: dict) -> str:
        """Helper: create a resume and return its ID."""
        resp = await client.post(
            "/resumes/",
            json={"title": "Test Resume for Translation", "latex_content": _SAMPLE_LATEX},
            headers=auth_headers,
        )
        assert resp.status_code in (200, 201), f"Resume creation failed: {resp.text}"
        return resp.json()["id"]

    async def test_latex_commands_preserved(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        resume_id = await self._create_resume(client, auth_headers)

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
                return_value=_make_openai_response(_TRANSLATED_FR)
            )
            mock_cls.return_value = mock_openai

            resp = await client.post(
                "/ai/translate",
                json={
                    "resume_id": resume_id,
                    "target_language": "French",
                    "language_code": "fr",
                },
                headers=auth_headers,
            )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["success"] is True
        assert "variant_resume_id" in data

        # Verify variant preserves LaTeX structure
        variant_resp = await client.get(
            f"/resumes/{data['variant_resume_id']}", headers=auth_headers
        )
        assert variant_resp.status_code == 200
        assert r"\section" in variant_resp.json()["latex_content"]

    async def test_variant_title_has_language_code(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        resume_id = await self._create_resume(client, auth_headers)

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
                return_value=_make_openai_response(_TRANSLATED_FR)
            )
            mock_cls.return_value = mock_openai

            resp = await client.post(
                "/ai/translate",
                json={
                    "resume_id": resume_id,
                    "target_language": "French",
                    "language_code": "fr",
                },
                headers=auth_headers,
            )

        assert resp.status_code == 200, resp.text
        variant_id = resp.json()["variant_resume_id"]

        variant_resp = await client.get(f"/resumes/{variant_id}", headers=auth_headers)
        assert variant_resp.status_code == 200
        assert variant_resp.json()["title"].endswith("— [FR]")

    async def test_cached_on_second_call(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        resume_id = await self._create_resume(client, auth_headers)

        # Second call: cache returns the translated string
        with patch(
            "app.api.ai_routes.cache_manager.get",
            new_callable=AsyncMock,
            return_value=_TRANSLATED_FR,
        ), patch(
            "app.api.ai_routes.cache_manager.set", new_callable=AsyncMock
        ):
            resp = await client.post(
                "/ai/translate",
                json={
                    "resume_id": resume_id,
                    "target_language": "French",
                    "language_code": "fr",
                },
                headers=auth_headers,
            )

        assert resp.status_code == 200, resp.text
        assert resp.json()["cached"] is True

    async def test_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/ai/translate",
            json={
                "resume_id": "00000000-0000-0000-0000-000000000001",
                "target_language": "French",
                "language_code": "fr",
            },
        )
        assert resp.status_code in (401, 403)

    async def test_resume_not_found(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        import uuid

        with patch(_SETTINGS_PATCH) as mock_settings, patch(
            "app.api.ai_routes.cache_manager.get", new_callable=AsyncMock, return_value=None
        ):
            _mock_settings(mock_settings)
            resp = await client.post(
                "/ai/translate",
                json={
                    "resume_id": str(uuid.uuid4()),
                    "target_language": "French",
                    "language_code": "fr",
                },
                headers=auth_headers,
            )

        assert resp.status_code == 404

    async def test_no_api_key_returns_503(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        resume_id = await self._create_resume(client, auth_headers)

        with patch(_SETTINGS_PATCH) as mock_settings, patch(
            "app.api.ai_routes.cache_manager.get", new_callable=AsyncMock, return_value=None
        ), patch(
            "app.api.ai_routes.api_key_service.get_user_provider",
            new_callable=AsyncMock,
            return_value=None,
        ):
            mock_settings.OPENAI_API_KEY = ""
            mock_settings.OPENAI_MODEL = "gpt-4o-mini"

            resp = await client.post(
                "/ai/translate",
                json={
                    "resume_id": resume_id,
                    "target_language": "French",
                    "language_code": "fr",
                },
                headers=auth_headers,
            )

        assert resp.status_code == 503
