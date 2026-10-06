import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.api.ai_routes import PhraseLibraryRequest, _phrase_library_cache_key

PHRASES = [
    {
        "text": "Engineered scalable services that improved request throughput by 37% across 14 regions.",
        "signals": ["technical_depth", "high_impact"],
    },
    {
        "text": "Led cross-functional delivery of platform initiatives while mentoring 12 engineers.",
        "signals": ["leadership", "high_impact"],
    },
    {
        "text": "Optimized distributed-system reliability to sustain 99.9% uptime for critical workflows.",
        "signals": ["technical_depth", "ats_friendly"],
    },
    {
        "text": "Automated deployment controls that reduced release lead time by 45% without weakening quality.",
        "signals": ["high_impact", "technical_depth"],
    },
    {
        "text": "Directed architecture reviews that aligned 8 product teams around resilient service standards.",
        "signals": ["leadership", "technical_depth"],
    },
    {
        "text": "Established observability practices that shortened incident recovery by 30% for core services.",
        "signals": ["ats_friendly", "high_impact"],
    },
    {
        "text": "Delivered cloud-efficiency improvements that saved $2M while maintaining service objectives.",
        "signals": ["high_impact", "technical_depth"],
    },
    {
        "text": "Partnered with product leaders to translate customer needs into 6 measurable platform outcomes.",
        "signals": ["leadership", "ats_friendly"],
    },
]


def _provider_response(phrases=PHRASES):
    choice = MagicMock()
    choice.message.content = json.dumps({"phrases": phrases})
    response = MagicMock()
    response.choices = [choice]
    return response


def _request(**overrides):
    return {
        "job_title": "Platform Engineer",
        "seniority": "senior",
        "industry": "Financial Services",
        "skill_category": "Distributed Systems",
        "count": 8,
        **overrides,
    }


def test_cache_key_uses_every_index_axis_and_count():
    base = PhraseLibraryRequest(**_request())
    first = _phrase_library_cache_key(base)

    assert first == _phrase_library_cache_key(PhraseLibraryRequest(**_request()))
    assert first != _phrase_library_cache_key(PhraseLibraryRequest(**_request(seniority="lead")))
    assert first != _phrase_library_cache_key(PhraseLibraryRequest(**_request(skill_category="Reliability")))


@pytest.mark.asyncio
async def test_generates_tagged_phrases_and_replaces_every_fabricated_metric(
    client: AsyncClient,
):
    provider = AsyncMock()
    provider.chat.completions.create = AsyncMock(return_value=_provider_response())
    with (
        patch("app.api.ai_routes.settings") as settings,
        patch("app.api.ai_routes.openai.AsyncOpenAI", return_value=provider),
        patch("app.api.ai_routes.cache_manager.get", new=AsyncMock(return_value=None)),
        patch("app.api.ai_routes.cache_manager.set", new=AsyncMock()) as cache_set,
    ):
        settings.OPENAI_API_KEY = "sk-test"
        settings.OPENAI_MODEL = "gpt-4o-mini"
        response = await client.post("/ai/phrase-library", json=_request())

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["cached"] is False
    assert len(body["phrases"]) == 8
    assert all(item["signals"] for item in body["phrases"])
    assert all(not any(character.isdigit() for character in item["text"]) for item in body["phrases"])
    assert all("[X]" in item["text"] for item in body["phrases"])
    cache_set.assert_awaited_once()
    assert cache_set.await_args.kwargs["ttl"] == 604800


@pytest.mark.asyncio
async def test_valid_cached_library_avoids_provider_and_is_labeled_cached(
    client: AsyncClient,
):
    cached = {
        "phrases": [
            {
                "text": item["text"]
                .replace("37%", "[X]%")
                .replace("12", "[X]")
                .replace("99.9%", "[X]%")
                .replace("45%", "[X]%")
                .replace("8", "[X]")
                .replace("30%", "[X]%")
                .replace("$2M", "$[X]M")
                .replace("6", "[X]"),
                "signals": item["signals"],
            }
            for item in PHRASES
        ]
    }
    with (
        patch("app.api.ai_routes.cache_manager.get", new=AsyncMock(return_value=cached)),
        patch("app.api.ai_routes.openai.AsyncOpenAI") as provider,
    ):
        response = await client.post("/ai/phrase-library", json=_request())

    assert response.status_code == 200, response.text
    assert response.json()["cached"] is True
    provider.assert_not_called()


@pytest.mark.asyncio
async def test_rejects_incomplete_provider_output_instead_of_caching_it(
    client: AsyncClient,
):
    provider = AsyncMock()
    provider.chat.completions.create = AsyncMock(return_value=_provider_response(PHRASES[:-1]))
    with (
        patch("app.api.ai_routes.settings") as settings,
        patch("app.api.ai_routes.openai.AsyncOpenAI", return_value=provider),
        patch("app.api.ai_routes.cache_manager.get", new=AsyncMock(return_value=None)),
        patch("app.api.ai_routes.cache_manager.set", new=AsyncMock()) as cache_set,
    ):
        settings.OPENAI_API_KEY = "sk-test"
        settings.OPENAI_MODEL = "gpt-4o-mini"
        response = await client.post("/ai/phrase-library", json=_request())

    assert response.status_code == 502
    cache_set.assert_not_awaited()


@pytest.mark.asyncio
async def test_count_and_axes_are_strictly_validated(client: AsyncClient):
    too_few = await client.post("/ai/phrase-library", json=_request(count=7))
    blank_axis = await client.post("/ai/phrase-library", json=_request(industry="  "))

    assert too_few.status_code == 422
    assert blank_axis.status_code == 422
