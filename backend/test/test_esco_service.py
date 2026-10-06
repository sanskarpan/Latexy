"""ESCO taxonomy lookup and conservative-normalization boundaries."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.services.esco_service import ESCO_API_URL, ESCOService


def _result(
    *,
    uri: str = "http://data.europa.eu/esco/skill/python",
    preferred: str = "Python (computer programming)",
    alternatives: list[str] | None = None,
) -> dict:
    return {
        "uri": uri,
        "title": preferred,
        "preferredLabel": {"en": preferred},
        "alternativeLabel": {"en": alternatives or []},
    }


@pytest.mark.asyncio
async def test_search_keeps_only_skill_namespace_and_requested_language():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(ESCO_API_URL)
        assert request.url.params["selectedVersion"] == "v1.2.1"
        return httpx.Response(
            200,
            json={
                "_embedded": {
                    "results": [
                        _result(alternatives=["Python"]),
                        _result(uri="http://data.europa.eu/esco/occupation/not-a-skill"),
                        {"uri": "http://data.europa.eu/esco/skill/malformed"},
                    ]
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        results, available = await ESCOService().search("Python", client=client)

    assert available is True
    assert results == [
        {
            "uri": "http://data.europa.eu/esco/skill/python",
            "preferred_label": "Python (computer programming)",
            "alternative_labels": ["Python"],
            "language": "en",
        }
    ]


@pytest.mark.asyncio
async def test_search_reports_provider_failure_without_fabricating_results():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        results, available = await ESCOService().search("Python", client=client)

    assert results == []
    assert available is False


@pytest.mark.asyncio
async def test_normalize_many_accepts_only_exact_preferred_or_alternative_labels():
    service = ESCOService()
    service.search = AsyncMock(
        side_effect=[
            (
                [
                    {
                        "uri": "http://data.europa.eu/esco/skill/python",
                        "preferred_label": "Python (computer programming)",
                        "alternative_labels": ["Python"],
                    }
                ],
                True,
            ),
            (
                [
                    {
                        "uri": "http://data.europa.eu/esco/skill/reactors",
                        "preferred_label": "operate chemical reactors",
                        "alternative_labels": [],
                    }
                ],
                True,
            ),
        ]
    )

    with patch("app.services.esco_service.settings.ENVIRONMENT", "production"):
        mappings, available = await service.normalize_many(["Python", "React.js"])

    assert available is True
    assert mappings[0]["matched"] is True
    assert mappings[0]["preferred_label"] == "Python (computer programming)"
    assert mappings[1] == {
        "input": "React.js",
        "preferred_label": "React.js",
        "uri": None,
        "matched": False,
    }


@pytest.mark.asyncio
async def test_normalize_many_discards_partial_taxonomy_when_any_lookup_fails():
    service = ESCOService()
    service.search = AsyncMock(
        side_effect=[
            ([{"uri": "u", "preferred_label": "Python", "alternative_labels": []}], True),
            ([], False),
        ]
    )

    with patch("app.services.esco_service.settings.ENVIRONMENT", "production"):
        _mappings, available = await service.normalize_many(["Python", "Terraform"])

    assert available is False


@pytest.mark.asyncio
async def test_test_environment_never_calls_external_provider():
    service = ESCOService()
    service.search = AsyncMock()

    mappings, available = await service.normalize_many(["Python"])

    assert available is False
    assert mappings[0]["matched"] is False
    service.search.assert_not_awaited()


@pytest.mark.parametrize(
    ("query", "language", "limit"),
    [("x", "en", 8), ("Python", "xx", 8), ("Python", "en", 21)],
)
@pytest.mark.asyncio
async def test_search_rejects_invalid_boundaries(query: str, language: str, limit: int):
    with pytest.raises(ValueError):
        await ESCOService().search(query, language=language, limit=limit)
