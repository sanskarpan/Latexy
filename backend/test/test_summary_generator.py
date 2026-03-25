"""
Tests for Feature 24: AI Professional Summary Generator.

Covers:
  - POST /ai/generate-summary returns 3 summaries (default count)
  - Each summary has emphasis, title, text fields
  - text is non-empty and has no JSON artifacts
  - count=1 → returns 1 summary
  - resume_latex too large → 422
  - Cached response returns cached=True
  - No API key returns empty summaries
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SETTINGS_PATCH = "app.api.ai_routes.settings"


def _mock_settings(mock) -> None:
    mock.OPENAI_API_KEY = "sk-test-dummy"
    mock.OPENAI_MODEL = "gpt-4o-mini"


def _make_openai_summary_response(summaries: list[dict]) -> MagicMock:
    choice = MagicMock()
    choice.message.content = json.dumps({"summaries": summaries})
    resp = MagicMock()
    resp.choices = [choice]
    return resp


_SAMPLE_3 = [
    {
        "emphasis": "technical",
        "title": "Technical Skills Focus",
        "text": "Full-stack engineer with 7 years building distributed systems at scale. "
                "Specialised in Go microservices and Kubernetes, delivering 99.99% uptime. "
                "Led architecture redesign cutting p99 latency by 60%.",
    },
    {
        "emphasis": "leadership",
        "title": "Leadership & Impact",
        "text": "Engineering manager who grew a 3-person squad to 12, shipping 4 major product lines. "
                "Championed developer productivity, reducing CI times from 20 min to 4 min. "
                "Directly accountable for $2M ARR expansion through platform reliability.",
    },
    {
        "emphasis": "unique",
        "title": "Unique Differentiator",
        "text": "Former competitive mathematician turned systems engineer — brings rigorous proof-based "
                "thinking to distributed consensus problems. Open-source contributor to etcd with "
                "3k GitHub stars. Speaker at KubeCon 2023 on low-latency storage.",
    },
]

_SAMPLE_1 = [_SAMPLE_3[0]]

_SAMPLE_RESUME = r"""
\documentclass{article}
\begin{document}
\name{Jane Doe}
\section{Summary}
Experienced software engineer.
\section{Experience}
\begin{itemize}
\item Built payment API
\end{itemize}
\end{document}
"""


# ---------------------------------------------------------------------------
# 24A — Validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSummaryGeneratorValidation:
    async def test_resume_latex_too_large_returns_422(self, client: AsyncClient):
        resp = await client.post(
            "/ai/generate-summary",
            json={"resume_latex": "x" * 50_001},
        )
        assert resp.status_code == 422

    async def test_count_zero_returns_422(self, client: AsyncClient):
        resp = await client.post(
            "/ai/generate-summary",
            json={"resume_latex": _SAMPLE_RESUME, "count": 0},
        )
        assert resp.status_code == 422

    async def test_count_six_returns_422(self, client: AsyncClient):
        resp = await client.post(
            "/ai/generate-summary",
            json={"resume_latex": _SAMPLE_RESUME, "count": 6},
        )
        assert resp.status_code == 422

    async def test_target_role_too_long_returns_422(self, client: AsyncClient):
        resp = await client.post(
            "/ai/generate-summary",
            json={"resume_latex": _SAMPLE_RESUME, "target_role": "x" * 201},
        )
        assert resp.status_code == 422

    async def test_job_description_too_long_returns_422(self, client: AsyncClient):
        resp = await client.post(
            "/ai/generate-summary",
            json={"resume_latex": _SAMPLE_RESUME, "job_description": "x" * 5001},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 24B — LLM-backed responses
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSummaryGeneratorLLM:
    async def test_default_count_returns_3_summaries(self, client: AsyncClient):
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
                return_value=_make_openai_summary_response(_SAMPLE_3)
            )
            mock_cls.return_value = mock_openai

            resp = await client.post(
                "/ai/generate-summary",
                json={"resume_latex": _SAMPLE_RESUME},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["summaries"]) == 3
            assert data["cached"] is False

    async def test_each_summary_has_required_fields(self, client: AsyncClient):
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
                return_value=_make_openai_summary_response(_SAMPLE_3)
            )
            mock_cls.return_value = mock_openai

            resp = await client.post(
                "/ai/generate-summary",
                json={"resume_latex": _SAMPLE_RESUME},
            )
            data = resp.json()
            for s in data["summaries"]:
                assert "emphasis" in s, "Missing emphasis"
                assert "title" in s, "Missing title"
                assert "text" in s, "Missing text"
                assert s["text"], "text must not be empty"

    async def test_text_has_no_json_artifacts(self, client: AsyncClient):
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
                return_value=_make_openai_summary_response(_SAMPLE_3)
            )
            mock_cls.return_value = mock_openai

            resp = await client.post(
                "/ai/generate-summary",
                json={"resume_latex": _SAMPLE_RESUME},
            )
            data = resp.json()
            for s in data["summaries"]:
                text = s["text"]
                assert "{" not in text or "}" not in text or not text.startswith("{"), (
                    f"text looks like raw JSON: {text!r}"
                )

    async def test_count_1_returns_1_summary(self, client: AsyncClient):
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
                return_value=_make_openai_summary_response(_SAMPLE_1)
            )
            mock_cls.return_value = mock_openai

            resp = await client.post(
                "/ai/generate-summary",
                json={"resume_latex": _SAMPLE_RESUME, "count": 1},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["summaries"]) == 1

    async def test_second_call_returns_cached(self, client: AsyncClient):
        cached_data = {"summaries": [s for s in _SAMPLE_3]}
        with patch(
            "app.api.ai_routes.cache_manager.get",
            new_callable=AsyncMock,
            return_value=cached_data,
        ):
            resp = await client.post(
                "/ai/generate-summary",
                json={"resume_latex": _SAMPLE_RESUME},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["cached"] is True
            assert len(data["summaries"]) == 3

    async def test_optional_fields_accepted(self, client: AsyncClient):
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
                return_value=_make_openai_summary_response(_SAMPLE_3)
            )
            mock_cls.return_value = mock_openai

            resp = await client.post(
                "/ai/generate-summary",
                json={
                    "resume_latex": _SAMPLE_RESUME,
                    "target_role": "Senior Software Engineer",
                    "job_description": "We are looking for a backend engineer...",
                    "count": 3,
                },
            )
            assert resp.status_code == 200

    async def test_no_api_key_returns_empty_summaries(self, client: AsyncClient):
        with patch(
            "app.api.ai_routes.cache_manager.get", new_callable=AsyncMock, return_value=None
        ), patch(_SETTINGS_PATCH) as mock_settings:
            mock_settings.OPENAI_API_KEY = ""
            mock_settings.OPENAI_MODEL = "gpt-4o-mini"

            resp = await client.post(
                "/ai/generate-summary",
                json={"resume_latex": _SAMPLE_RESUME},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["summaries"] == []
